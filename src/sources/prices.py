"""Precos diarios de fechamento dos indices.

Cadeia de provedores, nao "fallback com valor default": tenta cada um em ordem
e registra QUAL respondeu e QUE horizonte trouxe. Se nenhum responder, levanta
excecao. Em nenhuma hipotese um preco e estimado, interpolado ou herdado de
execucao anterior.

Historico do problema, para quem for mexer aqui:

  Execucao #2 (08/08/2026) -- Stooq devolveu pagina de bloqueio em vez de CSV.
  Execucao #3 (08/08/2026) -- Yahoo chart v8 devolveu 429 nas tres tentativas.

Os dois casos tem a mesma raiz: a requisicao parte de um runner do GitHub
Actions e ambos limitam faixas de nuvem. As contramedidas implementadas:

  1. yfinance      - a biblioteca resolve cookie e crumb do Yahoo, mantem
                     sessao e usa curl_cffi para se apresentar como navegador
                     no handshake TLS. E essa combinacao, e nao o User-Agent
                     sozinho, que costuma derrubar o 429 em runner de CI.
  2. yahoo_crumb   - o mesmo fluxo cookie/crumb implementado a mao, para o caso
                     de a biblioteca falhar por outro motivo.
  3. stooq         - CSV direto, util em execucao local.
  4. fred          - So S&P 500. A serie SP500 do FRED cobre apenas os ultimos
                     ~10 anos por licenca. Entra como ultimo recurso: horizonte
                     menor com dado bom e melhor que serie nenhuma, desde que o
                     encurtamento seja declarado -- e ele e, no diagnostico.

O horizonte efetivo nunca e presumido: quem consome le `inicio` e `fim` no
painel de diagnostico e sabe exatamente o que a serie cobre.
"""
from __future__ import annotations

import io
import json
import logging
import time

import pandas as pd
import requests

from ..config import START_DATE, STOOQ_TEMPLATE
from .http import UA, SourceUnavailable, get

log = logging.getLogger(__name__)

YAHOO_CHART = ("https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
               "?period1=0&period2=9999999999&interval=1d")
YAHOO_COOKIE_URL = "https://fc.yahoo.com"
YAHOO_CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

SYMBOLS = {
    "spx":  {"yahoo": "^GSPC", "stooq": "^spx", "fred": "SP500"},
    "ibov": {"yahoo": "^BVSP", "stooq": "^bvp", "fred": None},
}

_BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


# ---------------------------------------------------------------------------
# Parsers (puros, testaveis offline)
# ---------------------------------------------------------------------------

def _parse_yahoo_payload(payload: dict, symbol: str) -> pd.Series:
    """Extrai a serie de fechamento do payload do endpoint chart."""
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
    return _limpar(s)


def _parse_fred_csv(texto: str, series_id: str) -> pd.Series:
    """FRED usa '.' para observacao ausente; nunca preencher, sempre descartar."""
    df = pd.read_csv(io.StringIO(texto))
    if df.shape[1] < 2:
        raise SourceUnavailable(f"CSV do FRED inesperado para {series_id}: {list(df.columns)}")
    col_data, col_val = df.columns[0], df.columns[1]
    idx = pd.to_datetime(df[col_data], errors="coerce")
    val = pd.to_numeric(df[col_val].astype(str).str.strip().replace(".", pd.NA),
                        errors="coerce")
    return _limpar(pd.Series(val.values, index=pd.DatetimeIndex(idx)))


def _limpar(s: pd.Series) -> pd.Series:
    s = s[~s.index.isna()].dropna().astype("float64")
    return s[~s.index.duplicated(keep="last")].sort_index()


# ---------------------------------------------------------------------------
# Provedores
# ---------------------------------------------------------------------------

def _via_yfinance(indice: str) -> pd.Series:
    """Biblioteca yfinance: cuida de cookie, crumb, sessao e impersonacao TLS."""
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise SourceUnavailable(f"yfinance nao instalado: {exc}") from exc
    simbolo = SYMBOLS[indice]["yahoo"]
    df = yf.Ticker(simbolo).history(period="max", interval="1d", auto_adjust=False,
                                    actions=False, timeout=45, raise_errors=True)
    if df is None or df.empty or "Close" not in df.columns:
        raise SourceUnavailable(f"yfinance devolveu vazio para {simbolo}")
    s = df["Close"]
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_convert(None)
    s.index = pd.DatetimeIndex(s.index).normalize()
    return _limpar(s)


def _via_yahoo_crumb(indice: str) -> pd.Series:
    """Fluxo cookie -> crumb -> chart, feito a mao com sessao propria."""
    simbolo = SYMBOLS[indice]["yahoo"]
    ses = requests.Session()
    ses.headers.update(_BROWSER_HEADERS)
    try:
        ses.get(YAHOO_COOKIE_URL, timeout=20)  # 404 e esperado; o que importa e o cookie
    except Exception as exc:  # noqa: BLE001
        log.warning("cookie do Yahoo nao obtido: %s", exc)
    crumb = ""
    try:
        r = ses.get(YAHOO_CRUMB_URL, timeout=20)
        if r.ok and r.text and "<" not in r.text:
            crumb = r.text.strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("crumb do Yahoo nao obtido: %s", exc)

    url = YAHOO_CHART.format(symbol=requests.utils.quote(simbolo, safe=""))
    if crumb:
        url += "&crumb=" + requests.utils.quote(crumb, safe="")
    ultimo = None
    for tentativa in range(1, 4):
        try:
            r = ses.get(url, timeout=45)
            if r.status_code == 429:
                raise SourceUnavailable("429 (limite de requisicoes)")
            r.raise_for_status()
            return _parse_yahoo_payload(json.loads(r.text), simbolo)
        except Exception as exc:  # noqa: BLE001
            ultimo = exc
            log.warning("yahoo_crumb tentativa %d para %s: %s", tentativa, simbolo, exc)
            time.sleep(6 * tentativa)
    raise SourceUnavailable(f"yahoo_crumb falhou para {simbolo}: {ultimo}")


def _via_stooq(indice: str) -> pd.Series:
    simbolo = SYMBOLS[indice]["stooq"]
    raw = get(STOOQ_TEMPLATE.format(symbol=simbolo), headers=_BROWSER_HEADERS)
    df = pd.read_csv(io.BytesIO(raw))
    if "Date" not in df.columns or "Close" not in df.columns:
        raise SourceUnavailable(
            f"layout inesperado do Stooq para {simbolo}: colunas={list(df.columns)[:3]}")
    idx = pd.to_datetime(df["Date"], errors="coerce")
    return _limpar(pd.Series(pd.to_numeric(df["Close"], errors="coerce").values,
                             index=pd.DatetimeIndex(idx)))


def _via_fred(indice: str) -> pd.Series:
    """Somente S&P 500, e com horizonte reduzido (~10 anos, por licenca do FRED)."""
    series_id = SYMBOLS[indice].get("fred")
    if not series_id:
        raise SourceUnavailable(f"FRED nao publica serie diaria para {indice}")
    raw = get(FRED_CSV.format(series=series_id), headers=_BROWSER_HEADERS)
    return _parse_fred_csv(raw.decode("utf-8", errors="replace"), series_id)


PROVEDORES = {
    "yfinance": _via_yfinance,
    "yahoo_crumb": _via_yahoo_crumb,
    "stooq": _via_stooq,
    "fred": _via_fred,
}
ORDEM = ("yfinance", "yahoo_crumb", "stooq", "fred")


def fetch_index_close(indice: str):
    """Devolve (serie, descricao_do_provedor).

    O filtro por START_DATE e aplicado, mas NAO se exige que a serie comece em
    2010: se o provedor so cobre um trecho, usa-se o trecho e o horizonte real
    aparece no diagnostico. Exigir 16 anos e descartar 10 seria trocar dado bom
    por dado nenhum.
    """
    if indice not in SYMBOLS:
        raise ValueError(f"indice desconhecido: {indice}")
    erros = []
    for nome in ORDEM:
        try:
            s = _limpar(PROVEDORES[nome](indice)).loc[START_DATE:]
            if s.empty:
                raise SourceUnavailable(f"serie vazia apos {START_DATE}")
            s.name = indice
            anos = (s.index.max() - s.index.min()).days / 365.25
            desc = f"provedor: {nome}; horizonte: {anos:.1f} anos ({len(s)} pregoes)"
            if s.index.min() > pd.Timestamp(START_DATE) + pd.Timedelta(days=200):
                desc += f"; ATENCAO: cobertura comeca em {s.index.min().date()}, " \
                        f"nao em {START_DATE}"
            log.info("%s -> %s", indice, desc)
            return s, desc
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{nome}: {str(exc)[:160]}")
            log.warning("%s indisponivel em %s: %s", indice, nome, exc)
    raise SourceUnavailable(f"{indice}: nenhum provedor respondeu. " + " | ".join(erros))
