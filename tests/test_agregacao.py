"""Testes da agregacao de lucro entre companhias.

O erro que estes testes travam produziu um indice de base 100 com valores acima
de 20.000. Ele nao veio de coleta ruim nem de fonte errada: veio de somar antes
de projetar. Como as companhias fecham exercicio em datas diferentes, agrupar
por data_fim junta so as que fecham naquele dia, e a serie-degrau passa a valer
o SUBTOTAL daquele grupo -- nao o total.

O sintoma no dado real: o lucro agregado do Ibovespa oscilando entre R$ 0,8 bi
e R$ 150 bi dentro do mesmo ano de 2011.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import metrics


def _duas_companhias_com_fins_diferentes() -> pd.DataFrame:
    """Uma fecha em 31/12, a outra em 30/06. Juntas somam 100 por ano."""
    return pd.DataFrame({
        "cd_cvm": ["1", "1", "2", "2"],
        "data_fim": pd.to_datetime(["2020-12-31", "2021-12-31",
                                    "2020-06-30", "2021-06-30"]),
        "lucro": [70.0, 70.0, 30.0, 30.0],
        "freq": ["A"] * 4,
    })


def test_somar_por_data_fim_produz_subtotal_e_nao_total():
    """Documenta o erro: e o comportamento antigo, nao a correcao."""
    lucros = _duas_companhias_com_fins_diferentes()
    dias = pd.date_range("2021-01-01", "2022-12-31", freq="B")

    # forma ERRADA: agrupa por data_fim e projeta o resultado
    por_data = lucros.groupby("data_fim")["lucro"].sum().sort_index()
    errado = metrics.step_to_daily(por_data, dias, 0, 900)
    # em 01/12/2021 vale so a companhia de junho: 30, e nao 100
    assert errado.loc["2021-12-01"] == 30.0


def test_soma_por_entidade_devolve_o_total_das_companhias():
    lucros = _duas_companhias_com_fins_diferentes()
    dias = pd.date_range("2021-01-01", "2022-12-31", freq="B")
    total, cobertas = metrics.soma_por_entidade(lucros, dias, 0, 900)

    assert total.loc["2021-12-01"] == 100.0, "as duas companhias tem de estar na soma"
    assert cobertas.loc["2021-12-01"] == 2
    # a soma nao pode oscilar quando so muda o exercicio de uma delas
    meio = total.loc["2021-07-01":"2022-06-01"].dropna()
    assert meio.nunique() == 1, f"a soma oscilou: {sorted(meio.unique())}"


def test_contagem_de_empresas_distingue_queda_de_lucro_de_queda_de_cobertura():
    """Sem esse numero, 'o lucro caiu' e 'somei menos empresas' sao iguais."""
    lucros = pd.DataFrame({
        "cd_cvm": ["1", "2"],
        "data_fim": pd.to_datetime(["2020-12-31", "2020-12-31"]),
        "lucro": [70.0, 30.0],
        "freq": ["A", "A"],
    })
    dias = pd.date_range("2021-01-01", "2024-12-31", freq="B")
    total, cobertas = metrics.soma_por_entidade(lucros, dias, 0, 550)
    # passado o teto de validade, ninguem sobra e a soma some (em vez de cair)
    assert cobertas.iloc[-1] == 0
    assert np.isnan(total.iloc[-1]), "sem companhia vigente nao ha agregado"
    assert cobertas.loc["2021-06-01"] == 2 and total.loc["2021-06-01"] == 100.0


def test_trimestral_acumula_12m_por_companhia_antes_de_somar():
    """Somar trimestres de companhias diferentes e depois acumular mistura periodos."""
    q = pd.DataFrame({
        "cd_cvm": ["1"] * 5 + ["2"] * 5,
        "data_fim": list(pd.to_datetime(["2022-03-31", "2022-06-30", "2022-09-30",
                                         "2022-12-31", "2023-03-31"])) * 2,
        "lucro": [10.0] * 5 + [5.0] * 5,
        "freq": ["T"] * 10,
    })
    dias = pd.date_range("2023-01-01", "2023-06-30", freq="B")
    total, cobertas = metrics.soma_por_entidade(q, dias, 0, 400, trimestral=True)
    # 4 trimestres de 10 = 40 na companhia 1; 4 de 5 = 20 na 2; total 60
    assert total.dropna().iloc[0] == 60.0
    assert cobertas.max() == 2


def test_sem_lucro_nenhum_devolve_serie_vazia_e_nao_zero():
    dias = pd.date_range("2023-01-01", "2023-03-31", freq="B")
    total, cobertas = metrics.soma_por_entidade(pd.DataFrame(), dias, 0, 400)
    assert total.isna().all(), "vazio e diferente de zero"
    assert (cobertas == 0).all()


# ---------------------------------------------------------------------------
# Cobertura em peso do indice, nao em contagem de companhias
# ---------------------------------------------------------------------------

def test_cobertura_e_medida_em_peso_e_nao_em_contagem():
    """Uma companhia de 0,06% nao pode ter o mesmo poder de veto de uma de 8,5%.

    Medido no dado real em 17/08/2026: exigir 80% das COMPANHIAS cortava a serie
    do Ibovespa em 2014, enquanto a cobertura POR PESO ja era de 84,8% em 2010.
    O criterio por contagem nao era mais conservador -- era so menos alinhado
    com o que o indice e.
    """
    lucros = pd.DataFrame({
        "cd_cvm": ["1", "2"],
        "data_fim": pd.to_datetime(["2021-12-31", "2021-12-31"]),
        "lucro": [100.0, 1.0],
        "freq": ["A", "A"],
    })
    dias = pd.date_range("2022-06-01", "2022-12-31", freq="B")
    pesos = {"1": 90.0, "2": 1.0}   # a primeira e quase o indice inteiro

    # so a companhia grande tem lucro vigente
    so_grande = lucros[lucros["cd_cvm"] == "1"]
    _, cob = metrics.soma_por_entidade(so_grande, dias, 0, 900, pesos=pesos)
    assert cob.iloc[0] == 90.0, "a cobertura tem de ser o PESO, nao a contagem"
    # 90 de 91 pontos = 98,9%: passa num portao de 80% do peso...
    assert cob.iloc[0] / sum(pesos.values()) > 0.80
    # ...e reprovaria num portao de 80% da CONTAGEM (1 de 2 companhias = 50%)

    _, cont = metrics.soma_por_entidade(so_grande, dias, 0, 900)
    assert cont.iloc[0] == 1.0, "sem pesos, a cobertura volta a ser contagem"


def test_sem_pesos_o_comportamento_anterior_e_preservado():
    lucros = pd.DataFrame({
        "cd_cvm": ["1", "2", "3"],
        "data_fim": pd.to_datetime(["2021-12-31"] * 3),
        "lucro": [10.0, 20.0, 30.0],
        "freq": ["A"] * 3,
    })
    dias = pd.date_range("2022-06-01", "2022-08-31", freq="B")
    total, cob = metrics.soma_por_entidade(lucros, dias, 0, 900)
    assert total.iloc[0] == 60.0
    assert cob.iloc[0] == 3.0


def test_peso_de_companhia_fora_do_indice_nao_conta():
    """Lucro de companhia que nao esta na carteira nao deve inflar a cobertura."""
    lucros = pd.DataFrame({
        "cd_cvm": ["1", "999"],
        "data_fim": pd.to_datetime(["2021-12-31", "2021-12-31"]),
        "lucro": [50.0, 50.0],
        "freq": ["A", "A"],
    })
    dias = pd.date_range("2022-06-01", "2022-08-31", freq="B")
    total, cob = metrics.soma_por_entidade(lucros, dias, 0, 900, pesos={"1": 40.0})
    assert cob.iloc[0] == 40.0, "a companhia sem peso nao entra na cobertura"
    assert total.iloc[0] == 100.0, "mas o lucro dela, se foi selecionada, entra na soma"


def test_pesos_e_lucros_usam_a_mesma_forma_de_codigo():
    """Regressao: a CVM zera a esquerda e o mapa de pesos nao.

    Este e o MESMO erro de normalizacao que ja tinha esvaziado a serie uma vez,
    reintroduzido no commit que passou a medir cobertura por peso. O sintoma e
    traicoeiro: cobertura da carteira de 100%, nenhuma excecao, e "nenhuma data
    atingiu o minimo de peso". Quem le o relatorio ve dois numeros que parecem
    se contradizer e nao ha nada apontando para a causa.
    """
    from src import reconcile

    lucros = pd.DataFrame({
        "cd_cvm": ["000906", "009512"],          # como a CVM publica
        "data_fim": pd.to_datetime(["2021-12-31"] * 2),
        "lucro": [100.0, 50.0],
        "freq": ["A", "A"],
    })
    pesos_norm = {"906": 60.0, "9512": 30.0}     # como a conciliacao devolve
    dias = pd.date_range("2022-06-01", "2022-08-31", freq="B")

    # sem normalizar, a cobertura e zero e a serie some
    _, cob_cru = metrics.soma_por_entidade(lucros, dias, 0, 900, pesos=pesos_norm)
    assert cob_cru.iloc[0] == 0.0, "documenta o erro: chave crua nao casa"

    # normalizando os dois lados, a cobertura e o peso de verdade
    lu = lucros.assign(cd_cvm=lucros["cd_cvm"].map(reconcile.normalizar_cd_cvm))
    total, cob = metrics.soma_por_entidade(lu, dias, 0, 900, pesos=pesos_norm)
    assert cob.iloc[0] == 90.0
    assert total.iloc[0] == 150.0


def test_companhia_com_dois_ativos_soma_os_dois_pesos():
    """PETR3 e PETR4 sao a mesma companhia; o peso dela e a soma dos dois."""
    from src import reconcile

    casadas = pd.DataFrame({
        "codigo": ["PETR3", "PETR4", "VALE3"],
        "cd_cvm": ["9512", "9512", "906"],
        "participacao_pct": [4.5, 8.0, 12.0],
    })
    pesos = (casadas.assign(_cd=casadas["cd_cvm"].map(reconcile.normalizar_cd_cvm))
             .groupby("_cd")["participacao_pct"].sum().to_dict())
    assert pesos["9512"] == 12.5, "os dois papeis da mesma empresa somam"
    assert pesos["906"] == 12.0
