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
