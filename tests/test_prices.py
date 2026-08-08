"""Testes do parser do provedor de precos.

O payload usado aqui e SINTETICO: reproduz apenas a ESTRUTURA documentada da
resposta do endpoint chart do Yahoo. Os valores nao representam mercado e nao
chegam ao dashboard.
"""
from __future__ import annotations

import pytest

from src.sources import prices
from src.sources.http import SourceUnavailable


def test_parser_yahoo_extrai_serie():
    payload = {"chart": {"error": None, "result": [{
        "timestamp": [1262563200, 1262649600, 1262736000],
        "indicators": {"quote": [{"close": [1.0, None, 3.0]}]},
    }]}}
    s = prices._parse_yahoo_payload(payload, "TESTE")
    assert len(s) == 2, "fechamento nulo deve ser descartado, nao preenchido"
    assert s.iloc[0] == pytest.approx(1.0)
    assert s.iloc[-1] == pytest.approx(3.0)
    assert s.index.tz is None, "indice deve ser naive para casar com as demais series"


def test_parser_yahoo_falha_explicita_sem_result():
    with pytest.raises(SourceUnavailable):
        prices._parse_yahoo_payload({"chart": {"result": [], "error": None}}, "TESTE")


def test_parser_yahoo_propaga_erro_da_fonte():
    with pytest.raises(SourceUnavailable):
        prices._parse_yahoo_payload({"chart": {"error": {"code": "Not Found"}}}, "TESTE")


def test_parser_yahoo_sem_close():
    with pytest.raises(SourceUnavailable):
        prices._parse_yahoo_payload(
            {"chart": {"error": None, "result": [{"timestamp": [1], "indicators": {}}]}},
            "TESTE")


def test_indice_desconhecido():
    with pytest.raises(ValueError):
        prices.fetch_index_close("nasdaq")
