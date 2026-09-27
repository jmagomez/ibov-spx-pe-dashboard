"""P/L do Ibovespa em nivel.

Os numeros das fixtures sao os do dado real de 26/09/2026 (carteira da B3 de
28/09/2026 e composicao do capital do ITR de 30/06/2026), para que os testes
travem exatamente as armadilhas que o dado real tem: acoes em milhares num
arquivo que nao informa escala, units, e subconta da controladora zerada.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import ibov_nivel as nv
from src.sources import b3, cvm


# ---------------------------------------------------------------------------
# escala do numero de acoes e fracao da companhia no indice
# ---------------------------------------------------------------------------

def test_petrobras_em_unidades():
    f, esc = nv.fracao_na_carteira(2_441_951_100 + 4_410_957_710, 12_888_732_761)
    assert esc == 1.0 and f == pytest.approx(0.5317, abs=1e-3)


def test_itau_em_milhares_e_detectado_pela_quantidade_teorica():
    """O Itau informa 5.617.743 ON e 5.409.126 PN: sao milhares."""
    n = 5_617_743 + 5_409_126 - 4_997
    f, esc = nv.fracao_na_carteira(5_337_898_685, n)
    assert esc == 1_000.0 and f == pytest.approx(0.4843, abs=1e-3)


def test_santander_com_free_float_baixo_continua_plausivel():
    q = 356_245_448 * nv.acoes_por_papel("SANB11")
    f, esc = nv.fracao_na_carteira(q, 3_818_695 + 3_679_836 - 11_004)
    assert esc == 1_000.0 and 0.05 < f < 0.15


def test_numero_de_acoes_absurdo_nao_vira_fracao():
    assert np.isnan(nv.fracao_na_carteira(1e9, 10.0)[0])
    assert np.isnan(nv.fracao_na_carteira(1e6, 1e12)[0])


def test_units_contam_as_acoes_que_representam():
    assert nv.acoes_por_papel("BPAC11") == 3
    assert nv.acoes_por_papel("KLBN11") == 5
    assert nv.acoes_por_papel("PETR4") == 1
    assert nv.acoes_por_papel("XPTO11") is None, "unit desconhecida nao e presumida"


# ---------------------------------------------------------------------------
# carteira e P/L
# ---------------------------------------------------------------------------

def _acoes():
    return pd.DataFrame({
        "cnpj": ["33.000.167/0001-01", "60.872.504/0001-23", "60.872.504/0001-23"],
        "data_ref": pd.to_datetime(["2026-06-30", "2025-12-31", "2026-06-30"]),
        "versao": [1, 2, 1],
        "on": [7_442_231_382, 5_617_743, 5_617_743],
        "pn": [5_446_501_379, 5_409_126, 5_409_126],
        "tes_on": [0, 0, 0], "tes_pn": [0, 345, 4_997],
    })


def _casadas():
    return pd.DataFrame({
        "codigo": ["PETR3", "PETR4", "ITUB4"],
        "cd_cvm": ["9512", "9512", "19348"],
        "qtd_teorica": [2_441_951_100, 4_410_957_710, 5_337_898_685],
        "participacao_pct": [5.038, 8.233, 8.747],
    })


CNPJ = {"9512": "33000167000101", "19348": "60872504000123"}


def test_carteira_usa_a_ultima_composicao_e_soma_os_papeis_da_companhia():
    c = nv.montar_carteira(_casadas(), _acoes(), CNPJ).set_index("cd_cvm")
    assert c.loc["9512", "codigos"] == "PETR3 PETR4"
    assert c.loc["9512", "peso_pct"] == pytest.approx(13.271)
    assert c.loc["19348", "data_acoes"] == "2026-06-30"
    assert c.loc["19348", "acoes_circulacao"] == pytest.approx((5_617_743 + 5_409_126 - 4_997) * 1e3)


def test_pl_e_soma_do_valor_sobre_soma_do_lucro_ponderado():
    casadas = _casadas()
    cart = nv.montar_carteira(casadas, _acoes(), CNPJ)
    dias = pd.bdate_range("2026-09-21", "2026-09-25")
    precos = pd.DataFrame({"PETR3": 40.0, "PETR4": 36.0, "ITUB4": 42.0}, index=dias)
    lucro = pd.DataFrame({"9512": 125e9, "19348": 47e9}, index=dias)
    s = nv.serie_pl(precos, casadas, cart, lucro)
    f = cart.set_index("cd_cvm")["f"]
    valor = 2_441_951_100 * 40 + 4_410_957_710 * 36 + 5_337_898_685 * 42
    esperado = valor / (f["9512"] * 125e9 + f["19348"] * 47e9)
    assert s["pl"].iloc[-1] == pytest.approx(esperado)
    assert s["cobertura_pct"].iloc[-1] == pytest.approx(100.0)


def test_companhia_sem_preco_sai_do_numerador_e_do_denominador():
    casadas = _casadas()
    cart = nv.montar_carteira(casadas, _acoes(), CNPJ)
    dias = pd.bdate_range("2026-09-21", "2026-09-25")
    precos = pd.DataFrame({"PETR3": 40.0, "PETR4": 36.0}, index=dias)   # sem ITUB4
    lucro = pd.DataFrame({"9512": 125e9, "19348": 47e9}, index=dias)
    s = nv.serie_pl(precos, casadas, cart, lucro, minimo=0.5)
    f = cart.set_index("cd_cvm")["f"]["9512"]
    assert s["pl"].iloc[-1] == pytest.approx((2_441_951_100 * 40 + 4_410_957_710 * 36) / (f * 125e9))
    assert s["cobertura_pct"].iloc[-1] == pytest.approx(13.271 / 22.018 * 100, rel=1e-3)
    assert s["pl"].isna().all() == False  # noqa: E712
    s80 = nv.serie_pl(precos, casadas, cart, lucro, minimo=0.8)
    assert s80["pl"].isna().all(), "cobertura de 60% nao passa no portao de 80%"


def test_pl_pelo_redutor_usa_indice_vezes_redutor_como_valor():
    casadas = _casadas()
    cart = nv.montar_carteira(casadas, _acoes(), CNPJ)
    r = nv.pl_pelo_redutor(183_477.0, 14_013_018.53470505, cart,
                           pd.Series({"9512": 125e9, "19348": 47e9}))
    assert r["valor_carteira"] == pytest.approx(183_477.0 * 14_013_018.53470505)
    assert r["cobertura_pct"] == pytest.approx(100.0)
    tab = r["tabela"].set_index("cd_cvm")
    assert tab.loc["9512", "pl_implicito"] > 0


# ---------------------------------------------------------------------------
# fontes: redutor da B3 e subconta da controladora na CVM
# ---------------------------------------------------------------------------

def test_cabecalho_da_b3():
    h = {"date": "28/09/26", "reductor": "14.013.018,53470505",
         "theoricalQty": "93.803.750.400"}
    out = b3.ler_cabecalho(h)
    assert out["redutor"] == pytest.approx(14_013_018.53470505)
    assert out["data_carteira"] == "2026-09-28"
    assert b3.ler_cabecalho({}) == {}


def _linha(cd, conta, ds, valor, ini="2025-01-01", fim="2025-12-31"):
    return {"CD_CVM": cd, "DENOM_CIA": "X", "CNPJ_CIA": "1", "CD_CONTA": conta,
            "DS_CONTA": ds, "VL_CONTA": str(valor), "ESCALA_MOEDA": "MIL",
            "ORDEM_EXERC": "ÚLTIMO", "DT_INI_EXERC": ini, "DT_FIM_EXERC": fim}


def test_lucro_da_controladora_quando_publicado():
    """Banco do Brasil, DFP 2025: 16,8 bi consolidado, 13,7 bi da controladora."""
    df = pd.DataFrame([
        _linha("1023", "3.11", "Lucro ou Prejuízo Líquido Consolidado do Período", 16781938),
        _linha("1023", "3.11.01", "Atribuído aos Sócios da Empresa Controladora", 13698124),
        _linha("1023", "3.11.02", "Atribuído aos Sócios não Controladores", 3083814),
    ])
    out = cvm._extract_profit(df, freq="A")
    assert out["lucro"].iloc[0] == pytest.approx(16_781_938_000)
    assert out["lucro_ctrl"].iloc[0] == pytest.approx(13_698_124_000)


def test_subconta_zerada_ou_ausente_fica_com_a_conta_mae():
    """Klabin publica 3.11.01 = 0 no DFP 2025; BB Seguridade nao publica."""
    df = pd.DataFrame([
        _linha("12653", "3.11", "Lucro/Prejuízo Consolidado do Período", 1678211),
        _linha("12653", "3.11.01", "Atribuído a Sócios da Empresa Controladora", 0),
        _linha("23159", "3.11", "Resultado Líquido das Operações Continuadas", 9017329),
    ])
    out = cvm._extract_profit(df, freq="A").set_index("cd_cvm")
    assert out.loc["12653", "lucro_ctrl"] == pytest.approx(1_678_211_000)
    assert out.loc["23159", "lucro_ctrl"] == pytest.approx(9_017_329_000)


def test_no_itr_a_subconta_casa_com_o_trimestre_e_nao_com_o_acumulado():
    df = pd.DataFrame([
        _linha("9512", "3.11", "Lucro/Prejuízo Consolidado do Período", 85256000, "2026-01-01", "2026-06-30"),
        _linha("9512", "3.11", "Lucro/Prejuízo Consolidado do Período", 52495000, "2026-04-01", "2026-06-30"),
        _linha("9512", "3.11.01", "Atribuído a Sócios da Empresa Controladora", 85108000, "2026-01-01", "2026-06-30"),
        _linha("9512", "3.11.01", "Atribuído a Sócios da Empresa Controladora", 52445000, "2026-04-01", "2026-06-30"),
    ])
    out = cvm._extract_profit(df, freq="T")
    assert len(out) == 1
    assert out["lucro"].iloc[0] == pytest.approx(52_495_000_000)
    assert out["lucro_ctrl"].iloc[0] == pytest.approx(52_445_000_000)


def test_composicao_do_capital():
    cap = pd.DataFrame([{"CNPJ_CIA": "60.872.504/0001-23", "DT_REFER": "2026-06-30",
                         "VERSAO": "1", "DENOM_CIA": "ITAU",
                         "QT_ACAO_ORDIN_CAP_INTEGR": "5617743",
                         "QT_ACAO_PREF_CAP_INTEGR": "5409126",
                         "QT_ACAO_TOTAL_CAP_INTEGR": "11026869",
                         "QT_ACAO_ORDIN_TESOURO": "0", "QT_ACAO_PREF_TESOURO": "4997",
                         "QT_ACAO_TOTAL_TESOURO": "4997"}])
    a = cvm._extract_acoes(cap)
    n, data = nv.acoes_em_circulacao(a, "60872504000123")
    assert n == pytest.approx(11_021_872) and data == "2026-06-30"


def test_fetch_range_devolve_acoes_sem_quebrar_o_concat():
    """Com o numero de acoes em df.attrs, o pd.concat de DFP com ITR quebrava:
    o pandas compara os attrs dos pedacos, e DataFrame == DataFrame nao e bool."""
    import io
    import zipfile
    from unittest import mock

    def _zip(prefixo, ano, fim, ini):
        dre = ("CNPJ_CIA;CD_CVM;DENOM_CIA;CD_CONTA;DS_CONTA;VL_CONTA;ESCALA_MOEDA;"
               "ORDEM_EXERC;DT_INI_EXERC;DT_FIM_EXERC\n"
               f"1;9512;PETRO;3.11;Lucro;100;MIL;ÚLTIMO;{ini};{fim}\n")
        cap = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;QT_ACAO_ORDIN_CAP_INTEGR;"
               "QT_ACAO_PREF_CAP_INTEGR;QT_ACAO_TOTAL_CAP_INTEGR;QT_ACAO_ORDIN_TESOURO;"
               "QT_ACAO_PREF_TESOURO;QT_ACAO_TOTAL_TESOURO\n"
               f"1;{fim};1;PETRO;10;5;15;0;0;0\n")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(f"{prefixo}_cia_aberta_DRE_con_{ano}.csv", dre.encode("latin-1"))
            zf.writestr(f"{prefixo}_cia_aberta_composicao_capital_{ano}.csv", cap.encode("latin-1"))
        return buf.getvalue()

    def falso(bases, arquivo):
        ano = int(arquivo[-8:-4])
        if arquivo.startswith("dfp"):
            return _zip("dfp", ano, f"{ano}-12-31", f"{ano}-01-01"), arquivo
        return _zip("itr", ano, f"{ano}-06-30", f"{ano}-04-01"), arquivo

    acoes: list = []
    with mock.patch.object(cvm, "_baixar", side_effect=falso):
        dfp = cvm.fetch_range([2024, 2025], "DFP", acoes_out=acoes)
        itr = cvm.fetch_range([2025], "ITR", acoes_out=acoes)
    lucros = pd.concat([dfp, itr], ignore_index=True)
    assert len(lucros) == 3 and set(lucros["freq"]) == {"A", "T"}
    assert len(acoes) == 3 and all("on" in a.columns for a in acoes)


def test_posicao_historica_coincide_com_percentil_do_pl_quando_lucro_positivo():
    from src import metrics
    idx = pd.bdate_range("2020-01-01", periods=60)
    rng = np.random.default_rng(7)
    valor = pd.Series(100.0 + rng.normal(0, 5, 60).cumsum(), index=idx)
    lucro = pd.Series(8.0 + rng.normal(0, 0.3, 60), index=idx)
    pos = nv.posicao_historica(valor, lucro, 40)
    pct_pl = metrics.rolling_percentile(valor / lucro, 40)
    pd.testing.assert_series_equal(pos["pct"].round(9), pct_pl.round(9), check_names=False)


def test_posicao_historica_poe_prejuizo_no_topo_e_nao_explode_o_z():
    idx = pd.bdate_range("2020-01-01", periods=40)
    valor = pd.Series(100.0, index=idx)
    lucro = pd.Series(10.0, index=idx)          # P/L 10x
    lucro.iloc[10:15] = 0.5                     # P/L 200x
    lucro.iloc[15:20] = -2.0                    # P/L indefinido
    lucro.iloc[-1] = 9.0                        # hoje: P/L ~11x
    pos = nv.posicao_historica(valor, lucro, 40)
    # hoje e mais caro que os 29 dias a 10x, mais barato que os 10 extremos
    assert pos["pct"].iloc[-1] == pytest.approx(30 / 40 * 100)
    # prejuizo entra na amostra (o P/L seria NaN) e fica no topo
    assert pos["pct"].iloc[19] == pytest.approx(100.0)
    assert np.isfinite(pos["z"].iloc[-1]) and abs(pos["z"].iloc[-1]) < 1
