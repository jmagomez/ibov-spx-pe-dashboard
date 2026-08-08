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
import logging
import zipfile
from typing import Iterable

import pandas as pd

from ..config import CVM_DFP_BASE, CVM_ITR_BASE
from .http import SourceUnavailable, get

log = logging.getLogger(__name__)

# Conta 3.11 = "Lucro/Prejuizo Consolidado do Periodo" no plano padronizado da CVM.
CONTA_LUCRO = "3.11"
CONTA_LUCRO_ALT = "3.09"  # fallback: resultado liquido das operacoes continuadas


def _read_zip_csv(content: bytes, name_contains: str) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = [n for n in zf.namelist() if name_contains in n and n.endswith(".csv")]
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
    out = sel[["CD_CVM", "DENOM_CIA", "DT_FIM_EXERC", "VL_CONTA"]].copy()
    out.columns = ["cd_cvm", "empresa", "data_fim", "lucro"]
    out["freq"] = freq
    return out


def fetch_dfp_year(year: int) -> pd.DataFrame:
    """Lucro anual consolidado de todas as companhias, para um exercicio."""
    url = f"{CVM_DFP_BASE}dfp_cia_aberta_{year}.zip"
    return _extract_profit(_read_zip_csv(get(url), "dre_con"), freq="A")


def fetch_itr_year(year: int) -> pd.DataFrame:
    """Lucro trimestral consolidado de todas as companhias, para um ano."""
    url = f"{CVM_ITR_BASE}itr_cia_aberta_{year}.zip"
    return _extract_profit(_read_zip_csv(get(url), "dre_con"), freq="T")


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
            falhas.append(f"{y}: {exc}")
            log.warning("CVM %s %d indisponivel: %s", kind, y, exc)
    if not frames:
        raise SourceUnavailable(f"nenhum ano de {kind} obtido. {' | '.join(falhas[:5])}")
    df = pd.concat(frames, ignore_index=True)
    df.attrs["anos_falhos"] = falhas
    return df
