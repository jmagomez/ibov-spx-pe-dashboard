"""Testes da conciliacao B3 <-> CVM por CNPJ.

O caso central e o do CNPJ que muda. Uma companhia que trocou de inscricao em
2018 aparece na CVM com um numero ate 2017 e outro a partir de 2018. Se a
conciliacao se apoiar no CNPJ vigente, o lucro anterior a troca some -- e some
em silencio, que e o modo mais perigoso de perder dado: a serie continua sendo
desenhada, so que mais curta, e nada na tela diz por que.
"""
from __future__ import annotations

import pandas as pd

from src.reconcile import (conciliar, mapa_cnpj_cdcvm, normalizar_cnpj,
                           raiz_ticker)


def test_normalizar_cnpj():
    assert normalizar_cnpj("33.000.167/0001-01") == "33000167000101"
    assert normalizar_cnpj("33000167000101") == "33000167000101"
    assert normalizar_cnpj("167000101") == "00000167000101", "zeros a esquerda"
    assert normalizar_cnpj("") == ""
    assert normalizar_cnpj(None) == ""
    assert normalizar_cnpj("00000000000000") == ""
    assert normalizar_cnpj("1" * 20) == "", "numero longo demais nao e CNPJ"


def test_raiz_ticker():
    assert raiz_ticker("VALE3") == "VALE"
    assert raiz_ticker("PETR4") == "PETR"
    assert raiz_ticker("ITUB4") == "ITUB"
    assert raiz_ticker("") == ""


def _lucros_com_troca_de_cnpj() -> pd.DataFrame:
    """Companhia 111 troca de CNPJ em 2018; companhia 222 nunca troca."""
    return pd.DataFrame({
        "cnpj": ["11.111.111/0001-11"] * 2 + ["99.999.999/0001-99"] * 2
                + ["22.222.222/0001-22"] * 3,
        "cd_cvm": ["111"] * 4 + ["222"] * 3,
        "empresa": ["ALFA S.A."] * 4 + ["BETA HOLDING S.A."] * 3,
        "data_fim": pd.to_datetime(["2016-12-31", "2017-12-31", "2018-12-31",
                                    "2019-12-31", "2017-12-31", "2018-12-31",
                                    "2019-12-31"]),
        "lucro": [10.0, 11.0, 12.0, 13.0, 5.0, 6.0, 7.0],
        "freq": ["A"] * 7,
    })


def test_cnpj_antigo_continua_resolvendo_apos_a_troca():
    mapa, trocas, ambiguos = mapa_cnpj_cdcvm(_lucros_com_troca_de_cnpj())
    assert mapa["11111111000111"] == "111", "o CNPJ anterior a troca tem de resolver"
    assert mapa["99999999000199"] == "111", "e o posterior tambem, para a mesma companhia"
    assert not ambiguos
    assert len(trocas) == 1
    t = trocas[0]
    assert t["cd_cvm"] == "111"
    assert t["cnpjs"]["11111111000111"] == "2016-12-31..2017-12-31"
    assert t["cnpjs"]["99999999000199"] == "2018-12-31..2019-12-31"


def test_cnpj_ambiguo_e_recusado_e_nao_desempatado():
    """Um CNPJ para dois CD_CVM nao tem resposta certa. Melhor nenhuma."""
    df = pd.DataFrame({
        "cnpj": ["33.333.333/0001-33"] * 2,
        "cd_cvm": ["333", "444"],
        "empresa": ["GAMA S.A.", "DELTA S.A."],
        "data_fim": pd.to_datetime(["2020-12-31", "2020-12-31"]),
    })
    mapa, _, ambiguos = mapa_cnpj_cdcvm(df)
    assert "33333333000133" not in mapa
    assert ambiguos and ambiguos[0]["cd_cvm"] == ["333", "444"]


def test_conciliacao_por_cnpj_cobre_o_que_o_nome_nao_cobre():
    """A B3 diz "ALFA"; a CVM diz "ALFA S.A.". O CNPJ nao depende dessa grafia."""
    lucros = _lucros_com_troca_de_cnpj()
    composicao = pd.DataFrame({
        "codigo": ["ALFA3", "BETA4", "ZETA9"],
        "empresa": ["ALFA", "BETA", "ZETA"],
        "participacao_pct": [50.0, 30.0, 20.0],
    })
    empresas = pd.DataFrame({
        "raiz": ["ALFA", "BETA"],
        "cnpj": ["99.999.999/0001-99", "22.222.222/0001-22"],
    })
    casadas, cobertura, rel = conciliar(composicao, empresas, lucros)
    assert rel["por_cnpj"] == 2
    assert set(casadas["cd_cvm"]) == {"111", "222"}
    assert cobertura == 0.8, "80 dos 100 pontos de peso conciliados"
    assert rel["sem_correspondencia"] == [{"codigo": "ZETA9", "peso": 20.0}]
    assert len(rel["trocas_de_cnpj"]) == 1


def test_cobertura_e_por_peso_e_nao_por_contagem():
    """Tres ativos minusculos nao substituem um que vale metade do indice."""
    lucros = pd.DataFrame({
        "cnpj": ["22.222.222/0001-22"] * 3,
        "cd_cvm": ["222"] * 3,
        "empresa": ["BETA S.A."] * 3,
        "data_fim": pd.to_datetime(["2018-12-31", "2019-12-31", "2020-12-31"]),
    })
    composicao = pd.DataFrame({
        "codigo": ["PESA3", "BETA4", "BETB4", "BETC4"],
        "empresa": ["PESADA", "BETA", "BETA B", "BETA C"],
        "participacao_pct": [50.0, 20.0, 20.0, 10.0],
    })
    empresas = pd.DataFrame({"raiz": ["BETA", "BETB", "BETC"],
                             "cnpj": ["22.222.222/0001-22"] * 3})
    _, cobertura, rel = conciliar(composicao, empresas, lucros)
    assert rel["por_cnpj"] == 3
    assert cobertura == 0.5, "3 de 4 ativos, mas so metade do peso"


def test_nome_so_entra_no_que_o_cnpj_nao_resolveu():
    lucros = _lucros_com_troca_de_cnpj()
    composicao = pd.DataFrame({
        "codigo": ["ALFA3", "BETA4"],
        "empresa": ["ALFA S.A.", "BETA HOLDING S.A."],
        "participacao_pct": [60.0, 40.0],
    })
    empresas = pd.DataFrame({"raiz": ["ALFA"], "cnpj": ["11.111.111/0001-11"]})
    _, cobertura, rel = conciliar(composicao, empresas, lucros)
    assert rel["por_cnpj"] == 1 and rel["por_nome"] == 1
    assert cobertura == 1.0


def test_sem_cadastro_da_b3_a_conciliacao_nao_quebra():
    """Se o cadastro de listadas nao vier, cai para nome -- degradado, nao quebrado."""
    lucros = _lucros_com_troca_de_cnpj()
    composicao = pd.DataFrame({"codigo": ["ALFA3"], "empresa": ["ALFA S.A."],
                               "participacao_pct": [100.0]})
    _, cobertura, rel = conciliar(composicao, pd.DataFrame(), lucros)
    assert rel["por_cnpj"] == 0 and rel["por_nome"] == 1
    assert cobertura == 1.0
