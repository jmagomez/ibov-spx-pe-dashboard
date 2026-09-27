# Referências

Fontes consultadas e utilizadas. Última verificação dos endpoints: **26/09/2026**.

## Fontes de dados usadas pelo pipeline

| # | Fonte | Uso | Endereço |
|---|---|---|---|
| 1 | S&P Dow Jones Indices — *S&P 500 Earnings and Estimate Report* | LPA trimestral as-reported e operating do S&P 500 (responde 403 ao runner desde 08/2026) | `https://www.spglobal.com/spdji/en/documents/additional-material/sp-500-eps-est.xlsx` |
| 2 | Robert J. Shiller (Yale) — planilha `ie_data` | CAPE mensal, LPA 12m mensal (hoje a fonte do LPA do S&P) e história longa desde 1871 | https://shillerdata.com/ |
| 3 | Yahoo Finance, via `yfinance` | Fechamento diário do S&P 500, do Ibovespa e de cada papel da carteira do Ibovespa | https://finance.yahoo.com/ |
| 4 | Stooq | Reserva para o fechamento dos índices | https://stooq.com/ |
| 5 | FRED (St. Louis Fed) — DGS10 e DFII10 | Treasury e TIPS de 10 anos | https://fred.stlouisfed.org/series/DFII10 |
| 6 | Tesouro dos EUA — curvas diárias nominal e real | Reserva do FRED para os juros de 10 anos | https://home.treasury.gov/resource-center/data-chart-center/interest-rates |
| 7 | B3 — carteira do dia do Ibovespa | Composição vigente, quantidade teórica, participação e redutor | https://sistemaswebb3-listados.b3.com.br/indexPage/day/IBOV?language=pt-br |
| 8 | B3 — cadastro de companhias listadas | Ponte entre código de negociação e código CVM/CNPJ | https://sistemaswebb3-listados.b3.com.br/listedCompaniesPage/ |
| 9 | CVM — Portal de Dados Abertos, DFP | Lucro consolidado e da controladora anual, número de ações; 2010– | https://dados.cvm.gov.br/dataset/cia_aberta-doc-dfp |
| 10 | CVM — Portal de Dados Abertos, ITR | Lucro consolidado e da controladora trimestral (1T-3T), número de ações; 2011– | https://dados.cvm.gov.br/dataset/cia_aberta-doc-itr |

## Conferência externa (não é insumo)

| Fonte | O que foi conferido | Diferença de construção |
|---|---|---|
| Investidor10 — [P/L do Ibovespa](https://investidor10.com.br/indices/pl-ibovespa/) | P/L de hoje e histórico mensal desde 07/2016, contra `pl_nivel` (26/09/2026: 10,80x lá, 11,25x aqui; correlação de postos de 0,89 em 118 meses). A conferência revelou que o pipeline coletava ITR só de cinco anos | Universo de todas as ações com liquidez acima de R$ 1 mi/dia, não só o Ibovespa; média ponderada dos P/L individuais; defasagem de divulgação não documentada |

Número de agregador comercial não entra em nenhuma série: a metodologia deles não é
reproduzível. Serve só para dizer se a ordem de grandeza e a direção batem — ver `ESTADO.md`.

## Metodologia dos índices

| Fonte | Relevância |
|---|---|
| S&P Dow Jones Indices — *Index Mathematics Methodology* | Definição do cálculo de índice, divisor e agregação de lucros |
| S&P Dow Jones Indices — *S&P U.S. Indices Methodology* | Critérios de elegibilidade e rebalanceamento do S&P 500 |
| B3 — *Metodologia do Índice Bovespa* | Quantidade teórica, redutor (índice = Σ preço × quantidade / redutor), rebalanceamento quadrimestral |

## Base conceitual das métricas

- **Shiller, R. J.** — *Irrational Exuberance*. Origem do CAPE e da série `ie_data`.
- **Campbell, J. Y.; Shiller, R. J.** (1988) — "Stock Prices, Earnings, and Expected
  Dividends", *Journal of Finance*. Fundamento da relação entre múltiplos e retorno esperado.
- **Campbell, J. Y.; Shiller, R. J.** (1998) — "Valuation Ratios and the Long-Run Stock Market
  Outlook", *Journal of Portfolio Management*. Base da leitura de múltiplos em horizonte longo
  — e da ressalva de que a evidência é fraca em horizonte curto.
- **CFA Institute** — *Equity Asset Valuation*. Tratamento de múltiplos ponderados por
  capitalização, harmonic mean e o problema do P/E agregado com lucros próximos de zero.
- **Damodaran, A.** — *Investment Valuation* e as bases anuais de múltiplos por setor e por
  país. Referência sobre efeito de composição setorial na comparação entre mercados.
- **FactSet** — *Earnings Insight*, 07/08/2026. Ganhos não operacionais de Alphabet e Amazon no
  2T26 (`LIMITACOES.md`, seção 9).

## Viés de sobrevivência e dados point-in-time

- Discussão de reconstrução de constituintes históricos do S&P 500 e do custo de bases
  point-in-time: EODHD, Norgate Data e literatura associada. Consultado para dimensionar a
  limitação descrita em `LIMITACOES.md`, seção 2.

## Regulatório e calendário

- **Decreto nº 9.772/2019** — revoga o horário de verão no Brasil. Fundamenta o deslocamento
  fixo UTC-3 usado no agendamento do workflow (`0 12 * * 2-6` = terça a sábado, 9h BRT).
- **Resolução CVM nº 80/2022** — prazos de entrega de ITR (45 dias após o trimestre) e DFP
  (3 meses após o exercício). Base das defasagens point-in-time de 75 dias (ITR) e 92 dias
  (dezembro).
