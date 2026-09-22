"""Testes do resumo diario.

O que estes testes protegem nao e formatacao, e sim duas afirmacoes que o
e-mail faz e que podem ficar falsas sem ninguem notar:

  1. "este e o numero de hoje" -- um valor sem lastro recente nao pode aparecer
     como se fosse do dia, e muito menos na linha de assunto;
  2. "isto mudou desde ontem" -- a secao de mudancas so vale se ela de fato
     comparar com a execucao anterior, e nao repetir o estado corrente.

Ambas passaram perto de ser quebradas na propria construcao: a primeira versao
do assunto trazia um P/E de dois anos atras com cara de cotacao do dia.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pandas as pd
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "digest", pathlib.Path(__file__).resolve().parents[1] / "tools" / "digest.py")
digest = importlib.util.module_from_spec(_SPEC)
sys.modules["digest"] = digest
_SPEC.loader.exec_module(digest)


def _serie(valores, fim="2026-09-18", freq="B"):
    idx = pd.bdate_range(end=fim, periods=len(valores)) if freq == "B" else \
        pd.date_range(end=fim, periods=len(valores), freq=freq)
    return pd.DataFrame({"pe": valores}, index=idx).rename_axis("data")


# ---------------------------------------------------------------------------
# Idade do valor
# ---------------------------------------------------------------------------

def test_valor_do_dia_nao_e_marcado_como_vencido():
    df = _serie([20.0, 21.0])
    m = digest.ultimo(df, "pe", df.index.max())
    assert m["vencido"] is False
    assert m["idade_dias"] == 0
    assert m["delta"] == pytest.approx(1.0)
    assert m["delta_pct"] == pytest.approx(5.0)


def test_valor_parado_ha_dois_anos_e_marcado_como_vencido():
    """Era exatamente este o caso em producao: o cartao 'Situacao atual' exibia
    o P/E de 27/09/2024 porque foi o ultimo com lastro. O numero estava certo;
    a afirmacao de que ele era a situacao atual e que nao estava."""
    df = _serie([29.2, 29.16], fim="2024-09-27")
    referencia = pd.Timestamp("2026-09-18")
    m = digest.ultimo(df, "pe", referencia)
    assert m["vencido"] is True
    assert m["idade_dias"] > 700


def test_serie_inexistente_devolve_none_em_vez_de_zero():
    assert digest.ultimo(pd.DataFrame(), "pe", None) is None
    assert digest.ultimo(_serie([1.0]), "inexistente", None) is None


# ---------------------------------------------------------------------------
# Assunto
# ---------------------------------------------------------------------------

def _dados(spx_vencido: bool):
    m_ok = {"valor": 88.2, "data": "18/09/2026", "data_iso": "2026-09-18",
            "delta": -0.36, "delta_pct": -0.41, "idade_dias": 0, "vencido": False}
    m_spx = dict(m_ok, valor=29.16, data="27/09/2024", data_iso="2024-09-27",
                 idade_dias=721, vencido=spx_vencido)
    return {
        "referencia": "18/09/2026", "referencia_iso": "2026-09-18",
        "metricas": {
            "spx_pe": ("S&P 500 - P/E trailing 12m", "", m_spx),
            "spx_cape": ("S&P 500 - CAPE", "", None),
            "spx_ey": ("S&P 500 - earnings yield", "%", None),
            "spx_pct": ("S&P 500 - percentil", "", None),
            "ibov_val": ("Ibovespa - indice de valuation", "", m_ok),
            "ibov_pct": ("Ibovespa - percentil", "", m_ok),
        },
        "estagios": {"precos_spx": True, "eps_spx": True},
        "vencidas": ["eps_spx"] if spx_vencido else [],
        "avisos": [], "gerado_em_utc": "2026-09-20T12:00:00+00:00",
    }


def test_assunto_nao_publica_numero_vencido_como_se_fosse_do_dia():
    a = digest.assunto(_dados(spx_vencido=True), [])
    assert "29,16" not in a, "numero de 2024 nao pode aparecer no assunto de hoje"
    assert "sem lastro" in a


def test_assunto_traz_o_numero_quando_ele_tem_lastro():
    a = digest.assunto(_dados(spx_vencido=False), [])
    assert "29,16" in a


def test_assunto_marca_quando_houve_mudanca():
    assert digest.assunto(_dados(False), ["algo mudou"]).startswith("[!]")
    assert not digest.assunto(_dados(False), []).startswith("[!]")


# ---------------------------------------------------------------------------
# Mudancas
# ---------------------------------------------------------------------------

def _estado(**kw):
    base = {"referencia_iso": "2026-09-18",
            "estagios": {"precos_spx": True, "eps_spx": True},
            "vencidas": [], "faixa_spx": "intermediaria",
            "faixa_ibov": "intermediaria", "series_vazias": []}
    base.update(kw)
    return base


def test_dia_sem_novidade_nao_gera_linha_de_mudanca():
    assert digest.mudancas(_estado(), _estado()) == []


def test_estagio_que_quebrou_aparece():
    novo = _estado(estagios={"precos_spx": True, "eps_spx": False})
    m = digest.mudancas(novo, _estado())
    assert any("eps_spx" in x and "FALHAR" in x for x in m)


def test_estagio_que_voltou_aparece():
    anterior = _estado(estagios={"precos_spx": True, "eps_spx": False})
    m = digest.mudancas(_estado(), anterior)
    assert any("eps_spx" in x and "FUNCIONAR" in x for x in m)


def test_fonte_que_venceu_hoje_aparece_e_nao_se_repete_amanha():
    hoje = _estado(vencidas=["cape_shiller"])
    assert any("VENCEU" in x for x in digest.mudancas(hoje, _estado()))
    # Amanha, com o mesmo estado, o aviso nao volta: ele ja foi dado. E isso
    # que impede o e-mail de virar ruido diario repetindo o mesmo problema.
    assert digest.mudancas(hoje, hoje) == []


def test_cruzamento_de_faixa_de_percentil_aparece():
    m = digest.mudancas(_estado(faixa_spx="alta"), _estado())
    assert any("S&P 500" in x and "percentil" in x for x in m)
    assert any("nao sinal de compra ou venda" in x for x in m)


def test_primeira_execucao_nao_inventa_mudancas():
    assert digest.mudancas(_estado(), None) == []


# ---------------------------------------------------------------------------
# Renderizacao
# ---------------------------------------------------------------------------

def test_html_e_texto_marcam_o_valor_vencido():
    d = _dados(spx_vencido=True)
    h, t = digest.html(d, []), digest.texto(d, [])
    assert "sem atualizacao ha 721 dias" in h
    assert "sem atualizacao ha 721 dias" in t
    assert digest.DASHBOARD_URL in h and digest.DASHBOARD_URL in t


def test_texto_declara_a_serie_indisponivel_em_vez_de_omitir():
    """Omitir a linha faria a metrica ausente parecer inexistente. Ela existe;
    o que nao existe e o dado de hoje, e e isso que precisa estar escrito."""
    t = digest.texto(_dados(spx_vencido=True), [])
    assert "CAPE: indisponivel" in t


def test_numero_sai_no_formato_brasileiro():
    assert digest._num(1234.5) == "1.234,50"
    assert digest._num(-0.41) == "-0,41"
