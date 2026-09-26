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

    sel["VL_CONTA"] = _escalar(sel)

    sel["DT_FIM_EXERC"] = pd.to_datetime(sel["DT_FIM_EXERC"], errors="coerce")
    sel = sel.dropna(subset=["DT_FIM_EXERC", "VL_CONTA"])
    # Zero exato e DRE consolidada vazia (companhia que so publica a individual),
    # nao lucro zero. Ver metrics.sem_zero_de_formulario: la o mesmo filtro limpa
    # o que ja estava no cache antes desta correcao.
    sel = sel[sel["VL_CONTA"] != 0]
    # ITR: a DRE traz, para a mesma data de fim, DUAS linhas -- a do trimestre
    # (inicio no comeco do trimestre) e a do acumulado no ano (inicio em 1o de
    # janeiro). Ate aqui a escolha entre elas ficava a cargo do desempate de um
    # sort_values nao estavel. No dado real ela caiu no trimestre (mediana de
    # (1T+2T+3T)/anual = 0,74; acumulado daria ~1,5), mas por acaso de ordem,
    # nao por regra. Agora e regra: fica a linha com duracao de ate ~um
    # trimestre. Sem DT_INI_EXERC no arquivo, o comportamento anterior se
    # mantem.
    if freq == "T" and "DT_INI_EXERC" in sel.columns:
        ini = pd.to_datetime(sel["DT_INI_EXERC"], errors="coerce")
        dur = (sel["DT_FIM_EXERC"] - ini).dt.days
        sel = sel[dur.isna() | (dur <= 100)]
    # 3.11 tem prioridade sobre 3.09 quando ambos existem para a mesma companhia/data.
    sel["_prio"] = (sel["CD_CONTA"] == CONTA_LUCRO).astype(int)
    sel = (sel.sort_values(["CD_CVM", "DT_FIM_EXERC", "_prio"], kind="mergesort")
              .drop_duplicates(["CD_CVM", "DT_FIM_EXERC"], keep="last"))
    cols = ["CD_CVM", "DENOM_CIA", "DT_FIM_EXERC", "VL_CONTA"]
    if "CNPJ_CIA" in sel.columns:
        cols.append("CNPJ_CIA")
    ctrl = _lucro_controladora(df, sel, freq)
    out = sel[cols].copy()
    out.columns = (["cd_cvm", "empresa", "data_fim", "lucro"]
                   + (["cnpj"] if "CNPJ_CIA" in sel.columns else []))
    if "cnpj" not in out.columns:
        out["cnpj"] = ""
    out["freq"] = freq
    out["lucro_ctrl"] = ctrl.reindex(out.index).fillna(out["lucro"]).values
    return out


def _escalar(sel: pd.DataFrame) -> pd.Series:
    v = pd.to_numeric(sel["VL_CONTA"].astype(str).str.replace(",", ".", regex=False),
                      errors="coerce")
    if "ESCALA_MOEDA" in sel.columns:
        mult = sel["ESCALA_MOEDA"].astype(str).str.upper().map({"MIL": 1_000.0, "UNIDADE": 1.0})
        return v * mult.fillna(1_000.0)
    return v * 1_000.0


def _lucro_controladora(df: pd.DataFrame, sel: pd.DataFrame, freq: str) -> pd.Series:
    """Lucro ATRIBUIVEL AOS SOCIOS DA CONTROLADORA, alinhado ao indice de `sel`.

    A conta de lucro (3.11, ou 3.09 no leiaute de alguns bancos) inclui a
    parcela dos minoritarios das controladas. Para comparar com o preco da acao
    da controladora -- que e o que o indice carrega --, o certo e a subconta
    "Atribuido a Socios da Empresa Controladora" (codigo da conta-mae + ".01").
    Medido no DFP 2025: 432 de 438 companhias publicam a subconta. Nas que nao
    publicam, ou que a publicam zerada (Klabin, 2025), fica o valor da
    conta-mae -- o mesmo criterio de "zero e formulario vazio" de
    metrics.sem_zero_de_formulario. Casos em que a diferenca pesa: Banco do
    Brasil (R$ 16,8 bi consolidado x R$ 13,7 bi da controladora em 2025),
    Energisa (3,1 x 2,2), Metalurgica Gerdau (1,4 x 0,5).

    Devolve NaN onde nao ha subconta utilizavel; quem chama preenche com a
    conta-mae.
    """
    if "DS_CONTA" not in df.columns or sel.empty:
        return pd.Series(index=sel.index, dtype="float64")
    filhos = df[df["CD_CONTA"].isin([CONTA_LUCRO + ".01", CONTA_LUCRO_ALT + ".01"])
                & df["DS_CONTA"].astype(str).str.contains("controladora", case=False, na=False)]
    filhos = filhos[filhos["ORDEM_EXERC"].str.strip().str.upper() == "ÚLTIMO"].copy()
    if filhos.empty:
        return pd.Series(index=sel.index, dtype="float64")
    filhos["_v"] = _escalar(filhos)
    filhos["DT_FIM_EXERC"] = pd.to_datetime(filhos["DT_FIM_EXERC"], errors="coerce")
    filhos["_mae"] = filhos["CD_CONTA"].str[:-3]
    chave = ["CD_CVM", "DT_FIM_EXERC", "_mae"]
    if "DT_INI_EXERC" in filhos.columns and "DT_INI_EXERC" in sel.columns:
        filhos["_ini"] = pd.to_datetime(filhos["DT_INI_EXERC"], errors="coerce")
        chave.append("_ini")
    filhos = filhos.dropna(subset=["_v"])
    filhos = filhos[filhos["_v"] != 0].drop_duplicates(chave, keep="last")
    base = sel[["CD_CVM", "DT_FIM_EXERC", "CD_CONTA"]].rename(columns={"CD_CONTA": "_mae"})
    if "_ini" in chave:
        base["_ini"] = pd.to_datetime(sel["DT_INI_EXERC"], errors="coerce")
    base = base.reset_index()
    m = base.merge(filhos[chave + ["_v"]], on=chave, how="left").set_index("index")
    return m["_v"].reindex(sel.index)


COLUNAS_ACOES = ["cnpj", "data_ref", "versao", "on", "pn", "tes_on", "tes_pn"]


def _extract_acoes(cap: pd.DataFrame) -> pd.DataFrame:
    """Numero de acoes por companhia e data, do arquivo composicao_capital.

    ATENCAO a unidade: o arquivo nao tem coluna de escala e mistura as duas.
    No DFP 2025, Petrobras informa 7.442.231.382 ON (unidades) e o Itau,
    5.617.743 ON (MILHARES -- o Itau tem 5,6 bilhoes de ON). Vale, Santander,
    Taesa e Itausa tambem vem em milhares. A escala e resolvida depois, contra
    a quantidade teorica da B3 (ver ibov_nivel.fracao_na_carteira): quantidade
    no indice maior que o numero de acoes da companhia so e possivel se o
    numero estiver em milhares.
    """
    col = {"CNPJ_CIA": "cnpj", "DT_REFER": "data_ref", "VERSAO": "versao",
           "QT_ACAO_ORDIN_CAP_INTEGR": "on", "QT_ACAO_PREF_CAP_INTEGR": "pn",
           "QT_ACAO_ORDIN_TESOURO": "tes_on", "QT_ACAO_PREF_TESOURO": "tes_pn"}
    falta = set(col) - set(cap.columns)
    if falta:
        raise SourceUnavailable(f"composicao_capital sem colunas {sorted(falta)}")
    out = cap[list(col)].rename(columns=col).copy()
    for c in ("versao", "on", "pn", "tes_on", "tes_pn"):
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    out["data_ref"] = pd.to_datetime(out["data_ref"], errors="coerce")
    return out.dropna(subset=["data_ref"])


def _ano(bases: tuple, arquivo: str, freq: str) -> pd.DataFrame:
    conteudo, _ = _baixar(bases, arquivo)
    df = _extract_profit(_read_zip_csv(conteudo, "dre_con"), freq=freq)
    try:
        df.attrs["acoes"] = _extract_acoes(_read_zip_csv(conteudo, "composicao_capital"))
    except Exception as exc:  # noqa: BLE001
        log.warning("composicao do capital indisponivel em %s: %s", arquivo, str(exc)[:160])
    return df


def fetch_dfp_year(year: int) -> pd.DataFrame:
    """Lucro anual consolidado de todas as companhias, para um exercicio.

    O numero de acoes (composicao do capital) vem no mesmo zip e sai em
    df.attrs["acoes"].
    """
    return _ano(CVM_DFP_BASES, f"dfp_cia_aberta_{year}.zip", "A")


def fetch_itr_year(year: int) -> pd.DataFrame:
    """Lucro trimestral consolidado de todas as companhias, para um ano."""
    return _ano(CVM_ITR_BASES, f"itr_cia_aberta_{year}.zip", "T")


def fetch_range(years: Iterable[int], kind: str) -> pd.DataFrame:
    """Coleta varios anos, tolerando anos individualmente indisponiveis.

    Um ano que falha e registrado e omitido -- nunca substituido por estimativa.
    Se TODOS falharem, levanta excecao: uma serie vazia silenciosa seria pior
    que um erro.
    """
    fn = fetch_dfp_year if kind == "DFP" else fetch_itr_year
    frames, falhas, ausentes = [], [], []
    for y in years:
        try:
            frames.append(fn(y))
            log.info("CVM %s %d: ok", kind, y)
        except Exception as exc:  # noqa: BLE001
            # 404 e informacao, nao avaria: o exercicio simplesmente nao foi
            # publicado no portal. Tratar os dois como a mesma coisa faz o
            # diagnostico dizer "falhou" quando a resposta certa e "ainda nao
            # existe" -- e leva a procurar defeito onde nao ha.
            if "404" in str(exc):
                ausentes.append(y)
                log.info("CVM %s %d: nao publicado no portal (404)", kind, y)
            else:
                falhas.append(f"{y}: {str(exc)[:120]}")
                log.warning("CVM %s %d indisponivel: %s", kind, y, str(exc)[:200])
    if not frames:
        raise SourceUnavailable(
            f"nenhum ano de {kind} obtido. nao publicados: {ausentes}; "
            f"erros: {' | '.join(falhas[:3])}")
    acoes = [f.attrs["acoes"] for f in frames if isinstance(f.attrs.get("acoes"), pd.DataFrame)]
    for f in frames:
        f.attrs = {}
    df = pd.concat(frames, ignore_index=True)
    df.attrs["anos_falhos"] = falhas
    df.attrs["anos_ausentes"] = ausentes
    df.attrs["acoes"] = (pd.concat(acoes, ignore_index=True) if acoes
                         else pd.DataFrame(columns=COLUNAS_ACOES))
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

COLUNAS_CACHE = ["cd_cvm", "empresa", "data_fim", "lucro", "freq", "cnpj", "lucro_ctrl"]
ACOES_CACHE_NOME = "acoes_cvm.csv"


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
    if "lucro_ctrl" not in df.columns and "lucro" in df.columns:
        # Cache gravado antes de 26/09/2026: sem a subconta da controladora.
        df["lucro_ctrl"] = df["lucro"]
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


def salvar_acoes(acoes: pd.DataFrame) -> None:
    if acoes is None or acoes.empty:
        return
    (CVM_CACHE.parent / ACOES_CACHE_NOME).parent.mkdir(parents=True, exist_ok=True)
    acoes[COLUNAS_ACOES].sort_values(["cnpj", "data_ref", "versao"]).to_csv(
        CVM_CACHE.parent / ACOES_CACHE_NOME, index=False)


def carregar_acoes() -> pd.DataFrame:
    caminho = CVM_CACHE.parent / ACOES_CACHE_NOME
    if not caminho.exists():
        return pd.DataFrame(columns=COLUNAS_ACOES)
    df = pd.read_csv(caminho, parse_dates=["data_ref"], dtype={"cnpj": str})
    return df if set(COLUNAS_ACOES) <= set(df.columns) else pd.DataFrame(columns=COLUNAS_ACOES)
