"""Juros de 10 anos dos EUA, nominal e real, do FRED (St. Louis Fed).

  DGS10  - Treasury de 10 anos, taxa nominal, % a.a., diaria.
  DFII10 - TIPS de 10 anos, taxa REAL, % a.a., diaria (desde 2003).

Por que isto entrou no dashboard. O painel dizia, na legenda do earnings
yield, que ele "e a forma comparavel a juros -- e a unica em que a pergunta
'caro em relacao a que?' tem resposta". E nao mostrava juro nenhum. A pergunta
ficava formulada e sem resposta, justamente no momento em que ela e a mais
informativa: em setembro de 2026 o Treasury de 10 anos fechou acima de 5% e o
TIPS de 10 anos leiloou a 2,65% real, a maior taxa desde 2008. Com o CAPE em
~40, o rendimento de lucro normalizado (1/CAPE ~ 2,5%) fica ABAIXO do juro
real sem risco. Isso nao aparecia em lugar nenhum do painel.

Mesma regra do resto do repositorio: o FRED marca observacao ausente com '.',
e ela e descartada, nunca preenchida.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone

import pandas as pd

from ..config import START_DATE
from .http import SourceUnavailable, get
from .prices import FRED_CSV, _BROWSER_HEADERS, _parse_fred_csv

log = logging.getLogger(__name__)

SERIES = {
    "ust10": "DGS10",
    "tips10": "DFII10",
}

# Faixa de plausibilidade, em % a.a. Fora dela nao e taxa de 10 anos: e coluna
# errada, unidade errada (fracao em vez de percentual) ou pagina de erro que
# passou pelo parser. O TIPS ja foi negativo (-1,2% em 2021), dai o piso.
FAIXA_PLAUSIVEL = (-3.0, 20.0)


# Reserva: o proprio Tesouro americano publica as curvas diarias, nominal e real,
# em CSV por ano. Na execucao de 26/09/2026 o FRED deu ReadTimeout tres vezes a
# partir do runner, e o estagio de juros inteiro ficou vazio.
TREASURY_CSV = ("https://home.treasury.gov/resource-center/data-chart-center/"
                "interest-rates/daily-treasury-rates.csv/{ano}/all?type={tipo}"
                "&field_tdr_date_value={ano}&page&_format=csv")
TREASURY_TIPO = {"ust10": "daily_treasury_yield_curve",
                 "tips10": "daily_treasury_real_yield_curve"}


def _parse_treasury_csv(texto: str) -> pd.Series:
    """Coluna de 10 anos ("10 Yr" na nominal, "10 YR" na real) do CSV do Tesouro."""
    df = pd.read_csv(io.StringIO(texto))
    col = next((c for c in df.columns if re.fullmatch(r"\s*10\s*yr?s?\s*", str(c), re.I)), None)
    if col is None or "Date" not in df.columns:
        raise SourceUnavailable(f"CSV do Tesouro sem coluna de 10 anos: {list(df.columns)[:8]}")
    idx = pd.to_datetime(df["Date"], format="%m/%d/%Y", errors="coerce")
    s = pd.Series(pd.to_numeric(df[col], errors="coerce").values, index=idx)
    s = s[~s.index.isna()].dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def _via_treasury(nome: str) -> pd.Series:
    ano_fim = datetime.now(timezone.utc).year
    partes, erros = [], []
    for ano in range(int(START_DATE[:4]), ano_fim + 1):
        try:
            raw = get(TREASURY_CSV.format(ano=ano, tipo=TREASURY_TIPO[nome]),
                      headers=_BROWSER_HEADERS, retries=2, timeout=40)
            partes.append(_parse_treasury_csv(raw.decode("utf-8", errors="replace")))
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{ano}: {str(exc)[:80]}")
    if not partes or partes[-1].empty:
        raise SourceUnavailable(f"Tesouro {nome}: sem o ano corrente. {' | '.join(erros[:3])}")
    s = pd.concat(partes).sort_index()
    s.attrs["fonte"] = "Tesouro dos EUA (home.treasury.gov)"
    if erros:
        s.attrs["anos_faltando"] = erros
    return s[~s.index.duplicated(keep="last")]


def _via_fred(nome: str) -> pd.Series:
    series_id = SERIES[nome]
    url = FRED_CSV.format(series=series_id) + f"&cosd={START_DATE}"
    raw = get(url, headers=_BROWSER_HEADERS, retries=2, timeout=30)
    s = _parse_fred_csv(raw.decode("utf-8", errors="replace"), series_id)
    s.attrs["fonte"] = f"FRED {series_id}"
    return s


def fetch_serie(nome: str) -> pd.Series:
    """Serie diaria em % a.a. Levanta SourceUnavailable se nada utilizavel vier.

    FRED primeiro; o CSV do Tesouro, que e a fonte primaria do proprio FRED para
    estas series, como reserva. O atributo `fonte` diz qual respondeu.
    """
    series_id = SERIES[nome]
    try:
        s = _via_fred(nome)
    except Exception as exc:  # noqa: BLE001
        log.warning("FRED %s indisponivel (%s); tentando o Tesouro", series_id, str(exc)[:120])
        s = _via_treasury(nome)
    if s.empty:
        raise SourceUnavailable(f"{series_id}: serie vazia")
    lo, hi = FAIXA_PLAUSIVEL
    fora = s[(s < lo) | (s > hi)]
    if len(fora) > 0.01 * len(s):
        raise SourceUnavailable(
            f"FRED {series_id}: {len(fora)} observacoes fora de [{lo}, {hi}] -- "
            f"unidade ou coluna errada, recusado")
    fonte = s.attrs.get("fonte", "")
    s = s[(s >= lo) & (s <= hi)]
    s.attrs["fonte"] = fonte
    log.info("%s: %d observacoes, %s a %s", fonte, len(s),
             s.index.min().date(), s.index.max().date())
    return s
