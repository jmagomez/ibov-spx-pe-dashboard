"""Planilha ie_data de Robert Shiller (Yale).

Duas coisas saem daqui:

  CAPE     - contraponto ao P/E trailing; usa lucro real medio de 10 anos.
  Earnings - a coluna E e o lucro por acao do S&P 500 acumulado em 12 meses,
             mensal. E a mesma linhagem de dado da S&P DJI, e serve de fonte
             alternativa quando o arquivo oficial da S&P nao esta acessivel --
             o que ocorreu na execucao #4, com 403 vindo de spglobal.com.

Ponto metodologico importante: a coluna E JA e acumulada em 12 meses. Aplicar
sobre ela a soma movel de quatro trimestres usada na serie da S&P DJI
quadruplicaria o denominador. Por isso ela entra direto como LPA 12m.
"""
from __future__ import annotations

import io
import logging
import math

import pandas as pd

from ..config import SHILLER_XLS, START_DATE
from .http import SourceUnavailable, get

log = logging.getLogger(__name__)


def _shiller_date_to_ts(v):
    """A planilha codifica data como AAAA.MM com mes fracionario (2010.01 = jan/2010)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return pd.NaT
    if math.isnan(f) or math.isinf(f):
        return pd.NaT
    year = int(f)
    if year < 1800 or year > 2200:
        return pd.NaT
    month = int(round((f - year) * 100))
    if month < 1 or month > 12:
        return pd.NaT
    return pd.Timestamp(year=year, month=month, day=1)


def _abrir_tabela() -> pd.DataFrame:
    """Devolve a aba Data crua, com a linha de cabecalho ja localizada."""
    raw = get(SHILLER_XLS)
    xls = pd.ExcelFile(io.BytesIO(raw))
    sheet = next((s for s in xls.sheet_names if s.strip().lower() == "data"),
                 xls.sheet_names[0])
    df = xls.parse(sheet, header=None)
    header_row = None
    for i in range(min(30, len(df))):
        linha = " ".join(str(v).lower() for v in df.iloc[i].tolist())
        if "cape" in linha:
            header_row = i
            break
    if header_row is None:
        raise SourceUnavailable("linha de cabecalho (com CAPE) nao encontrada na planilha Shiller")
    df.attrs["header_row"] = header_row
    return df


def fetch_tabela() -> pd.DataFrame:
    """DataFrame mensal com colunas: preco, lucro_ttm, cape.

    Layout historico da aba Data: coluna 0 = Date, 1 = P, 2 = D, 3 = E.
    A posicao e usada apenas para P/D/E; o CAPE e localizado pelo rotulo.
    Um teste de sanidade rejeita a leitura se as colunas nao forem numericas.
    """
    df = _abrir_tabela()
    h = df.attrs["header_row"]
    cols = list(df.columns)
    body = df.iloc[h + 1:]

    datas = pd.DatetimeIndex(body[cols[0]].map(_shiller_date_to_ts))
    preco = pd.to_numeric(body[cols[1]], errors="coerce")
    lucro = pd.to_numeric(body[cols[3]], errors="coerce")

    cape_col = next((c for c in cols
                     if "cape" in str(df.iloc[h][c]).strip().lower()), None)
    cape = (pd.to_numeric(body[cape_col], errors="coerce")
            if cape_col is not None else pd.Series(index=body.index, dtype="float64"))

    out = pd.DataFrame({"preco": preco.values, "lucro_ttm": lucro.values,
                        "cape": cape.values}, index=datas)
    out = out[~out.index.isna()].sort_index().loc[START_DATE:]
    if out.empty:
        raise SourceUnavailable("tabela Shiller vazia apos filtro de data")
    if out["lucro_ttm"].notna().sum() < 12:
        raise SourceUnavailable(
            "coluna de lucro da planilha Shiller nao parece numerica; layout mudou")
    log.info("Shiller: %d meses de %s a %s (lucro=%d, cape=%d)", len(out),
             out.index.min().date(), out.index.max().date(),
             int(out["lucro_ttm"].notna().sum()), int(out["cape"].notna().sum()))
    return out


def fetch_cape() -> pd.Series:
    """Serie mensal do CAPE."""
    s = fetch_tabela()["cape"].dropna()
    if s.empty:
        raise SourceUnavailable("serie CAPE vazia")
    return s


def fetch_eps_ttm() -> pd.Series:
    """Serie mensal do LPA 12m do S&P 500 (coluna E). JA acumulada em 12 meses."""
    s = fetch_tabela()["lucro_ttm"].dropna()
    if s.empty:
        raise SourceUnavailable("serie de lucro da Shiller vazia")
    return s
