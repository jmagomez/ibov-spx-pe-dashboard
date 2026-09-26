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

import logging

import pandas as pd

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


def fetch_serie(nome: str) -> pd.Series:
    """Serie diaria em % a.a. Levanta SourceUnavailable se nada utilizavel vier."""
    series_id = SERIES[nome]
    raw = get(FRED_CSV.format(series=series_id), headers=_BROWSER_HEADERS)
    s = _parse_fred_csv(raw.decode("utf-8", errors="replace"), series_id)
    if s.empty:
        raise SourceUnavailable(f"FRED {series_id}: serie vazia")
    lo, hi = FAIXA_PLAUSIVEL
    fora = s[(s < lo) | (s > hi)]
    if len(fora) > 0.01 * len(s):
        raise SourceUnavailable(
            f"FRED {series_id}: {len(fora)} observacoes fora de [{lo}, {hi}] -- "
            f"unidade ou coluna errada, recusado")
    s = s[(s >= lo) & (s <= hi)]
    log.info("FRED %s: %d observacoes, %s a %s", series_id, len(s),
             s.index.min().date(), s.index.max().date())
    return s
