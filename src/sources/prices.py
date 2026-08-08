"""Precos diarios de fechamento dos indices.

Estrategia multi-fonte, e nao "fallback com valor default": tenta provedores em
ordem e registra QUAL respondeu. Se nenhum responder, levanta excecao -- em
nenhuma hipotese um preco e estimado, interpolado ou herdado de execucao
anterior.

Motivo de existirem dois provedores: na primeira execucao real deste pipeline
(08/08/2026) o Stooq devolveu uma pagina de bloqueio em vez de CSV quando
chamado a partir de um runner do GitHub Actions -- comportamento tipico de
bloqueio a IP de datacenter. O provedor Yahoo passou a ser o primario e o
Stooq permanece como alternativa, util em execucao local.
"""
from __future__ import annotations

import io
import json
import logging
from typing import Callable

import pandas as pd

from ..config import START_DATE, STOOQ_TEMPLATE
from .http import SourceUnavailable, get

log = logging.getLogger(__name__)

YAHOO_TEMPLATE = ("https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                  "?period1=0&period2=9999999999&interval=1d")

# Simbolos equivalentes por provedor.
SYMBOLS = {
    "spx":  {"yahoo": "%5EGSPC", "stooq": "^spx"},
    "ibov": {"yahoo": "%5EBVSP", "stooq": "^bvp"},
}


def _from_yahoo(symbol: str) -> pd.Series:
    """Le o endpoint chart v8 do Yahoo Finance (JSON, sem chave)."""
    raw = get(YAHOO_TEMPLATE.format(symbol=symbol),
              headers={"Accept": "application/json"})
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SourceUnavailable(f"Yahoo nao devolveu JSON para {symbol}: {exc}") from exc
    return _parse_yahoo_payload(payload, symbol)


def _parse_yahoo_payload(payload: dict, symbol: str) -> pd.Series:
    """Extrai a serie de fechamento do payload. Separado para ser testavel."""
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise SourceUnavailable(f"Yahoo retornou erro para {symbol}: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise SourceUnavailable(f"Yahoo sem 'result' para {symbol}")
    res = results[0]
    ts = res.get("timestamp")
    quotes = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quotes.get("close")
    if not ts or not closes:
        raise SourceUnavailable(f"Yahoo sem timestamp/close para {symbol}")
    s = pd.Series(closes, index=pd.to_datetime(ts, unit="s", utc=True))
    s.index = s.index.tz_convert(None).normalize()
    s = s.dropna().astype("float64")
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


def _from_stooq(symbol: str) -> pd.Series:
    """Le o CSV diario do Stooq."""
    raw = get(STOOQ_TEMPLATE.format(symbol=symbol))
    df = pd.read_csv(io.BytesIO(raw))
    if "Date" not in df.columns or "Close" not in df.columns:
        raise SourceUnavailable(
            f"layout inesperado do Stooq para {symbol}: colunas={list(df.columns)[:4]}"
        )
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date", "Close"]).set_index("Date").sort_index()
    return df["Close"].astype("float64")


PROVEDORES: dict = {
    "yahoo": _from_yahoo,
    "stooq": _from_stooq,
}
ORDEM = ("yahoo", "stooq")


def fetch_index_close(indice: str):
    """Serie diaria de fechamento do indice, do START_DATE em diante.

    Devolve (serie, nome_do_provedor). O nome do provedor vai para o painel de
    diagnostico: saber de onde veio o numero faz parte do numero.
    """
    if indice not in SYMBOLS:
        raise ValueError(f"indice desconhecido: {indice}")
    erros = []
    for nome in ORDEM:
        simbolo = SYMBOLS[indice][nome]
        try:
            s = PROVEDORES[nome](simbolo).loc[START_DATE:]
            if s.empty:
                raise SourceUnavailable(f"serie vazia apos {START_DATE}")
            s.name = indice
            log.info("%s via %s: %d pregoes de %s a %s", indice, nome, len(s),
                     s.index.min().date(), s.index.max().date())
            return s, nome
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{nome}: {exc}")
            log.warning("%s indisponivel em %s: %s", indice, nome, exc)
    raise SourceUnavailable(f"{indice}: nenhum provedor respondeu. " + " | ".join(erros))
