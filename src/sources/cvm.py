"""Lucro liquido consolidado das companhias abertas, via dados abertos da CVM.

Duas bases, com coberturas diferentes -- e essa diferenca e material:

  DFP (Demonstracoes Financeiras Padronizadas): anual, disponivel desde 2010.
  ITR (Informacoes Trimestrais): trimestral, mas o portal mantem apenas os
      ultimos cinco anos.

Consequencia direta e inevitavel: para o Ibovespa nao existe, em fonte publica
gratuita, lucro TRIMESTRAL desde 2010. O trecho antigo da serie so pode ser
construido com lucro ANUAL. O pipeline constroi as duas partes, marca cada
observacao com a frequencia de origem e o dashboard as distingue visualmente.
Emendar as duas em uma linha unica sem sinalizacao seria enganoso.
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from ..config import (CVM_CACHE, CVM_CACHE_META, CVM_DFP_BASES, CVM_ITR_BASES)
from .http import SourceUnavailable, diagnosticar, get_qualquer

log = logging.getLogger(__name__)

# Conta 3.11 = "Lucro/Prejuizo Consolidado do Periodo" no plano padronizado da CVM.
CONTA_LUCRO = "3.11"
CONTA_LUCRO_ALT = "3.09"  # fallback: resultado liquido das operacoes continuadas


def _baixar(bases: tuple, arquivo: str) -> tuple[bytes, str]:
    """Baixa um zip da CVM tentando cada base equivalente (https e http).

    retries=2, nao 1. A politica anterior era de uma tentativa so, adotada
    quando o host se mostrou INALCANCAVEL a partir do runner -- e insistir com
    host inalcancavel so queima tempo de job. Mas erro de rota e erro
    intermitente produzem a mesma mensagem no requests, e tratar os dois como
    permanentes descarta o caso recuperavel. Duas tentativas com backoff curto
    custam segundos quando a rota nao existe (o connect_timeout de 8s corta
    rapido) e resgatam a falha transitoria.
    """
    urls = [base + arquivo for base in bases]
    return get_qualquer(urls, retries=2, backoff=2.0, timeout=180, connect_timeout=8)


def diagnostico_conectividade() -> dict:
    """Onde exatamente a conexao com a CVM quebra. Roda em segundos."""
    alvo = CVM_DFP_BASES[0] + "dfp_cia_aberta_2023.zip"
    return diagnosticar(alvo)


def _read_zip_csv(content: bytes, name_contains: str) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        # Case-insensitive: a CVM nomeia o arquivo "dfp_cia_aberta_DRE_con_2010.csv".
        # A comparacao sensivel a caixa nunca casava, e o erro resultante ("zip
        # sem arquivo dre_con") parecia problema de rede na execucao anterior,
        # quando o download ja funcionava.
        alvo = name_contains.lower()
        names = [n for n in zf.namelist() if alvo in n.lower() and n.lower().endswith(".csv")]
        if not names:
            raise SourceUnavailable(
                f"zip da CVM sem arquivo contendo '{name_contains}': {zf.namelist()[:8]}"
            )
        frames = []
        for n in names:
            with zf.open(n) as fh:
                frames.append(pd.read_csv(fh, sep=";", encoding="latin-1",
                                          dtype=str, low_memory=False))
        return pd.concat(frames, ignore_index=True)


def _extract_profit(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Filtra a linha de lucro consolidado do ultimo exercicio/periodo."""
    needed = {"CD_CONTA", "VL_CONTA", "DT_FIM_EXERC", "CD_CVM", "DENOM_CIA", "ORDEM_EXERC"}
    # CNPJ_CIA e opcional de proposito: se a CVM deixar de publica-lo, a
    # conciliacao cai para razao social em vez de o pipeline inteiro parar.
    missing = needed - set(df.columns)
    if missing:
        raise SourceUnavailable(f"colunas ausentes no CSV da CVM: {sorted(missing)}")

    sel = df[df["CD_CONTA"].isin([CONTA_LUCRO, CONTA_LUCRO_ALT])].copy()
    sel = sel[sel["ORDEM_EXERC"].str.strip().str.upper() == "ÚLTIMO"]
    if sel.empty:
        sel = df[df["CD_CONTA"].isin([CONTA_LUCRO, CONTA_LUCRO_ALT])].copy()
    if sel.empty:
        raise SourceUnavailable("nenhuma linha de lucro consolidado encontrada no CSV da CVM")

    sel["VL_CONTA"] = pd.to_numeric(
        sel["VL_CONTA"].str.replace(",", ".", regex=False), errors="coerce")
    if "ESCALA_MOEDA" in sel.columns:
        mult = sel["ESCALA_MOEDA"].str.upper().map({"MIL": 1_000.0, "UNIDADE": 1.0})
        sel["VL_CONTA"] = sel["VL_CONTA"] * mult.fillna(1_000.0)
    else:
        sel["VL_CONTA"] = sel["VL_CONTA"] * 1_000.0

    sel["DT_FIM_EXERC"] = pd.to_datetime(sel["DT_FIM_EXERC"], errors="coerce")
    sel = sel.dropna(subset=["DT_FIM_EXERC", "VL_CONTA"])
    # 3.11 tem prioridade sobre 3.09 quando ambos existem para a mesma companhia/data.
    sel["_prio"] = (sel["CD_CONTA"] == CONTA_LUCRO).astype(int)
    sel = (sel.sort_values(["CD_CVM", "DT_FIM_EXERC", "_prio"])
              .drop_duplicates(["CD_CVM", "DT_FIM_EXERC"], keep="last"))
    cols = ["CD_CVM", "DENOM_CIA", "DT_FIM_EXERC", "VL_CONTA"]
    if "CNPJ_CIA" in sel.columns:
        cols.append("CNPJ_CIA")
    out = sel[cols].copy()
    out.columns = (["cd_cvm", "empresa", "data_fim", "lucro"]
                   + (["cnpj"] if "CNPJ_CIA" in sel.columns else []))
    if "cnpj" not in out.columns:
        out["cnpj"] = ""
    out["freq"] = freq
    return out


def fetch_dfp_year(year: int) -> pd.DataFrame:
    """Lucro anual consolidado de todas as companhias, para um exercicio."""
    conteudo, _ = _baixar(CVM_DFP_BASES, f"dfp_cia_aberta_{year}.zip")
    return _extract_profit(_read_zip_csv(conteudo, "dre_con"), freq="A")


def fetch_itr_year(year: int) -> pd.DataFrame:
    """Lucro trimestral consolidado de todas as companhias, para um ano."""
    conteudo, _ = _baixar(CVM_ITR_BASES, f"itr_cia_aberta_{year}.zip")
    return _extract_profit(_read_zip_csv(conteudo, "dre_con"), freq="T")


def fetch_range(years: Iterable[int], kind: str) -> pd.DataFrame:
    """Coleta varios anos, tolerando anos individualmente indisponiveis.

    Um ano que falha e registrado e omitido -- nunca substituido por estimativa.
    Se TODOS falharem, levanta excecao: uma serie vazia silenciosa seria pior
    que um erro.
    """
    fn = fetch_dfp_year if kind == "DFP" else fetch_itr_year
    frames, falhas = [], []
    for y in years:
        try:
            frames.append(fn(y))
            log.info("CVM %s %d: ok", kind, y)
        except Exception as exc:  # noqa: BLE001
            falhas.append(f"{y}: {str(exc)[:120]}")
            log.warning("CVM %s %d indisponivel: %s", kind, y, str(exc)[:200])
    if not frames:
        raise SourceUnavailable(f"nenhum ano de {kind} obtido. {' | '.join(falhas[:3])}")
    df = pd.concat(frames, ignore_index=True)
    df.attrs["anos_falhos"] = falhas
    return df


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
# O que segue NAO relaxa a regra do repositorio de nao inventar numero. O cache
# guarda o resultado de uma coleta que de fato aconteceu, com a data em que
# aconteceu. Quando a CVM nao responde e o cache e usado, o pipeline registra a
# origem e a idade, o dashboard exibe as duas, e nenhum valor e extrapolado. A
# alternativa -- redescobrir a mesma serie de 16 exercicios a cada sabado, com
# uma fonte que ja se mostrou inconstante -- perde a serie inteira sempre que o
# portal esta fora do ar, e isso nao torna o resultado mais honesto: torna-o
# indisponivel.

COLUNAS_CACHE = ["cd_cvm", "empresa", "data_fim", "lucro", "freq", "cnpj"]


def salvar_cache(df: pd.DataFrame, origem: str) -> None:
    if df.empty:
        return
    CVM_CACHE.parent.mkdir(parents=True, exist_ok=True)
    df[COLUNAS_CACHE].to_csv(CVM_CACHE, index=False)
    CVM_CACHE_META.write_text(json.dumps({
        "coletado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "linhas": int(len(df)),
        "origem": origem,
        "data_fim_min": str(df["data_fim"].min().date()),
        "data_fim_max": str(df["data_fim"].max().date()),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("cache da CVM gravado: %d linhas", len(df))


def carregar_cache() -> tuple[pd.DataFrame, dict]:
    """Devolve (dados, metadados). DataFrame vazio se nao houver cache."""
    if not CVM_CACHE.exists():
        return pd.DataFrame(), {}
    df = pd.read_csv(CVM_CACHE, parse_dates=["data_fim"], dtype={"cnpj": str})
    faltando = set(COLUNAS_CACHE) - set(df.columns)
    if faltando:
        log.warning("cache da CVM ignorado: colunas ausentes %s", sorted(faltando))
        return pd.DataFrame(), {}
    meta = {}
    if CVM_CACHE_META.exists():
        try:
            meta = json.loads(CVM_CACHE_META.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            meta = {}
    if meta.get("coletado_em_utc"):
        try:
            col = datetime.fromisoformat(meta["coletado_em_utc"])
            meta["idade_dias"] = (datetime.now(timezone.utc) - col).days
        except Exception:  # noqa: BLE001
            pass
    return df, meta
