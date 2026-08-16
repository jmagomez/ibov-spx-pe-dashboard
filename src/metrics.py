"""Funcoes puras de calculo.

Este modulo nao faz I/O e nao acessa rede. Tudo aqui e testavel offline, e e o
que os testes em tests/test_metrics.py cobrem. Separar o calculo da coleta e
deliberado: permite verificar a aritmetica das metricas sem depender de a fonte
externa estar no ar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Lucro por acao acumulado em 12 meses
# ---------------------------------------------------------------------------

def ttm_from_quarterly(quarterly: pd.Series, min_quarters: int = 4) -> pd.Series:
    """Soma movel de 4 trimestres (LPA 12 meses).

    `quarterly` deve ser indexada por fim de trimestre e ordenada. Trimestres
    faltantes NAO sao preenchidos: o resultado fica NaN, e NaN e propagado ate
    a saida. Preencher um trimestre ausente com estimativa seria inventar lucro.
    """
    if not isinstance(quarterly.index, pd.DatetimeIndex):
        raise TypeError("indice deve ser DatetimeIndex de fins de trimestre")
    q = quarterly.sort_index()
    return q.rolling(window=min_quarters, min_periods=min_quarters).sum()


def annual_to_step(annual: pd.Series) -> pd.Series:
    """Serie anual tratada como degrau.

    Usado para o trecho do Ibovespa anterior a cobertura de ITR, em que apenas
    o lucro anual (DFP) esta disponivel. O valor do exercicio N vale como
    denominador constante ate o exercicio seguinte. E uma aproximacao grosseira
    e esta sinalizada como tal no dashboard.
    """
    if not isinstance(annual.index, pd.DatetimeIndex):
        raise TypeError("indice deve ser DatetimeIndex de fins de exercicio")
    return annual.sort_index()


# ---------------------------------------------------------------------------
# Projecao da serie de lucro sobre o calendario diario
# ---------------------------------------------------------------------------

def step_to_daily(step: pd.Series, daily_index: pd.DatetimeIndex,
                  lag_days: int = 0, max_stale_days: int | None = None) -> pd.Series:
    """Projeta uma serie-degrau de lucro sobre datas diarias de pregao.

    `lag_days` desloca a data de vigencia de cada observacao para frente,
    representando o intervalo entre o fim do periodo contabil e a divulgacao.
    Com lag_days=0 obtem-se a convencao usada pelos provedores de indice; com
    lag>0, uma serie point-in-time.

    Antes da primeira data de vigencia o resultado e NaN. Nao ha extrapolacao
    para tras: o P/E simplesmente nao existe nesse trecho.

    `max_stale_days` limita ate quando a ULTIMA observacao continua valendo.
    Sem esse limite, o `ffill` estende indefinidamente o ultimo valor da fonte
    para frente -- e foi exatamente o que aconteceu na serie publicada em
    08/08/2026: a planilha Shiller parou em 09/2024 e o dashboard seguiu
    exibindo P/E ate 08/2026 com um LPA de dois anos atras, o que INFLA o
    multiplo sem que nada na tela indique o problema. Um trecho vazio no fim do
    grafico e um resultado; um multiplo calculado com denominador vencido e um
    numero errado com aparencia de certo.

    O limite so corta a cauda: buracos internos entre duas observacoes reais
    continuam preenchidos pelo degrau, que e o comportamento correto para uma
    serie de lucro que so muda quando ha nova divulgacao.
    """
    if step.empty:
        return pd.Series(index=daily_index, dtype="float64")
    s = step.sort_index().dropna()
    if s.empty:
        return pd.Series(index=daily_index, dtype="float64")
    shifted = s.copy()
    shifted.index = s.index + pd.Timedelta(days=lag_days)
    shifted = shifted[~shifted.index.duplicated(keep="last")]
    out = shifted.reindex(shifted.index.union(daily_index)).ffill()
    out = out.reindex(daily_index)
    if max_stale_days is not None:
        limite = shifted.index.max() + pd.Timedelta(days=int(max_stale_days))
        out = out.where(pd.DatetimeIndex(out.index) <= limite)
    return out


def vencimento(step: pd.Series, lag_days: int, max_stale_days: int) -> pd.Timestamp:
    """Data a partir da qual a serie-degrau deixa de ter lastro."""
    s = step.sort_index().dropna()
    if s.empty:
        return pd.NaT
    return s.index.max() + pd.Timedelta(days=int(lag_days + max_stale_days))


def defasagem_dias(step: pd.Series, referencia: pd.Timestamp) -> int:
    """Quantos dias a ultima observacao da fonte esta atras da data de referencia."""
    s = step.sort_index().dropna()
    if s.empty:
        return -1
    return int((pd.Timestamp(referencia) - s.index.max()).days)


def soma_por_entidade(lucros, daily_index, lag_days: int, max_stale_days: int,
                      trimestral: bool = False):
    """Projeta o lucro de CADA companhia no calendario diario e soma.

    Somar por data_fim e so depois projetar esta errado, e o erro nao e sutil.
    As companhias tem fins de exercicio diferentes; agrupar por data_fim junta
    apenas as que fecham naquele dia, e a serie-degrau resultante salta para o
    SUBTOTAL do ultimo grupo em vez do total. O agregado do Ibovespa oscilava
    entre R$ 0,8 bi e R$ 150 bi dentro do mesmo ano de 2011 por causa disso, e
    o indice normalizado chegava a 20.000 numa serie de base 100.

    Aqui cada companhia vira a sua propria serie-degrau, com o mesmo teto de
    validade das demais, e a soma e feita ponto a ponto. Devolve tambem quantas
    companhias tinham lucro vigente em cada data -- sem esse numero nao da para
    distinguir "o lucro agregado caiu" de "menos empresas foram somadas".

    Args:
        lucros: DataFrame com cd_cvm, data_fim e lucro.
        trimestral: se True, cada companhia passa por soma movel de 4 trimestres
            ANTES da projecao. Somar trimestres de companhias diferentes e depois
            acumular 12 meses misturaria periodos distintos.
    """
    if lucros.empty:
        vazio = pd.Series(index=daily_index, dtype="float64")
        return vazio, pd.Series(0, index=daily_index, dtype="int64")

    total = pd.Series(0.0, index=daily_index)
    cobertas = pd.Series(0, index=daily_index, dtype="int64")
    for _, g in lucros.groupby("cd_cvm"):
        s = g.groupby("data_fim")["lucro"].sum().sort_index()
        if trimestral:
            s = ttm_from_quarterly(s)
            if s.dropna().empty:
                continue
        d = step_to_daily(s, daily_index, lag_days, max_stale_days)
        total = total.add(d.fillna(0.0))
        cobertas = cobertas.add(d.notna().astype("int64"))
    return total.where(cobertas > 0), cobertas


# ---------------------------------------------------------------------------
# Metricas de valuation
# ---------------------------------------------------------------------------

def pe_ratio(price: pd.Series, eps_ttm: pd.Series) -> pd.Series:
    """P/E = preco do indice / LPA 12m do indice.

    LPA <= 0 devolve NaN, e nao um numero negativo ou infinito. P/E com lucro
    agregado negativo nao tem interpretacao economica util e, se plotado, gera
    exatamente o tipo de artefato visual que induz leitura errada. O periodo em
    que isso ocorre e reportado no painel de diagnostico.
    """
    p, e = price.align(eps_ttm, join="inner")
    out = p / e.where(e > 0)
    return out.replace([np.inf, -np.inf], np.nan)


def earnings_yield(pe: pd.Series) -> pd.Series:
    """Earnings yield = 1 / (P/E), em percentual ao ano."""
    return (1.0 / pe.where(pe > 0)) * 100.0


def relative_pe(pe_a: pd.Series, pe_b: pd.Series) -> pd.Series:
    """Razao entre dois P/E. Valor < 1 indica o indice A negociando com desconto."""
    a, b = pe_a.align(pe_b, join="inner")
    return a / b.where(b > 0)


def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    """Z-score contra a propria janela movel. min_periods = metade da janela."""
    m = series.rolling(window, min_periods=max(2, window // 2)).mean()
    s = series.rolling(window, min_periods=max(2, window // 2)).std(ddof=1)
    return (series - m) / s.where(s > 0)


def rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    """Percentil do valor corrente dentro da propria janela movel, em 0-100."""
    def _pct(x: np.ndarray) -> float:
        cur = x[-1]
        if np.isnan(cur):
            return np.nan
        valid = x[~np.isnan(x)]
        if valid.size < 2:
            return np.nan
        return float((valid <= cur).sum()) / valid.size * 100.0
    return series.rolling(window, min_periods=max(2, window // 2)).apply(_pct, raw=True)


def drawdown_of_multiple(pe: pd.Series) -> pd.Series:
    """Queda do multiplo em relacao ao maximo historico ate a data, em %.

    Separa compressao de multiplo de queda de lucro: uma queda de preco com
    lucro estavel aparece aqui; uma queda de preco acompanhando queda de lucro,
    nao.
    """
    peak = pe.cummax()
    return (pe / peak - 1.0) * 100.0


def decompose_price_change(price: pd.Series, eps: pd.Series,
                           periods: int) -> pd.DataFrame:
    """Decompoe a variacao do preco em contribuicao de lucro e de multiplo.

    Identidade: P = (P/E) x E, logo ln(P_t/P_{t-n}) = ln(PE_t/PE_{t-n}) + ln(E_t/E_{t-n}).
    A decomposicao em log e exata e aditiva, motivo pelo qual e a usada aqui em
    vez da versao em variacao percentual simples, que deixa um termo cruzado.
    """
    p, e = price.align(eps, join="inner")
    pe = p / e.where(e > 0)
    return pd.DataFrame({
        "preco_ln": np.log(p / p.shift(periods)),
        "lucro_ln": np.log(e.where(e > 0) / e.where(e > 0).shift(periods)),
        "multiplo_ln": np.log(pe / pe.shift(periods)),
    })
