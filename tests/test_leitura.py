"""Leitura dos numeros: crescimento do lucro, historia longa e juros.

Nenhuma destas funcoes muda o P/E. Elas existem para responder a pergunta que
o P/E sozinho nao responde -- "isto e caro?" -- em tres eixos que o dashboard
nao mostrava: o lucro do denominador subiu por que?, caro contra que
historia?, e caro contra que juro?
"""
from __future__ import annotations

from unittest import mock

import numpy as np
import pandas as pd
import pytest

from src import metrics
from src.sources import juros, shiller
from src.sources.http import SourceUnavailable


# ---------------------------------------------------------------------------
# variacao_anual
# ---------------------------------------------------------------------------

def test_variacao_anual_em_serie_mensal():
    idx = pd.date_range("2024-01-01", periods=25, freq="MS")
    s = pd.Series(np.linspace(100.0, 148.0, 25), index=idx)
    v = metrics.variacao_anual(s)
    assert np.isnan(v.iloc[11]), "antes de 12 meses de historia nao ha base"
    assert v.iloc[24] == pytest.approx((148.0 / 124.0 - 1) * 100)


def test_variacao_anual_em_serie_trimestral():
    idx = pd.date_range("2024-03-31", periods=5, freq="QE")
    s = pd.Series([200.0, 205.0, 210.0, 215.0, 260.0], index=idx)
    assert metrics.variacao_anual(s).iloc[4] == pytest.approx(30.0)


def test_variacao_anual_com_base_negativa_nao_vira_numero():
    """Crescimento sobre lucro negativo nao tem leitura; NaN, nao -300%."""
    idx = pd.date_range("2020-03-31", periods=5, freq="QE")
    s = pd.Series([-10.0, 1.0, 2.0, 3.0, 20.0], index=idx)
    assert np.isnan(metrics.variacao_anual(s).iloc[4])


# ---------------------------------------------------------------------------
# resumo_historico
# ---------------------------------------------------------------------------

def test_percentil_contra_a_historia_inteira():
    h = pd.Series(np.arange(1.0, 101.0), index=pd.date_range("1900-01-01", periods=100, freq="YS"))
    r = metrics.resumo_historico(h, 96.5)
    assert r["percentil"] == pytest.approx(96.0)
    assert r["acima_do_atual"] == 4
    assert r["maximo"] == 100.0 and r["data_maximo"].startswith("1999")
    assert r["mediana"] == pytest.approx(50.5)


def test_janela_curta_e_historia_longa_contam_historias_diferentes():
    """O ponto da funcao, no formato do caso real: uma decada cara dentro de um
    seculo barato. O mesmo valor e mediano na decada e extremo no seculo."""
    seculo = pd.Series(15.0 + np.random.default_rng(0).normal(0, 3, 1200),
                       index=pd.date_range("1900-01-01", periods=1200, freq="MS"))
    decada = pd.Series(24.0 + np.random.default_rng(1).normal(0, 3, 120),
                       index=pd.date_range("2016-01-01", periods=120, freq="MS"))
    tudo = pd.concat([seculo, decada])
    atual = 26.0
    assert metrics.resumo_historico(decada, atual)["percentil"] < 90
    assert metrics.resumo_historico(tudo, atual)["percentil"] > 95


def test_historico_vazio_devolve_dicionario_vazio_e_nao_zero():
    assert metrics.resumo_historico(pd.Series(dtype=float), 20.0) == {}
    assert metrics.resumo_historico(pd.Series([1.0, 2.0]), float("nan")) == {}


# ---------------------------------------------------------------------------
# premio_sobre_juro
# ---------------------------------------------------------------------------

def test_premio_negativo_quando_o_lucro_normalizado_rende_menos_que_o_tips():
    """Setembro de 2026, em numeros redondos: CAPE 40,6 -> 2,46%; TIPS 2,65%."""
    dias = pd.date_range("2026-09-21", periods=3, freq="B")
    cape_yield = pd.Series(100.0 / 40.58, index=dias)
    tips = pd.Series(2.65, index=dias)
    p = metrics.premio_sobre_juro(cape_yield, tips)
    assert (p < 0).all()
    assert p.iloc[0] == pytest.approx(2.464 - 2.65, abs=1e-3)


def test_premio_sem_juro_na_data_fica_nan_e_nao_igual_ao_rendimento():
    dias = pd.date_range("2026-09-21", periods=3, freq="B")
    ey = pd.Series(3.8, index=dias)
    tips = pd.Series([2.6, np.nan, 2.7], index=dias)
    p = metrics.premio_sobre_juro(ey, tips)
    assert np.isnan(p.iloc[1])


# ---------------------------------------------------------------------------
# juros (FRED)
# ---------------------------------------------------------------------------

CSV_FRED = b"observation_date,DFII10\n2026-09-23,2.62\n2026-09-24,.\n2026-09-25,2.68\n"


def test_fred_descarta_ausente_em_vez_de_preencher():
    with mock.patch.object(juros, "get", return_value=CSV_FRED):
        s = juros.fetch_serie("tips10")
    assert list(s.values) == [2.62, 2.68]


def test_fred_recusa_serie_em_unidade_errada():
    """Taxa em fracao (0,0262) ou pagina de erro com numero grande: nao e juro
    de 10 anos em % a.a., e o estagio falha em vez de publicar."""
    ruim = b"observation_date,DFII10\n" + b"".join(
        f"2026-01-{d:02d},{262 + d}\n".encode() for d in range(1, 28))
    with mock.patch.object(juros, "get", return_value=ruim):
        with pytest.raises(SourceUnavailable):
            juros.fetch_serie("tips10")


# ---------------------------------------------------------------------------
# shiller: a historia longa deixa de ser cortada em 2010
# ---------------------------------------------------------------------------

def _planilha_desde_1871() -> pd.DataFrame:
    meses = pd.date_range("1871-01-01", "2026-06-01", freq="MS")
    n = len(meses)
    df = pd.DataFrame({
        0: ["Date"] + [round(d.year + d.month / 100, 2) for d in meses],
        1: ["P"] + list(np.linspace(4.0, 7000.0, n)),
        2: ["D"] + [0.2] * n,
        3: ["E"] + list(np.linspace(0.4, 290.0, n)),
        4: ["CAPE"] + [20.0] * n,
    })
    df.attrs["header_row"] = 0
    return df


def test_historico_preserva_o_seculo_xix_e_tabela_continua_em_2010():
    with mock.patch.object(shiller, "_abrir_tabela", return_value=_planilha_desde_1871()):
        hist = shiller.fetch_historico()
        rec = shiller.fetch_tabela()
    assert hist.index.min().year == 1871
    assert rec.index.min().year == 2010
    assert hist.index.max() == rec.index.max()


# ---------------------------------------------------------------------------
# reparar_validade: o aviso so aparece quando o reparo mexeu em algo
# ---------------------------------------------------------------------------

def test_reparo_sem_efeito_nao_publica_aviso(tmp_path):
    """Ate 26/09/2026 o aviso do reparo de 08/08 era anexado em TODA execucao e
    aparecia todo dia no resumo por e-mail, descrevendo como atual um reparo
    que nao estava acontecendo."""
    import importlib.util
    import json
    import pathlib
    spec = importlib.util.spec_from_file_location(
        "reparar", pathlib.Path(__file__).resolve().parents[1] / "tools" / "reparar_validade.py")
    rep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rep)

    dias = pd.bdate_range("2026-06-01", "2026-09-25")
    eps = pd.Series(295.0, index=dias)
    eps.loc["2026-06-01":"2026-06-05"] = 290.0          # ultima mudanca em junho
    d = pd.DataFrame({"preco": 7700.0, "eps_ttm": eps, "cape": 40.0}, index=dias)
    d.to_csv(tmp_path / "spx.csv", index_label="data")
    (tmp_path / "status.json").write_text(json.dumps({"avisos": []}), encoding="utf-8")
    with mock.patch.object(rep, "PROCESSED", tmp_path):
        rep.main()
    st = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert st["avisos"] == [], "nada foi removido; nao ha o que avisar"


def test_sem_fred_o_tesouro_responde_e_a_fonte_fica_registrada():
    """26/09/2026: o FRED deu ReadTimeout tres vezes no runner e o estagio de
    juros ficou vazio. O Tesouro publica a mesma curva, e e a fonte do FRED."""
    csv_tesouro = (b'Date,"5 YR","7 YR","10 YR","20 YR","30 YR"\n'
                   b"09/25/2026,2.21,2.40,2.65,2.90,3.01\n")

    def falso_get(url, **kw):
        if "fred" in url:
            raise SourceUnavailable("ReadTimeout")
        return csv_tesouro

    with mock.patch.object(juros, "get", side_effect=falso_get):
        s = juros.fetch_serie("tips10")
    assert s.iloc[-1] == pytest.approx(2.65)
    assert "Tesouro" in s.attrs["fonte"]
