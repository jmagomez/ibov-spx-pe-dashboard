"""Precos diarios das acoes da carteira do Ibovespa (numerador do P/L em nivel)."""
from __future__ import annotations

import logging

import pandas as pd

from ..config import START_DATE
from .http import SourceUnavailable

log = logging.getLogger(__name__)


def fetch_ativos(codigos: list[str], inicio: str = START_DATE) -> pd.DataFrame:
    """Fechamento diario de cada ativo (datas x codigos B3), via yfinance.

    `Close` com auto_adjust=False: ajustado por desdobramento e grupamento,
    NAO por dividendo. E o preco certo para P/L -- um preco ajustado por
    dividendo rebaixa o passado e infla o multiplo historico. O ajuste por
    desdobramento deixa o preco antigo na base de acoes de hoje, a mesma base
    da quantidade teorica e do numero de acoes usados no denominador.

    Ativo sem resposta fica sem coluna; quem consome mede a cobertura por peso.
    Nenhum preco e preenchido.
    """
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise SourceUnavailable(f"yfinance nao instalado: {exc}") from exc
    simbolos = {f"{c}.SA": c for c in codigos}
    df = yf.download(list(simbolos), start=inicio, interval="1d", auto_adjust=False,
                     actions=False, progress=False, threads=True, group_by="column",
                     timeout=60)
    if df is None or df.empty:
        raise SourceUnavailable("yfinance devolveu vazio para os ativos do Ibovespa")
    close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]]
    if not isinstance(df.columns, pd.MultiIndex):
        close.columns = list(simbolos)[:1]
    close = close.rename(columns=simbolos)
    if getattr(close.index, "tz", None) is not None:
        close.index = close.index.tz_convert(None)
    close.index = pd.DatetimeIndex(close.index).normalize()
    close = close[~close.index.duplicated(keep="last")].sort_index()
    close = close.dropna(axis=1, how="all").astype("float64")
    if close.empty:
        raise SourceUnavailable("nenhum ativo do Ibovespa com preco no yfinance")
    log.info("precos de %d/%d ativos do Ibovespa", close.shape[1], len(codigos))
    return close
