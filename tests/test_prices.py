"""Testes dos parsers de preco.

Os payloads sao SINTETICOS: reproduzem apenas a ESTRUTURA documentada das
respostas. Nenhum valor daqui representa mercado nem chega ao dashboard.
"""
from __future__ import annotations

import pandas as pd
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
    assert s.index.tz is None, "indice naive, para casar com as demais series"


def test_parser_yahoo_falha_sem_result():
    with pytest.raises(SourceUnavailable):
        prices._parse_yahoo_payload({"chart": {"result": [], "error": None}}, "T")


def test_parser_yahoo_propaga_erro_da_fonte():
    with pytest.raises(SourceUnavailable):
        prices._parse_yahoo_payload({"chart": {"error": {"code": "Not Found"}}}, "T")


def test_parser_yahoo_sem_close():
    with pytest.raises(SourceUnavailable):
        prices._parse_yahoo_payload(
            {"chart": {"error": None, "result": [{"timestamp": [1], "indicators": {}}]}}, "T")


def test_parser_fred_descarta_ponto():
    csv = "observation_date,SP500\n2020-01-02,3257.85\n2020-01-03,.\n2020-01-06,3246.28\n"
    s = prices._parse_fred_csv(csv, "SP500")
    assert len(s) == 2, "'.' do FRED e ausencia, nao zero"
    assert s.iloc[-1] == pytest.approx(3246.28)


def test_parser_fred_aceita_cabecalho_antigo():
    csv = "DATE,SP500\n2020-01-02,3257.85\n"
    assert len(prices._parse_fred_csv(csv, "SP500")) == 1


def test_parser_fred_csv_invalido():
    with pytest.raises(SourceUnavailable):
        prices._parse_fred_csv("apenas_uma_coluna\n1\n", "SP500")


def test_limpar_remove_duplicata_e_ordena():
    idx = pd.DatetimeIndex(["2020-01-02", "2020-01-01", "2020-01-02"])
    s = prices._limpar(pd.Series([1.0, 2.0, 9.0], index=idx))
    assert s.tolist() == [2.0, 9.0], "mantem a ultima duplicata e ordena"


def test_fred_nao_serve_ibov():
    with pytest.raises(SourceUnavailable):
        prices._via_fred("ibov")


def test_indice_desconhecido():
    with pytest.raises(ValueError):
        prices.fetch_index_close("nasdaq")
