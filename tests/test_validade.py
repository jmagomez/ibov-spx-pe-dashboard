"""Testes do teto de validade das series-degrau e da selecao de coluna do CAPE.

Estes testes existem por causa de dois erros que chegaram ao ar na versao
publicada em 08/08/2026, e cada um deles falha contra o codigo anterior:

  1. A planilha Shiller parou em 09/2024 e o `ffill` estendeu o LPA por quase
     dois anos. O P/E exibido para 2026 usava lucro de 2024 -- inflado, e sem
     nada na tela que o denunciasse.
  2. A coluna do CAPE era escolhida pela primeira que contivesse "cape" no
     rotulo. "Excess CAPE Yield" contem, e e um rendimento. O grafico rotulado
     CAPE saiu com valores entre 0,01 e 0,06.

Dados sinteticos. Nenhum numero daqui chega ao dashboard.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import metrics
from src.sources import shiller


# ---------------------------------------------------------------------------
# Teto de validade
# ---------------------------------------------------------------------------

def test_sem_teto_o_ffill_estende_para_sempre():
    """Documenta o comportamento antigo: e o bug, nao a correcao."""
    step = pd.Series([100.0], index=pd.DatetimeIndex(["2024-09-30"]))
    dias = pd.date_range("2024-01-01", "2026-08-07", freq="B")
    sem_teto = metrics.step_to_daily(step, dias, lag_days=0)
    assert sem_teto.iloc[-1] == 100.0, "sem teto, o ultimo valor vale indefinidamente"


def test_teto_de_validade_esvazia_a_cauda():
    step = pd.Series([100.0], index=pd.DatetimeIndex(["2024-09-30"]))
    dias = pd.date_range("2024-01-01", "2026-08-07", freq="B")
    com_teto = metrics.step_to_daily(step, dias, lag_days=0, max_stale_days=120)
    assert np.isnan(com_teto.iloc[-1]), "apos o vencimento a serie tem de ficar vazia"
    assert com_teto.loc["2024-12-02"] == 100.0
    assert np.isnan(com_teto.loc["2025-06-02"])


def test_teto_nao_apaga_buraco_interno():
    """O teto corta a cauda, nao os intervalos entre observacoes reais."""
    step = pd.Series([10.0, 20.0],
                     index=pd.DatetimeIndex(["2024-03-31", "2025-03-31"]))
    dias = pd.date_range("2024-01-01", "2025-06-30", freq="B")
    s = metrics.step_to_daily(step, dias, lag_days=0, max_stale_days=120)
    assert s.loc["2024-11-01"] == 10.0
    assert s.loc["2025-05-01"] == 20.0


def test_teto_convive_com_lag():
    step = pd.Series([50.0], index=pd.DatetimeIndex(["2025-12-31"]))
    dias = pd.date_range("2025-12-01", "2026-12-31", freq="B")
    s = metrics.step_to_daily(step, dias, lag_days=75, max_stale_days=180)
    assert np.isnan(s.loc["2026-02-02"]), "antes do lag nao ha valor"
    assert s.loc["2026-04-01"] == 50.0
    assert np.isnan(s.loc["2026-11-02"]), "lag + teto = 255 dias apos 31/12/2025"


def test_vencimento_e_defasagem():
    step = pd.Series([1.0], index=pd.DatetimeIndex(["2024-09-30"]))
    assert metrics.vencimento(step, 0, 120) == pd.Timestamp("2025-01-28")
    assert metrics.defasagem_dias(step, pd.Timestamp("2026-08-07")) == 676
    assert pd.isna(metrics.vencimento(pd.Series(dtype=float), 0, 120))


def test_pe_com_lpa_vencido_fica_vazio_e_nao_inflado():
    """Reproduz o erro publicado, em miniatura, com numeros verificaveis a mao."""
    dias = pd.date_range("2024-01-01", "2026-08-07", freq="B")
    preco = pd.Series(np.linspace(4000.0, 8000.0, len(dias)), index=dias)
    eps_mensal = pd.Series([200.0], index=pd.DatetimeIndex(["2024-09-30"]))

    eps_sem_teto = metrics.step_to_daily(eps_mensal, dias, 0)
    pe_errado = metrics.pe_ratio(preco, eps_sem_teto)
    assert pe_errado.iloc[-1] == pytest.approx(40.0), "8000/200 com lucro de 2 anos atras"

    eps_com_teto = metrics.step_to_daily(eps_mensal, dias, 0, max_stale_days=120)
    pe_certo = metrics.pe_ratio(preco, eps_com_teto)
    assert np.isnan(pe_certo.iloc[-1]), "sem lucro vigente nao existe P/E"
    assert pe_certo.dropna().index.max() < pd.Timestamp("2025-02-01")


# ---------------------------------------------------------------------------
# Selecao da coluna de CAPE
# ---------------------------------------------------------------------------

def _planilha(colunas: dict) -> pd.DataFrame:
    """Monta uma aba no formato da ie_data: linha 0 = rotulos, resto = valores."""
    return pd.DataFrame({pos: [rot] + list(vals) for pos, (rot, vals) in colunas.items()})


def _tres_colunas(n: int = 200) -> pd.DataFrame:
    return _planilha({
        0: ("Date", np.linspace(2010.01, 2026.08, n)),
        1: ("CAPE", np.linspace(15.0, 35.0, n)),
        2: ("TR CAPE", np.linspace(18.0, 40.0, n)),
        3: ("Excess CAPE Yield", np.linspace(0.01, 0.06, n)),
    })


def test_cape_escolhe_a_coluna_certa_entre_tres_parecidas():
    df = _tres_colunas()
    serie, rotulo = shiller._escolher_cape(df, df.iloc[1:], list(df.columns), 0)
    assert rotulo == "cape"
    assert 15.0 <= float(pd.to_numeric(serie, errors="coerce").median()) <= 35.0


def test_cape_nao_aceita_a_coluna_de_rendimento():
    """Sem a coluna CAPE, o rendimento NAO pode ser adotado como substituto."""
    df = _tres_colunas().drop(columns=[1, 2])
    serie, rotulo = shiller._escolher_cape(df, df.iloc[1:], list(df.columns), 0)
    assert rotulo == "ausente"
    assert pd.to_numeric(serie, errors="coerce").notna().sum() == 0


def test_cape_rejeita_rotulo_certo_com_valor_absurdo():
    """Layout mudou e a coluna 'CAPE' passou a trazer o inverso: tem de falhar alto."""
    df = _planilha({
        0: ("Date", np.linspace(2010.01, 2026.08, 200)),
        1: ("CAPE", np.linspace(0.01, 0.06, 200)),
    })
    with pytest.raises(Exception) as e:
        shiller._escolher_cape(df, df.iloc[1:], list(df.columns), 0)
    assert "plausivel" in str(e.value)


def test_cape_plausivel_exige_amostra_minima_e_faixa():
    assert not shiller.cape_plausivel(pd.Series([25.0] * 12))
    assert shiller.cape_plausivel(pd.Series([25.0] * 24))
    assert not shiller.cape_plausivel(pd.Series([0.03] * 240))
    assert not shiller.cape_plausivel(pd.Series([250.0] * 240))
