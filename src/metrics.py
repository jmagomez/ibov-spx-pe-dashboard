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
    if q.empty:
        return q.astype("float64")
    # A janela e de quatro TRIMESTRES CONSECUTIVOS DO CALENDARIO, e nao de quatro
    # LINHAS. A diferenca parece detalhe e nao e. O ITR da CVM cobre so 1T, 2T e
    # 3T -- o 4T vem na DFP, como exercicio fechado. Um rolling(4) sobre as
    # linhas do ITR juntava, em 30/06/2026, 2T25 + 3T25 + 1T26 + 2T26: pulava o
    # 4T25 e trazia de volta um trimestre de 15 meses atras. Somava quatro
    # trimestres, entao o NIVEL parecia plausivel, e por isso o erro passou.
    # Medido no dado real, o lucro agregado saiu 14% acima do correto em
    # 30/06/2026 e 30% acima em 30/09/2025; so a Vale respondia por R$ 35 bi,
    # porque o prejuizo do 4T25 simplesmente nao entrava na conta.
    #
    # Agora o indice vira periodo trimestral e e reindexado no calendario
    # completo: trimestre que falta vira NaN, e NaN contamina as quatro somas
    # que o incluiriam. Buraco e buraco -- nao se pula por cima dele.
    per = q.index.to_period("Q")
    manter = ~per.duplicated(keep="last")
    q, per = q[manter], per[manter]
    s = pd.Series(q.values, index=per, dtype="float64")
    s = s.reindex(pd.period_range(per.min(), per.max(), freq="Q"))
    ttm = s.rolling(window=min_quarters, min_periods=min_quarters).sum()
    return pd.Series(ttm.reindex(per).values, index=q.index, dtype="float64")


def sem_zero_de_formulario(lucros: pd.DataFrame) -> pd.DataFrame:
    """Descarta lucro EXATAMENTE zero: e formulario vazio, nao resultado.

    Companhia sem controladas pode entregar a DRE consolidada zerada e publicar
    o resultado so na individual. No dado da CVM ha 45 linhas com lucro 0,00 --
    0,3% do total, mas quatro das companhias afetadas estao na carteira atual do
    Ibovespa: BB Seguridade (tres periodos, numa companhia que lucra ~R$ 9 bi/ano),
    TIM S.A. (1T24 a 3T24 e os exercicios de 2024 e 2025), Lojas Renner e Auren. Somado como
    zero, o numero rebaixava o lucro agregado E contava a companhia como
    coberta, o que escondia o buraco do portao de cobertura. Lucro liquido de
    companhia aberta igual a zero ate o centavo nao acontece; descartado, vira o
    que e -- dado ausente --, e a cobertura passa a refletir isso.
    """
    if lucros is None or lucros.empty or "lucro" not in lucros.columns:
        return lucros
    return lucros[pd.to_numeric(lucros["lucro"], errors="coerce") != 0]


def completar_quarto_trimestre(lucros_empresa: pd.DataFrame) -> pd.Series:
    """Serie trimestral de UMA companhia, com o 4T derivado da DFP.

    O ITR traz 1T, 2T e 3T. O 4T nao e publicado como trimestre: sai embutido
    no exercicio anual da DFP. Logo

        4T(ano) = lucro anual(ano) - [1T + 2T + 3T](ano)

    e so e calculado quando os TRES trimestres do ano e o exercicio anual
    existem, e o exercicio fecha em dezembro. Faltando qualquer peca, o 4T nao
    e inventado: fica ausente, e a soma de 12 meses que dependeria dele fica
    NaN (ver ttm_from_quarterly). Companhia com exercicio fora de dezembro nao
    entra na derivacao pelo mesmo motivo -- os "trimestres" dela nao sao os do
    calendario e a subtracao misturaria periodos.

    Pressupoe que o ITR traga o valor DO TRIMESTRE, e nao o acumulado no ano.
    Verificado no dado real: mediana de 2T/1T = 1,09 e 3T/1T = 1,19 em 1.210
    pares de companhias com lucro positivo; acumulado daria ~2 e ~3.

    Args:
        lucros_empresa: linhas de UMA companhia com data_fim, lucro e,
            opcionalmente, freq ("T" trimestral, "A" anual). Sem a coluna freq,
            todas as linhas sao tratadas como trimestrais.
    """
    g = sem_zero_de_formulario(lucros_empresa)
    if "freq" in g.columns:
        tri = g[g["freq"] == "T"]
        anu = g[g["freq"] == "A"]
    else:
        tri, anu = g, g.iloc[0:0]
    q = tri.groupby("data_fim")["lucro"].sum().sort_index().astype("float64")
    if anu.empty or q.empty:
        return q
    por_periodo = pd.Series(q.values, index=q.index.to_period("Q"))
    q4 = {}
    for data_fim, valor in anu.groupby("data_fim")["lucro"].sum().items():
        data_fim = pd.Timestamp(data_fim)
        if data_fim.month != 12:
            continue
        ano = data_fim.year
        pedacos = [pd.Period(f"{ano}Q{k}", freq="Q") for k in (1, 2, 3)]
        if not all(p in por_periodo.index for p in pedacos):
            continue
        acumulado_9m = float(por_periodo.loc[pedacos].sum())
        q4[data_fim] = float(valor) - acumulado_9m
    if not q4:
        return q
    out = pd.concat([q, pd.Series(q4, dtype="float64")]).sort_index()
    # Se o ITR tiver trazido um "4T" proprio, ele prevalece sobre o derivado.
    return out[~out.index.duplicated(keep="first")]


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
                      trimestral: bool = False, pesos: dict | None = None):
    """Projeta o lucro de CADA companhia no calendario diario e soma.

    Somar por data_fim e so depois projetar esta errado, e o erro nao e sutil.
    As companhias tem fins de exercicio diferentes; agrupar por data_fim junta
    apenas as que fecham naquele dia, e a serie-degrau resultante salta para o
    SUBTOTAL do ultimo grupo em vez do total. O agregado do Ibovespa oscilava
    entre R$ 0,8 bi e R$ 150 bi dentro do mesmo ano de 2011 por causa disso, e
    o indice normalizado chegava a 20.000 numa serie de base 100.

    Aqui cada companhia vira a sua propria serie-degrau, com o mesmo teto de
    validade das demais, e a soma e feita ponto a ponto. Devolve tambem quanto
    do indice tinha lucro vigente em cada data -- sem esse numero nao da para
    distinguir "o lucro agregado caiu" de "menos empresas foram somadas".

    A segunda saida e medida em PESO do indice quando `pesos` e informado, e em
    contagem de companhias quando nao e. Peso e o criterio certo: uma companhia
    que vale 0,06% do Ibovespa nao deveria ter o mesmo poder de veto que uma que
    vale 8,5%. Medido no dado real, exigir 80% das COMPANHIAS cortava a serie em
    2014; exigir 80% do PESO a estende ate 2010, quando a cobertura ja era de
    84,8% -- e o criterio fica mais exigente onde importa, nao menos.

    Args:
        lucros: DataFrame com cd_cvm, data_fim e lucro.
        pesos: {cd_cvm normalizado: participacao no indice, em pontos percentuais}.
        trimestral: se True, cada companhia passa por soma movel de 4 trimestres
            ANTES da projecao. Somar trimestres de companhias diferentes e depois
            acumular 12 meses misturaria periodos distintos. Neste modo as linhas
            anuais (freq "A") nao sao somadas: servem para derivar o 4T, que o
            ITR nao publica. Passe as duas frequencias juntas.
    """
    if lucros.empty:
        vazio = pd.Series(index=daily_index, dtype="float64")
        return vazio, pd.Series(0.0, index=daily_index)

    total = pd.Series(0.0, index=daily_index)
    cobertura = pd.Series(0.0, index=daily_index)
    for cd, g in lucros.groupby("cd_cvm"):
        if trimestral:
            # O 4T vem da DFP (linhas freq "A"); sem ele a soma de 12 meses
            # ficaria sempre com um trimestre de fora. Ver ttm_from_quarterly.
            s = ttm_from_quarterly(completar_quarto_trimestre(g))
            if s.dropna().empty:
                continue
        else:
            s = g.groupby("data_fim")["lucro"].sum().sort_index()
        d = step_to_daily(s, daily_index, lag_days, max_stale_days)
        total = total.add(d.fillna(0.0))
        # Peso da companhia no indice, ou 1 quando nao ha pesos: nesse caso a
        # cobertura vira contagem, que e o comportamento anterior.
        w = 1.0 if pesos is None else float(pesos.get(str(cd), 0.0))
        cobertura = cobertura.add(d.notna().astype(float) * w)
    return total.where(cobertura > 0), cobertura


def serie_12m_empresa(lucros_empresa: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Lucro de 12 meses de UMA companhia, com a melhor frequencia disponivel.

    Uniao de duas fontes do mesmo conceito -- lucro de 12 meses --, indexadas
    pela data de referencia:

      * LTM trimestral (ITR com 4T derivado da DFP), onde os quatro trimestres
        existem;
      * exercicio anual da DFP, onde nao ha LTM valido para aquela data.

    Nas datas de dezembro as duas coincidem por construcao (LTM do 4T = soma
    dos quatro trimestres = exercicio), e o trimestral e mantido.

    Por que por COMPANHIA e nao no agregado: a versao anterior montava dois
    agregados, um so de ITR e outro so de DFP, e escolhia um deles por data. A
    companhia que tinha um buraco no ITR (a TIM nao tem os tres trimestres de
    2025 no dado da CVM) saia do agregado trimestral inteira, e o lucro anual
    dela, que existia, nao entrava no lugar. Agora cada companhia contribui com
    o lucro de 12 meses mais recente que ela de fato tem.

    Devolve (valores, eh_trimestral), ambos indexados pela data de referencia.
    """
    g = sem_zero_de_formulario(lucros_empresa)
    ltm = pd.Series(dtype="float64")
    if "freq" in g.columns and (g["freq"] == "T").any():
        ltm = ttm_from_quarterly(completar_quarto_trimestre(g)).dropna()
    if "freq" in g.columns:
        anu = g[g["freq"] == "A"]
    else:
        anu = g.iloc[0:0]
    anual = anu.groupby("data_fim")["lucro"].sum().sort_index().astype("float64")
    anual = anual[~anual.index.isin(ltm.index)]
    valores = pd.concat([ltm, anual]).sort_index()
    eh_tri = pd.Series(np.r_[np.ones(len(ltm)), np.zeros(len(anual))],
                       index=ltm.index.append(anual.index)).sort_index()
    return valores, eh_tri


def soma_mista(lucros: pd.DataFrame, daily_index: pd.DatetimeIndex, lag_days: int,
               max_stale_anual: int, max_stale_trimestral: int,
               pesos: dict | None = None):
    """Lucro agregado de 12 meses, com cada companhia na melhor frequencia que tem.

    Devolve (total, cobertura, cobertura_trimestral): a soma ponto a ponto; o
    peso do indice (ou a contagem, sem `pesos`) com lucro vigente; e quanto
    desse peso vem de LTM trimestral. A terceira serie substitui o rotulo
    binario "anual/trimestral" do agregado, que deixou de fazer sentido quando
    a escolha passou a ser por companhia.

    O teto de validade da ultima observacao segue o tipo dela: 200 dias se for
    trimestral, 550 se for anual (ver config.py).
    """
    total = pd.Series(0.0, index=daily_index)
    cobertura = pd.Series(0.0, index=daily_index)
    cob_tri = pd.Series(0.0, index=daily_index)
    if lucros is None or lucros.empty:
        return total.where(cobertura > 0), cobertura, cob_tri
    for cd, g in lucros.groupby("cd_cvm"):
        valores, eh_tri = serie_12m_empresa(g)
        if valores.dropna().empty:
            continue
        teto = max_stale_trimestral if eh_tri.iloc[-1] > 0 else max_stale_anual
        d = step_to_daily(valores, daily_index, lag_days, teto)
        t = step_to_daily(eh_tri, daily_index, lag_days, teto)
        w = 1.0 if pesos is None else float(pesos.get(str(cd), 0.0))
        total = total.add(d.fillna(0.0))
        cobertura = cobertura.add(d.notna().astype(float) * w)
        cob_tri = cob_tri.add((d.notna() & (t > 0)).astype(float) * w)
    return total.where(cobertura > 0), cobertura, cob_tri


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


# ---------------------------------------------------------------------------
# Leitura dos numeros: crescimento do lucro, historia longa, juros
# ---------------------------------------------------------------------------

def variacao_anual(serie: pd.Series, dias: int = 365) -> pd.Series:
    """Variacao percentual contra o valor vigente `dias` antes, observacao a observacao.

    Feita sobre a serie-FONTE (mensal da Shiller ou trimestral da S&P DJI), antes
    de projetar no calendario diario, para que "a/a" compare dois LPA de 12 meses
    que existiram de fato, e nao dois pontos de um degrau com ffill.
    """
    s = serie.sort_index().dropna()
    if s.empty:
        return s.astype("float64")
    anterior = s.reindex(s.index - pd.Timedelta(days=dias), method="ffill")
    anterior.index = s.index
    # asof: o valor anterior precisa ter existido na data de referencia. Antes
    # do inicio da serie nao ha base de comparacao -- NaN, nao zero.
    anterior = anterior.where(s.index - pd.Timedelta(days=dias) >= s.index.min())
    return (s / anterior.where(anterior > 0) - 1.0) * 100.0


def resumo_historico(historico: pd.Series, atual: float) -> dict:
    """Onde `atual` cai dentro de TODA a historia disponivel, e nao de 10 anos.

    O percentil de janela movel responde "caro em relacao a esta decada". Quando
    a propria decada foi a segunda mais cara ja registrada, essa resposta
    subestima o nivel absoluto -- com o P/E do S&P em 26x, o percentil de 10
    anos marcava 68, e o desde 2010, 81. Esta funcao devolve a outra leitura,
    contra a distribuicao completa.

    O percentil e a fracao de observacoes <= atual, em 0-100.
    """
    h = pd.to_numeric(historico, errors="coerce").dropna()
    if h.empty or atual is None or not np.isfinite(atual):
        return {}
    return {
        "atual": round(float(atual), 2),
        "percentil": round(float((h <= atual).mean() * 100.0), 1),
        "mediana": round(float(h.median()), 2),
        "media": round(float(h.mean()), 2),
        "p10": round(float(h.quantile(0.10)), 2),
        "p90": round(float(h.quantile(0.90)), 2),
        "maximo": round(float(h.max()), 2),
        "data_maximo": str(pd.Timestamp(h.idxmax()).date()),
        "inicio": str(pd.Timestamp(h.index.min()).date()),
        "fim": str(pd.Timestamp(h.index.max()).date()),
        "n": int(h.size),
        "acima_do_atual": int((h > atual).sum()),
    }


def premio_sobre_juro(rendimento_pct: pd.Series, juro_pct: pd.Series) -> pd.Series:
    """Diferenca, em pontos percentuais, entre um rendimento de acoes e um juro.

    Com o juro REAL de 10 anos (TIPS), earnings yield menos juro e uma proxy
    grosseira do premio de risco de acoes: o lucro e real por construcao (cresce
    com a inflacao), entao o comparavel e o juro real, nao o nominal. Com o
    rendimento do CAPE (1/CAPE) no lugar do earnings yield, e a construcao do
    "excess CAPE yield" de Shiller, com juro de mercado em vez do juro real que
    ele estima a partir da inflacao passada.
    """
    a, b = rendimento_pct.align(juro_pct, join="left")
    return a - b
