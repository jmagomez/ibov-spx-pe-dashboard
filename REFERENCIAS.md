# Referências

Fontes consultadas e utilizadas. Data de verificação dos endpoints: **08/08/2026**.

## Fontes de dados usadas pelo pipeline

| # | Fonte | Uso | Endereço |
|---|---|---|---|
| 1 | S&P Dow Jones Indices — *S&P 500 Earnings and Estimate Report* | LPA trimestral as-reported e operating do S&P 500 | `https://www.spglobal.com/spdji/en/documents/additional-material/sp-500-eps-est.xlsx` |
| 2 | Robert J. Shiller (Yale) — planilha `ie_data` | CAPE mensal | https://shillerdata.com/ |
| 3 | Stooq | Fechamento diário do S&P 500 (`^spx`) e do Ibovespa (`^bvp`) | https://stooq.com/q/d/?s=%5Ebvp&i=d |
| 4 | B3 — portal de índices | Composição vigente do Ibovespa | https://sistemaswebb3-listados.b3.com.br/indexPage/day/IBOV?language=pt-br |
| 5 | CVM — Portal de Dados Abertos, DFP | Lucro líquido consolidado anual, 2010– | https://dados.cvm.gov.br/dataset/cia_aberta-doc-dfp |
| 6 | CVM — Portal de Dados Abertos, ITR | Lucro líquido consolidado trimestral, últimos 5 anos | https://dados.cvm.gov.br/dataset/cia_aberta-doc-itr |
| 7 | B3 — Ibovespa, estatísticas históricas | Referência de conferência do índice | https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-amplos/indice-ibovespa-ibovespa-estatisticas-historicas.htm |

## Metodologia dos índices

| Fonte | Relevância |
|---|---|
| S&P Dow Jones Indices — *Index Mathematics Methodology* | Definição do cálculo de índice, divisor e agregação de lucros |
| S&P Dow Jones Indices — *S&P U.S. Indices Methodology* | Critérios de elegibilidade e rebalanceamento do S&P 500 |
| B3 — *Metodologia do Índice Bovespa* | Quantidade teórica, redutor, critérios de inclusão e rebalanceamento quadrimestral |

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

## Viés de sobrevivência e dados point-in-time

- Discussão de reconstrução de constituintes históricos do S&P 500 e do custo de bases
  point-in-time: EODHD, Norgate Data e literatura associada. Consultado para dimensionar a
  limitação descrita em `LIMITACOES.md`, seção 2.

## Regulatório e calendário

- **Decreto nº 9.772/2019** — revoga o horário de verão no Brasil. Fundamenta o deslocamento
  fixo UTC-3 usado no agendamento do workflow (`0 12 * * 6` = sábados, 9h BRT).
- **Resolução CVM nº 80/2022** — prazos de entrega de ITR (45 dias após o trimestre) e DFP
  (3 meses após o exercício). Base da defasagem de 75 dias adotada na série point-in-time.

## Nota sobre o que não foi usado

Números de P/E divulgados por agregadores comerciais (portais de finanças, plataformas de
research) **não** foram usados como insumo nem como conferência, porque em geral não
documentam a convenção de defasagem, a escolha entre as-reported e operating, nem o
tratamento de lucro negativo. Um número sem metodologia declarada não é verificável, e este
projeto não incorpora número que não possa reproduzir.
