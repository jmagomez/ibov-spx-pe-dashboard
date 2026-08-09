"""Parametros centrais do pipeline.

Nenhum valor de mercado e definido aqui. Apenas datas de corte, URLs de fontes
publicas e convencoes de calculo que estao documentadas em METODOLOGIA.md.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
DOCS = ROOT / "docs"

# Inicio da janela de analise solicitada.
START_DATE = "2010-01-01"

# --- Fontes -----------------------------------------------------------------
# Precos diarios dos indices (CSV livre, sem chave).
STOOQ_TEMPLATE = "https://stooq.com/q/d/l/?s={symbol}&i=d"
SYMBOL_SPX = "^spx"   # S&P 500
SYMBOL_IBOV = "^bvp"  # Ibovespa

# S&P Dow Jones Indices - "S&P 500 Earnings and Estimate Report".
# Contem EPS trimestral as-reported e operating do indice, serie longa.
SPDJI_EPS_XLSX = (
    "https://www.spglobal.com/spdji/en/documents/additional-material/sp-500-eps-est.xlsx"
)

# Robert Shiller (Yale) - planilha ie_data, base do CAPE.
SHILLER_XLS = (
    "https://img1.wsimg.com/blobby/go/e5e77e0b-59d1-44d9-ab25-4763ac982e53/"
    "downloads/ie_data.xls"
)

# B3 - composicao vigente do Ibovespa (endpoint do portal de indices).
B3_INDEX_PORTFOLIO = (
    "https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/"
)

# B3 - cadastro de companhias listadas. E a ponte entre o codigo de negociacao
# (unico identificador que a carteira do indice traz) e o CNPJ (unico
# identificador que a CVM aceita). Sem ela a conciliacao volta a depender de
# razao social, que casou 47,9% do peso do indice.
B3_LISTED_COMPANIES = (
    "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/"
    "GetInitialCompanies/"
)

# CVM - dados abertos de companhias abertas.
CVM_DFP_BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/"
CVM_ITR_BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/"

# --- Convencoes de calculo --------------------------------------------------
# Defasagem entre o fim do trimestre e a data a partir da qual o lucro daquele
# trimestre passa a compor o LPA 12m usado no denominador.
#
#   0  = convencao de indice (S&P DJI/Bloomberg): o trimestre entra na serie
#        datado do proprio fim de trimestre. Comparavel a dados de mercado,
#        mas NAO e point-in-time: no dia 30/06 ninguem conhecia o lucro do 2T.
#   >0 = modo point-in-time. 75 dias cobre o prazo regulatorio brasileiro de
#        ITR (45 dias) e DFP (3 meses) com folga, e o ciclo de reporte dos EUA.
#
# O pipeline gera as DUAS series. A convencao de indice e a exibida por padrao
# no dashboard, por ser a comparavel ao que o mercado publica; a point-in-time
# aparece como sobreposicao, e a diferenca entre elas e o proprio objeto de uma
# das analises criticas.
REPORTING_LAG_DAYS_INDEX = 0
REPORTING_LAG_DAYS_PIT = 75

# Numero minimo de trimestres necessarios para formar um LPA 12m.
TTM_QUARTERS = 4

# Janela para z-score e percentil historico (dias uteis). 2520 ~ 10 anos.
STAT_WINDOW = 2520

# --- Validade da ultima observacao de cada fonte ----------------------------
# O ffill de uma serie-degrau estende o ultimo valor para sempre. Sem um teto,
# uma fonte que para de ser atualizada continua alimentando o dashboard com um
# denominador vencido -- e o grafico nao muda de aparencia. Os limites abaixo
# definem por quanto tempo a ultima observacao de cada fonte ainda tem lastro.
#
# EPS trimestral: 92 dias de trimestre + 45 dias de prazo de divulgacao + folga.
MAX_STALE_DAYS_EPS_TRIMESTRAL = 180
# EPS mensal (planilha Shiller): serie mensal, tolerancia de um trimestre.
MAX_STALE_DAYS_EPS_MENSAL = 120
# CAPE: mensal, mesma tolerancia.
MAX_STALE_DAYS_CAPE = 120
# Lucro anual (DFP): exercicio + 3 meses de prazo regulatorio + folga de um ano,
# porque a serie anual e degrau por construcao e vale ate o exercicio seguinte.
MAX_STALE_DAYS_LUCRO_ANUAL = 550
MAX_STALE_DAYS_LUCRO_TRIMESTRAL = 200

# --- Faixa de plausibilidade do CAPE ---------------------------------------
# O CAPE do S&P 500 oscilou entre ~5 (1920, 1982) e ~44 (2000) em toda a serie
# de Shiller. Uma leitura fora de [3, 100] nao e um CAPE: e coluna errada.
# A planilha traz, lado a lado, "CAPE", "TR CAPE" e "Excess CAPE Yield" -- e a
# ultima, sendo um rendimento (~0,02), passa despercebida se a selecao de
# coluna for por substring. A verificacao abaixo existe por causa disso.
CAPE_MIN_PLAUSIVEL = 3.0
CAPE_MAX_PLAUSIVEL = 100.0

# --- Espelhos e alternativas ------------------------------------------------
# O host da CVM recusou conexao a partir do runner do GitHub Actions em todas as
# execucoes ate 08/08/2026. Manter o esquema http como alternativa custa nada e
# distingue bloqueio de TLS de bloqueio de rota.
CVM_DFP_BASES = (
    "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/",
    "http://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS/",
)
CVM_ITR_BASES = (
    "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/",
    "http://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/",
)

# Cache de lucros ja coletados da CVM. NAO e dado sintetico: e o proprio
# resultado de uma coleta bem-sucedida, com a data em que foi obtido gravada
# junto. Quando a CVM nao responde, o pipeline usa o cache e ANUNCIA que usou,
# com a idade em dias. Se o cache nao existir, a serie do IBOV fica vazia.
CVM_CACHE = PROCESSED / "lucros_cvm.csv"
CVM_CACHE_META = PROCESSED / "lucros_cvm_meta.json"
