"""Lucro de 12 meses a partir do ITR: o 4T que faltava.

O ITR da CVM traz 1T, 2T e 3T. O 4T vem embutido no exercicio da DFP. Ate
09/2026 o pipeline somava as quatro ultimas LINHAS do ITR, e o resultado em
30/06/2026 era 2T25 + 3T25 + 1T26 + 2T26: pulava o 4T25 e ressuscitava um
trimestre de 15 meses atras. Quatro trimestres somados, nivel plausivel, erro
invisivel -- ate medir: lucro agregado 14% acima do correto em 30/06/2026, 30%
acima em 30/09/2025, e so a Vale com R$ 35 bi a mais, porque o prejuizo do
4T25 nao entrava.

Os casos abaixo usam numeros com a forma do caso real da Vale (1T-3T de 2025
positivos, 4T25 com prejuizo grande), em R$ bi.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import metrics

D = pd.Timestamp


def _vale() -> pd.DataFrame:
    linhas = [
        ("2024-03-31", "T", 8.33), ("2024-06-30", "T", 14.59), ("2024-09-30", "T", 13.27),
        ("2024-12-31", "A", 30.43),
        ("2025-03-31", "T", 8.17), ("2025-06-30", "T", 12.19), ("2025-09-30", "T", 14.67),
        ("2025-12-31", "A", 11.81),
        ("2026-03-31", "T", 10.20), ("2026-06-30", "T", 7.04),
    ]
    return pd.DataFrame({
        "cd_cvm": "4170",
        "data_fim": pd.to_datetime([x[0] for x in linhas]),
        "freq": [x[1] for x in linhas],
        "lucro": [x[2] for x in linhas],
    })


# ---------------------------------------------------------------------------
# ttm_from_quarterly: quatro trimestres CONSECUTIVOS, nao quatro linhas
# ---------------------------------------------------------------------------

def test_so_itr_sem_4t_nao_produz_numero_errado():
    """O caso de producao: sem o 4T, a janela tem buraco -- e buraco vira NaN,
    nao uma soma de trimestres nao consecutivos."""
    so_itr = _vale()
    so_itr = so_itr[so_itr["freq"] == "T"].set_index("data_fim")["lucro"]
    ltm = metrics.ttm_from_quarterly(so_itr)
    assert np.isnan(ltm.loc[D("2026-06-30")]), (
        "antes daqui saia 2T25+3T25+1T26+2T26 = 44,1 -- sem o 4T25 de -23,2")


def test_janela_consecutiva_com_datas_que_nao_sao_fim_exato_de_trimestre():
    """Serie trimestral da S&P DJI pode vir datada em dia util; o periodo e o
    que importa, nao o dia."""
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0],
                  index=pd.to_datetime(["2023-03-31", "2023-06-30", "2023-09-29",
                                        "2023-12-29", "2024-03-28"]))
    ltm = metrics.ttm_from_quarterly(s)
    assert ltm.iloc[3] == pytest.approx(10.0)
    assert ltm.iloc[4] == pytest.approx(14.0)
    assert list(ltm.index) == list(s.index), "o indice original e preservado"


def test_buraco_no_meio_contamina_as_quatro_janelas_que_o_incluiriam():
    idx = pd.date_range("2022-03-31", periods=9, freq="QE")
    s = pd.Series(1.0, index=idx).drop(idx[4])      # some o 1T23
    ltm = metrics.ttm_from_quarterly(s)
    assert ltm.loc[idx[3]] == pytest.approx(4.0)
    for d in idx[5:8]:
        assert np.isnan(ltm.loc[d]), f"{d.date()} dependeria do trimestre ausente"
    assert ltm.loc[idx[8]] == pytest.approx(4.0), "depois do buraco a janela volta"


# ---------------------------------------------------------------------------
# completar_quarto_trimestre
# ---------------------------------------------------------------------------

def test_4t_derivado_e_anual_menos_nove_meses():
    q = metrics.completar_quarto_trimestre(_vale())
    assert q.loc[D("2025-12-31")] == pytest.approx(11.81 - (8.17 + 12.19 + 14.67))
    assert q.loc[D("2025-12-31")] < -23, "o prejuizo do 4T25 aparece"


def test_ltm_no_4t_bate_com_o_exercicio_anual():
    """Identidade que serve de prova: 1T+2T+3T+4T derivado = exercicio."""
    ltm = metrics.ttm_from_quarterly(metrics.completar_quarto_trimestre(_vale()))
    assert ltm.loc[D("2025-12-31")] == pytest.approx(11.81)
    assert ltm.loc[D("2024-12-31")] == pytest.approx(30.43)


def test_ltm_corrigido_no_caso_da_vale():
    ltm = metrics.ttm_from_quarterly(metrics.completar_quarto_trimestre(_vale()))
    esperado = 14.67 + (11.81 - 35.03) + 10.20 + 7.04    # 3T25 + 4T25 + 1T26 + 2T26
    assert ltm.loc[D("2026-06-30")] == pytest.approx(esperado)
    assert ltm.loc[D("2026-06-30")] < 9, "e nao os 44,1 que o calculo antigo dava"


def test_sem_os_tres_trimestres_o_4t_nao_e_inventado():
    v = _vale()
    v = v[v["data_fim"] != D("2025-06-30")]
    q = metrics.completar_quarto_trimestre(v)
    assert D("2025-12-31") not in q.index


def test_exercicio_fora_de_dezembro_nao_entra_na_derivacao():
    """Sucroalcooleiras (Raizen, Sao Martinho) fecham o exercicio em marco: os
    'trimestres' delas nao sao os do calendario, e subtrair misturaria periodos."""
    g = pd.DataFrame({
        "cd_cvm": "1",
        "data_fim": pd.to_datetime(["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"]),
        "freq": ["T", "T", "T", "A"],
        "lucro": [1.0, 1.0, 1.0, 10.0],
    })
    q = metrics.completar_quarto_trimestre(g)
    assert D("2026-03-31") not in q.index


# ---------------------------------------------------------------------------
# lucro zero = formulario vazio
# ---------------------------------------------------------------------------

def test_zero_exato_e_descartado_e_nao_conta_como_cobertura():
    """TIM S.A. tem 1T24-3T24 e os exercicios 2024-2025 com lucro 0,00 no dado
    da CVM: DRE consolidada vazia. Somar como zero rebaixa o agregado e ainda
    marca a companhia como coberta."""
    g = pd.DataFrame({
        "cd_cvm": ["1", "1", "2"],
        "data_fim": pd.to_datetime(["2024-12-31"] * 3),
        "freq": ["A", "A", "A"],
        "lucro": [0.0, 0.0, 5.0],
    })
    g.loc[1, "data_fim"] = D("2023-12-31")
    dias = pd.date_range("2025-06-01", "2025-06-30", freq="B")
    total, cob, _ = metrics.soma_mista(g, dias, 0, 550, 200)
    assert total.iloc[-1] == pytest.approx(5.0)
    assert cob.iloc[-1] == 1, "a companhia do zero nao pode contar como coberta"


# ---------------------------------------------------------------------------
# soma_mista: cada companhia na melhor frequencia que tem
# ---------------------------------------------------------------------------

def test_companhia_com_buraco_no_itr_cai_para_o_anual_em_vez_de_sumir():
    """Antes, o agregado trimestral simplesmente nao tinha a companhia, e o
    anual dela -- que existia -- nao entrava no lugar."""
    completa = _vale()
    com_buraco = pd.DataFrame({
        "cd_cvm": "2",
        "data_fim": pd.to_datetime(["2024-12-31", "2025-12-31", "2026-03-31", "2026-06-30"]),
        "freq": ["A", "A", "T", "T"],
        "lucro": [2.4, 3.4, 0.6, 0.8],
    })
    dias = pd.date_range("2026-07-01", "2026-09-30", freq="B")
    total, cob, cob_tri = metrics.soma_mista(pd.concat([completa, com_buraco]), dias,
                                             0, 550, 200)
    ltm_vale = 14.67 + (11.81 - 35.03) + 10.20 + 7.04
    assert total.iloc[-1] == pytest.approx(ltm_vale + 3.4)
    assert cob.iloc[-1] == 2
    assert cob_tri.iloc[-1] == 1, "so a Vale entra por LTM trimestral"


def test_trecho_so_com_dfp_segue_igual_ao_anual():
    anual = pd.DataFrame({
        "cd_cvm": ["1", "1"],
        "data_fim": pd.to_datetime(["2012-12-31", "2013-12-31"]),
        "freq": ["A", "A"],
        "lucro": [10.0, 12.0],
    })
    dias = pd.date_range("2014-01-01", "2014-03-31", freq="B")
    total, cob, cob_tri = metrics.soma_mista(anual, dias, 0, 550, 200)
    assert total.iloc[-1] == pytest.approx(12.0)
    assert cob_tri.iloc[-1] == 0


def test_pesos_medem_cobertura_em_peso_do_indice():
    dias = pd.date_range("2026-07-01", "2026-07-31", freq="B")
    total, cob, cob_tri = metrics.soma_mista(_vale(), dias, 0, 550, 200,
                                             pesos={"4170": 3.5})
    assert cob.iloc[-1] == pytest.approx(3.5)
    assert cob_tri.iloc[-1] == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# Extracao do ITR: trimestre por regra, e nao por desempate de ordenacao
# ---------------------------------------------------------------------------

def test_itr_fica_com_a_linha_do_trimestre_e_nao_com_o_acumulado():
    from src.sources import cvm
    linhas = []
    for ordem in ("acumulado", "trimestre"):     # acumulado primeiro no arquivo
        ini = "2025-01-01" if ordem == "acumulado" else "2025-04-01"
        val = "300" if ordem == "acumulado" else "100"
        linhas.append({"CD_CONTA": "3.11", "VL_CONTA": val, "DT_INI_EXERC": ini,
                       "DT_FIM_EXERC": "2025-06-30", "CD_CVM": "1", "DENOM_CIA": "X",
                       "ORDEM_EXERC": "ÚLTIMO", "ESCALA_MOEDA": "MIL"})
    for ordem_arquivo in (linhas, linhas[::-1]):
        out = cvm._extract_profit(pd.DataFrame(ordem_arquivo), freq="T")
        assert len(out) == 1
        assert out["lucro"].iloc[0] == pytest.approx(100_000.0), (
            "a linha do trimestre vence qualquer que seja a ordem no arquivo")


def test_extracao_descarta_lucro_zero():
    from src.sources import cvm
    df = pd.DataFrame([{"CD_CONTA": "3.11", "VL_CONTA": "0", "DT_FIM_EXERC": "2025-12-31",
                        "CD_CVM": "1", "DENOM_CIA": "X", "ORDEM_EXERC": "ÚLTIMO"},
                       {"CD_CONTA": "3.11", "VL_CONTA": "5", "DT_FIM_EXERC": "2025-12-31",
                        "CD_CVM": "2", "DENOM_CIA": "Y", "ORDEM_EXERC": "ÚLTIMO"}])
    out = cvm._extract_profit(df, freq="A")
    assert list(out["cd_cvm"]) == ["2"]
