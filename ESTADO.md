# Estado de validacao

Registro honesto do que ja foi exercitado contra a realidade e do que ainda nao.
Atualizado em 26/09/2026.

## Conferência externa do P/L do Ibovespa e ITR desde 2011 (26/09/2026)

**Contra quem.** Investidor10, página "P/L do Ibovespa" (histórico mensal desde 07/2016). Não é
insumo: a metodologia não é reproduzível — universo de todas as ações com liquidez, não só o
Ibovespa, e média ponderada dos P/L individuais. Serve para dizer se nível e direção batem.

**Hoje.** 10,80x lá, 11,25x aqui (+4,2%). Em 2024-26 a diferença média mensal é de +4%.

**O que a conferência achou: um erro nosso, e não deles.** Com o código de então, as séries
divergiam muito em 2021 (21x aqui contra 12x lá) e 2017-18 (+15%). A causa: o pipeline coletava ITR
só dos últimos cinco anos, e a documentação dizia que o portal da CVM "mantém apenas os últimos cinco
anos". Não mantém — o diretório `ITR/DADOS` tem arquivos de 2011 a 2026. Até 2021 o P/L usava o lucro
**anual**, defasado em até 15 meses: durante quase todo o ano de 2021 o denominador era o lucro de 2020
(pandemia), e a queda do P/L só aparecia em abril de 2022. Corrigido: ITR desde `ITR_INICIO = 2011`.
Na validação do runner (branch `claude/validacao-runner-5`), 84,9% do peso coberto passa a vir de LTM
trimestral em 2012-2020, contra 0% antes.

| Comparação mensal com o Investidor10 | Antes (ITR 5 anos) | Depois (ITR desde 2011) |
|---|---|---|
| Correlação de postos (Spearman), 118 meses | 0,76 | **0,89** |
| Diferença média, 2024-26 | +4,0% | +4,0% |
| Diferença média, 06/2021-2023 | +24,3% | −15,9% |
| Diferença média, 04/2017-05/2020 | +15,7% | +12,0% |
| 2021 (P/L de dezembro) | 19,2x | 6,6x (lá: 8,9x) |

**A divergência que sobra é de construção, e tem sinal previsível.** Aqui o P/L é Σ valor / Σ lucro;
lá, média de P/L. Com lucros positivos, a média aritmética de P/L é sempre maior ou igual ao P/L
agregado — por isso este painel sai ~16% abaixo em 2021-23, com lucro de commodities no pico. Com
prejuízo, a média de P/L descarta a companhia e o agregado a desconta do denominador — por isso este
painel sai muito acima quando Petrobras e Vale têm baixas grandes: ~140x em 12/2016-03/2017 (4T15),
25-40x em 06/2020-03/2021 (1T20 da Petrobras), e lucro agregado **negativo** entre 04 e 12/2016 (P/L
indefinido, série vazia). Excluídos os 11 meses acima de 30x, a correlação de nível é 0,88.

**Consequência para as estatísticas.** Com esses meses na janela, a média de 10 anos do P/L ficou em
17,8x e o desvio-padrão em 22,0x: um z-score sobre o P/L não diz nada. Percentil e z-score do
Ibovespa passam a ser calculados sobre L/P (`METODOLOGIA.md`, seção 6), que é contínuo em zero e põe
os meses de prejuízo no topo da distribuição. O gráfico do P/L passa a escala logarítmica.

| Ibovespa, runner de 26/09/2026 | Antes | Depois |
|---|---|---|
| P/L 12m (índice × redutor) | 11,25x | 11,25x (o valor de hoje não muda: o LTM de hoje já vinha do ITR) |
| Percentil de 10 anos | 40 (sobre o P/L) | **43** (sobre L/P) |
| Z-score de 10 anos | −0,5 (sobre o P/L) | **−0,08** (sobre L/P; L/P de 8,9% contra média de 8,7%) |
| Mediana do P/L, 10 anos | 13,9x | 12,8x (p10 6,4x, p90 27,2x) |

Leitura: o Ibovespa está perto do meio da própria história de 10 anos, levemente abaixo da mediana
em P/L. Não é "barato".

**Um defeito operacional que a validação pegou.** Na execução intermediária
(`claude/validacao-runner-4`) o portal da CVM não respondeu ao runner, e o job levou mais de 12
minutos tentando ano a ano (~40 s por ano) antes de cair no cache. `cvm.fetch_range` ganhou um
disjuntor: três anos seguidos com erro de rede e nenhum acerto encerram a coleta. Coberto por teste;
ainda não exercitado no runner com o portal fora do ar.

**Um defeito que só apareceu olhando o gráfico renderizado.** Nos oito meses de 2016 em que o P/L
não existe, o Chart.js ligava o último ponto antes do buraco (~50x) ao primeiro depois (~126x) com uma
reta — uma rampa que parecia dado. `render._serie` passou a interromper a linha em buraco de mais de
15 dias, em todas as séries.

**O que continua dependendo de sorte:** se o portal estiver fora na primeira execução depois do
merge, o cache usado será o de `main`, com ITR só desde 2021, e o histórico sai como antes até a
próxima coleta que funcionar. O painel avisa quando usa cache.

## Execução de validação de 26/09/2026 (branch `claude/validacao-runner-2`)

Números do runner, com o código do PR #2, e não do ambiente de desenvolvimento:

| Medida | Valor | Leitura |
|---|---|---|
| S&P 500 — P/E trailing GAAP | 26,2x | Percentil 93 desde 1871 (mediana 15,1); percentil 68 na janela de 10 anos |
| S&P 500 — CAPE | 40,6 | Percentil 99 desde 1881; só 20 meses acima (quase todos em 1999-2000, mais ago/2026; máximo 44,2 em dez/1999) |
| 1/CAPE − TIPS 10a | −0,37 p.p. | TIPS 2,83% (Tesouro dos EUA; o FRED não respondeu) |
| Earnings yield − TIPS 10a | +0,99 p.p. | Treasury 10a nominal a 5,17% |
| Ibovespa — P/L 12m (índice × redutor) | **11,25x** | 98,6% do peso coberto; lucro da carteira R$ 225 bi |
| Ibovespa — P/L 12m (Σ q × preço) | 11,26x | As duas medidas do numerador diferem 0,04% |
| Ibovespa — percentil do P/L | 40 (10 anos) | Mediana desde 2011: 15,4x (faixa p10-p90: 7,1x a 21,8x); z = −0,5. **Superado** pela seção acima: com ITR desde 2011 e estatísticas sobre L/P, percentil 43 e z −0,08 |

O que o diagnóstico (`tools/diagnostico3.py`) mediu antes de o código ser escrito: o cabeçalho da
carteira do dia da B3 traz o redutor; 432 de 438 companhias publicam a subconta do lucro da
controladora no DFP 2025; a composição do capital vem no mesmo zip da DFP/ITR, **sem escala** —
Petrobras em unidades, Itaú, Vale, Santander, Taesa e Itaúsa em milhares.

Dois defeitos que a execução pegou e que os testes não pegariam:

- O FRED deu ReadTimeout três vezes e o estágio de juros inteiro ficou vazio. O CSV do Tesouro dos
  EUA entrou como reserva.
- O teto de 120 dias para o LPA mensal da Shiller esvaziaria o P/E do S&P a partir de 29/09/2026,
  sem nada errado: o LPA de junho (2T26) é o mais recente que existe até o 3T26 ser compilado. Teto
  agora de 210 dias.

## Auditoria de 26/09/2026: o lucro do Ibovespa deixava o 4T de fora

Revisão feita a partir da pergunta "estes números são mesmo tão altos?". Para o S&P 500 a
resposta foi que os insumos estão certos (preço, LPA e CAPE conferem com fontes independentes)
e que o que faltava era contexto de leitura — ver `LIMITACOES.md`, seção 9. Para o Ibovespa, a
revisão achou erro de cálculo.

**O erro.** O LPA de 12 meses do trecho trimestral era `rolling(4)` sobre as linhas do ITR. O
ITR não tem 4T. Em 30/06/2026 a soma juntava 2T25 + 3T25 + 1T26 + 2T26: pulava o 4T25 e trazia
de volta um trimestre de 15 meses atrás. Eram quatro trimestres, o nível parecia plausível, e
por isso passou.

**O tamanho.** Sobre todas as companhias da CVM com os dois cálculos disponíveis, o lucro
agregado saía 14,2% acima do correto em 30/06/2026, 15,6% em 31/03/2026 e 30,4% em 30/09/2025.
A Vale sozinha respondia por R$ 35 bi em 30/06/2026 (LTM de R$ 44,1 bi no cálculo antigo contra
R$ 8,7 bi no correto), porque o prejuízo de R$ 23,2 bi do 4T25 não entrava na conta.

**A direção não é constante**, e isso importa: o erro foi de −6,5% em jun/2024, +10,7% em
jun/2025, +30,4% em set/2025 e +14,2% em jun/2026. O sinal depende de o trimestre ressuscitado
ser maior ou menor que o 4T que ficava de fora. No trecho de 2025-26, com lucro superestimado, a
razão preço/lucro saía **menor**: o índice de valuation do Ibovespa aparecia **mais barato** do
que era. Além de enviesar o nível, o erro somava ruído à série — o que contamina também o
percentil e o z-score.

**Dois problemas vizinhos, achados no mesmo lugar:**

- Companhia com buraco no ITR saía do agregado trimestral inteira, e o lucro anual dela não
  entrava no lugar (caso da TIM S.A., sem os três trimestres de 2025 no dado). Agora a escolha
  de frequência é por companhia (`metrics.soma_mista`).
- 45 linhas de lucro exatamente zero — DRE consolidada vazia — entravam como zero *e contavam
  como cobertura*. Quatro das companhias afetadas estão na carteira atual do índice: BB
  Seguridade, TIM, Lojas Renner e Auren. Agora são dado ausente.

**Uma fragilidade que não tinha causado erro, mas podia:** no ITR, a DRE traz para a mesma
data de fim a linha do trimestre e a do acumulado no ano. A escolha entre elas era o desempate
de uma ordenação não estável. No dado real caiu sempre no trimestre (mediana de
`(1T+2T+3T)/anual` = 0,74; acumulado daria ~1,5) — por acaso de ordem, não por regra. Agora a
extração fica com a linha de duração de até um trimestre (`DT_INI_EXERC`).

**Uma promessa da documentação que o código não cumpria:** a defasagem point-in-time de 75
dias era descrita como suficiente para a DFP "com folga". O prazo da DFP é de três meses
(31/03), e 31/12 + 75 = 16/03. Na série do Ibovespa, observações de dezembro passam a usar 92
dias; as de ITR seguem com 75.

**O que ficou gravado para auditoria futura:** a conciliação ticker → código CVM passa a ser
salva em `data/processed/ibov_conciliacao.csv`. Sem ela não era possível reproduzir o agregado
fora do runner.

## O defeito mais caro ate agora: HTTP 200 com arquivo de 2024

Entre agosto de 2024 e setembro de 2026, o P/E do S&P 500 no dashboard terminava
em junho de 2024. O CAPE terminava em setembro de 2024. E o `status.json`
trazia, em todas as execucoes, os nove estagios marcados **`ok`**.

Nao havia excecao, log de erro nem fonte "falhou" -- porque, do ponto de vista
do coletor, nada falhou: a URL da planilha ie_data em `config.py` apontava para
`.../downloads/ie_data.xls`, endereco antigo que continua respondendo HTTP 200 e
continua entregando um XLS integro e parseavel. So que congelado. O endereco
vigente, o que o shillerdata.com de fato linka, tem um segmento de pasta a mais.

O mecanismo de teto de validade, que ja existia, fez o que devia: em vez de
repetir o ultimo LPA para sempre, esvaziou o trecho sem lastro e escreveu o
aviso. Foi ele que deixou o sintoma visivel. Mas o aviso dizia "a fonte parou de
ser atualizada", e a fonte nao tinha parado -- nos e que estavamos lendo o
endereco errado. Diagnostico correto sobre o fato, errado sobre a causa.

Tres coisas mudaram por causa disto:

1. `SHILLER_XLS_URLS` e uma lista de espelhos, e a escolha entre eles **nao e
   "o primeiro que responder"**: e o que trouxer a observacao mais recente
   dentro do arquivo. O endereco legado continua na lista, em ultimo lugar,
   porque um dado velho e melhor que nenhum -- mas ele so ganha se for o unico.
2. O dashboard passou a exibir a tabela "Validade da ultima observacao de cada
   fonte", e os cartoes marcam em amarelo o valor sem atualizacao recente. Antes,
   o cartao "Situacao atual" exibia o P/E de 27/09/2024 em corpo 27, com a data
   verdadeira em cinza, 11px, embaixo.
3. `tests/test_espelho_shiller.py` trava a regra.

A generalizacao que fica: **para fonte servida por CDN, status 200 e arquivo
bem-formado nao sao evidencia de dado atualizado**. A unica evidencia e a data
da ultima observacao dentro do arquivo.

## O que esta comprovadamente funcionando

| Componente | Evidencia |
|---|---|
| Testes de calculo | 137 testes passam (`pytest tests -q`), inclusive com o pandas 2.2.3 do runner |
| Orquestracao e diagnostico | `status.json` gerado, com estagio, situacao e detalhe por fonte |
| Renderizacao do dashboard | `docs/index.html` produzido mesmo com todas as fontes falhando |
| Degradacao explicita | Graficos vazios com a causa escrita; nenhum numero inventado |
| Artefato e Step Summary | Publicados a cada execucao |
| Portao final | Falha a execucao quando nenhuma fonte responde — comportamento correto |
| Agendamento | `0 12 * * 2-6` = 9h BRT, de terca a sabado -- uma execucao por pregao |

Em outras palavras: **o encanamento esta validado ponta a ponta**. O que falta
e agua.

## O que esta bloqueado

**Resolvido desde entao:** o bloqueio de preco descrito abaixo deixou de
ocorrer com a entrada do `yfinance` (que faz o handshake TLS se apresentando
como navegador). As execucoes de agosto e setembro de 2026 trazem
`precos_spx` e `precos_ibov` com ~4.200 e ~4.140 pregoes, provedor `yfinance`.
O registro fica porque o diagnostico continua valendo se o bloqueio voltar.

**Continua bloqueado:** a planilha da S&P DJI (`sp-500-eps-est.xlsx`) responde
403 ao runner. O LPA do S&P vem, hoje, da coluna E da planilha de Shiller --
mesma linhagem de dado, fonte declarada no diagnostico. Se a S&P DJI voltar a
responder, ela retoma a primazia sem mudanca de codigo.

**Historico: provedores de preco de indice recusam IPs de datacenter.**

| Execucao | Provedor | Resultado |
|---|---|---|
| #2 | Stooq | Pagina de bloqueio em vez de CSV (`colunas=['This site...']`) |
| #3 | Yahoo Finance chart v8 | `429 Client Error` apos 3 tentativas, para ambos os simbolos |

Os dois casos sao o mesmo fenomeno: a requisicao parte de um runner do GitHub
Actions, e ambos os provedores limitam ou bloqueiam faixas de nuvem. Rodando
localmente, de um IP residencial, a tendencia e funcionar.

Como os precos sao o primeiro estagio, a falha deles impedia que os demais
rodassem. Depois que os precos voltaram, as fontes de lucro foram exercitadas:
Shiller, B3 e CVM respondem do runner; so a S&P DJI continua em 403.

## Caminhos para destravar

Em ordem de custo crescente:

1. **Rodar localmente.** `python -m src.build && python -m src.render` de uma
   maquina comum. Ja cumpriu o papel: foi assim que a cobertura de 100% do peso
   da carteira se confirmou. Continua util para distinguir bloqueio de faixa de
   IP de defeito de codigo.
2. **Chave gratuita de um provedor com API estavel** (Alpha Vantage, Tiingo,
   Twelve Data). Nenhum e pago no nivel de uso deste projeto. Entraria como
   terceiro provedor em `src/sources/prices.py`, com a chave em
   *Settings > Secrets and variables > Actions*.
3. **Self-hosted runner** em IP residencial. Resolve o bloqueio na raiz, mas
   e infraestrutura para manter.

A opcao 2 e a unica que ainda tem serventia real, e so se os precos voltarem a
ser bloqueados.

## O que NAO foi feito para "resolver" o bloqueio

Nao foi adicionado dado embutido, serie de exemplo, valor plausivel ou cache
commitado para que o dashboard "tivesse alguma coisa". Um dashboard vazio que
diz por que esta vazio e um resultado; um dashboard com numero de origem
desconhecida e um passivo.
