"""Precos diarios de fechamento dos indices (Stooq, CSV livre)."""
from __future__ import annotations

import io
import logging

import pandas as pd

from ..config import START_DATE, STOOQ_TEMPLATE
from .http import SourceUnavailable, get

log = logging.getLogger(__name__)


def fetch_index_close(symbol: str) -> pd.Series:
    """Serie diaria de fechamento do indice, do START_DATE em diante.

    Stooq devolve CSV com colunas Date,Open,High,Low,Close,Volume. Se o layout
    mudar, isto quebra de forma barulhenta em vez de devolver algo plausivel.
    """
    raw = get(STOOQ_TEMPLATE.format(symbol=symbol))
    df = pd.read_csv(io.BytesIO(raw))
    if "Date" not in df.columns or "Close" not in df.columns:
        raise SourceUnavailable(
            f"layout inesperado do Stooq para {symbol}: colunas={list(df.columns)}"
        )
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date", "Close"]).set_index("Date").sort_index()
    s = df.loc[START_DATE:, "Close"].astype("float64")
    s.name = symbol
    if s.empty:
        raise SourceUnavailable(f"serie vazia para {symbol} apos {START_DATE}")
    log.info("%s: %d pregoes de %s a %s", symbol, len(s),
             s.index.min().date(), s.index.max().date())
    return s
