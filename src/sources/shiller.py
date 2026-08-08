"""CAPE (Shiller P/E) do S&P 500, a partir da planilha ie_data de Robert Shiller.

Serve como contraponto ao P/E trailing: usa lucro real medio de 10 anos, o que
elimina a distorcao mecanica de o denominador colapsar em recessao. Nao
substitui o P/E trailing; a leitura conjunta e que informa.
"""
from __future__ import annotations

import io
import logging

import pandas as pd

from ..config import SHILLER_XLS, START_DATE
from .http import SourceUnavailable, get

log = logging.getLogger(__name__)


def _shiller_date_to_ts(v: float):
    """A planilha codifica data como AAAA.MM com mes fracionario (1900.1 = jan/1900)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float("nan")
    year = int(f)
    month = int(round((f - year) * 100))
    if month < 1 or month > 12:
        return float("nan")
    return pd.Timestamp(year=year, month=month, day=1)


def fetch_cape() -> pd.Series:
    """Serie mensal do CAPE, do START_DATE em diante."""
    raw = get(SHILLER_XLS)
    xls = pd.ExcelFile(io.BytesIO(raw))
    sheet = next((s for s in xls.sheet_names if s.strip().lower() == "data"),
                 xls.sheet_names[0])
    df = xls.parse(sheet, header=None)

    header_row = None
    for i in range(min(30, len(df))):
        row = " ".join(str(v).lower() for v in df.iloc[i].tolist())
        if "cape" in row:
            header_row = i
            break
    if header_row is None:
        raise SourceUnavailable("coluna CAPE nao encontrada na planilha Shiller")

    cape_col = next(
        (c for c in df.columns if str(df.iloc[header_row][c]).strip().lower() == "cape"),
        None,
    )
    if cape_col is None:
        cape_col = next(
            (c for c in df.columns if "cape" in str(df.iloc[header_row][c]).lower()),
            None,
        )
    if cape_col is None:
        raise SourceUnavailable("coluna CAPE nao identificada")

    body = df.iloc[header_row + 1:]
    dates = body[df.columns[0]].map(_shiller_date_to_ts)
    vals = pd.to_numeric(body[cape_col], errors="coerce")
    s = pd.Series(vals.values, index=pd.DatetimeIndex(dates), name="cape").dropna()
    s = s[~s.index.isna()].sort_index().loc[START_DATE:]
    if s.empty:
        raise SourceUnavailable("serie CAPE vazia apos filtro de data")
    log.info("CAPE: %d observacoes mensais ate %s", len(s), s.index.max().date())
    return s
