"""Testes das funcoes de calculo.

Os dados usados aqui sao SINTETICOS e existem para verificar aritmetica, nao
para produzir analise. Nenhum numero destes testes chega ao dashboard.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import metrics


def q_index(n: int, start: str = "2020-03-31") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="QE")


def test_ttm_soma_quatro_trimestres():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=q_index(5))
    ttm = metrics.ttm_from_quarterly(s)
    assert np.isnan(ttm.iloc[2])
    assert ttm.iloc[3] == pytest.approx(10.0)
    assert ttm.iloc[4] == pytest.approx(14.0)


def test_ttm_nao_preenche_trimestre_faltante():
    s = pd.Series([1.0, np.nan, 3.0, 4.0, 5.0], index=q_index(5))
    ttm = metrics.ttm_from_quarterly(s)
    assert np.isnan(ttm.iloc[3]), "trimestre ausente nao pode virar numero"


def test_ttm_exige_datetimeindex():
    with pytest.raises(TypeError):
        metrics.ttm_from_quarterly(pd.Series([1, 2, 3]))


def test_step_to_daily_sem_extrapolacao_para_tras():
    step = pd.Series([10.0], index=pd.DatetimeIndex(["2020-06-30"]))
    dias = pd.date_range("2020-06-25", "2020-07-05", freq="D")
    out = metrics.step_to_daily(step, dias, lag_days=0)
    assert out.loc["2020-06-29"] != out.loc["2020-06-29"]  # NaN
    assert out.loc["2020-06-30"] == pytest.approx(10.0)
    assert out.loc["2020-07-05"] == pytest.approx(10.0)


def test_step_to_daily_aplica_defasagem():
    step = pd.Series([10.0], index=pd.DatetimeIndex(["2020-06-30"]))
    dias = pd.date_range("2020-06-25", "2020-09-30", freq="D")
    sem = metrics.step_to_daily(step, dias, lag_days=0)
    com = metrics.step_to_daily(step, dias, lag_days=75)
    assert sem.loc["2020-07-01"] == pytest.approx(10.0)
    assert np.isnan(com.loc["2020-07-01"]), "com defasagem o lucro ainda nao era conhecido"
    assert com.loc["2020-09-30"] == pytest.approx(10.0)


def test_step_to_daily_serie_vazia():
    out = metrics.step_to_daily(pd.Series(dtype=float),
                               pd.date_range("2020-01-01", periods=3, freq="D"))
    assert out.isna().all()


def test_pe_ratio_basico():
    dias = pd.date_range("2020-01-01", periods=3, freq="D")
    pe = metrics.pe_ratio(pd.Series([100.0, 110.0, 90.0], index=dias),
                          pd.Series([5.0, 5.0, 5.0], index=dias))
    assert pe.tolist() == pytest.approx([20.0, 22.0, 18.0])


def test_pe_ratio_suprime_lucro_nao_positivo():
    dias = pd.date_range("2020-01-01", periods=3, freq="D")
    pe = metrics.pe_ratio(pd.Series([100.0, 100.0, 100.0], index=dias),
                          pd.Series([5.0, 0.0, -2.0], index=dias))
    assert pe.iloc[0] == pytest.approx(20.0)
    assert np.isnan(pe.iloc[1]) and np.isnan(pe.iloc[2])


def test_earnings_yield_inverso():
    ey = metrics.earnings_yield(pd.Series([20.0, 25.0]))
    assert ey.tolist() == pytest.approx([5.0, 4.0])


def test_relative_pe():
    dias = pd.date_range("2020-01-01", periods=2, freq="D")
    r = metrics.relative_pe(pd.Series([10.0, 12.0], index=dias),
                            pd.Series([20.0, 24.0], index=dias))
    assert r.tolist() == pytest.approx([0.5, 0.5])


def test_zscore_media_zero_em_serie_constante():
    s = pd.Series([5.0] * 40, index=pd.date_range("2020-01-01", periods=40, freq="D"))
    z = metrics.rolling_zscore(s, 20)
    assert z.dropna().empty or np.isnan(z.iloc[-1])


def test_percentil_extremos():
    s = pd.Series(list(range(1, 41)), dtype=float,
                  index=pd.date_range("2020-01-01", periods=40, freq="D"))
    p = metrics.rolling_percentile(s, 20)
    assert p.iloc[-1] == pytest.approx(100.0), "serie crescente termina no topo"


def test_drawdown_do_multiplo():
    s = pd.Series([10.0, 20.0, 15.0])
    dd = metrics.drawdown_of_multiple(s)
    assert dd.tolist() == pytest.approx([0.0, 0.0, -25.0])


def test_decomposicao_e_aditiva_em_log():
    dias = pd.date_range("2020-01-01", periods=5, freq="D")
    p = pd.Series([100.0, 110.0, 121.0, 133.1, 146.41], index=dias)
    e = pd.Series([5.0, 5.0, 6.0, 6.0, 7.0], index=dias)
    d = metrics.decompose_price_change(p, e, periods=2).dropna()
    resid = d["preco_ln"] - (d["lucro_ln"] + d["multiplo_ln"])
    assert resid.abs().max() < 1e-12, "identidade P = (P/E) x E deve fechar exatamente"
