# Limitações e análise crítica

Este documento existe porque a parte difícil deste projeto não é calcular uma divisão — é
saber o quanto o resultado da divisão significa. As limitações abaixo estão ordenadas por
gravidade: as primeiras podem inverter uma conclusão.

---

## 1. Não existe P/E diário. Existe preço diário sobre lucro trimestral.

O denominador de qualquer P/E "diário" muda quatro vezes por ano, no melhor caso. Entre uma
divulgação e a seguinte, toda a variação da série vem do numerador. A série é, em rigor,
**preço diário reescalado por uma constante que muda trimestralmente**.

A consequência prática é que a "volatilidade diária do P/E" é a volatilidade do preço, e
lê-la como se fosse informação sobre valuation é um erro. A informação nova entra em degraus,
não continuamente — e os degraus são visíveis na série.

Nada disso é defeito deste projeto: é como o indicador funciona em qualquer provedor. Mas
raramente é dito.

## 2. Viés de sobrevivência no Ibovespa — o problema mais grave da série brasileira

A B3 não publica em formato aberto o histórico de composição do Ibovespa. O pipeline usa a
**carteira vigente** e aplica os lucros dessas mesmas empresas ao passado. Com o P/L em nível
(seção 10), isso ficou explícito: o número de hoje é o P/L do índice; o histórico é o P/L que a
carteira de hoje teria tido.

O efeito é sistemático e conhecido: empresas que entraram no índice depois de 2010 tendem a
ter entrado **porque cresceram**, e empresas que saíram tendem a ter saído **porque
encolheram ou quebraram**. Usar a carteira de hoje para medir o lucro agregado de 2012
significa medir o lucro de uma amostra selecionada pelo próprio sucesso posterior. O lucro
agregado histórico fica **superestimado**, e o múltiplo, **subestimado** — o mercado parece
mais barato no passado do que estava.

A direção do viés é conhecida; a magnitude, não. Não há como estimá-la sem os dados que
faltam. Por isso o percentil histórico do P/L do Ibovespa deve ser lido como posição da carteira
atual contra a própria história, e não do índice contra a dele.

**O que resolveria:** base de constituintes point-in-time (EODHD, Norgate, Refinitiv,
Bloomberg). Todas pagas. É a fronteira do que este projeto entrega de graça.

## 3. Cobertura da conciliação — e o que o portão de 80% não resolve

A conciliação usa o cadastro de listadas da B3, que traz o código CVM e o CNPJ de cada
emissor; razão social normalizada só entra como último recurso, quando o cadastro não
responde. Em setembro de 2026, os 76 ativos da carteira casaram por código CVM, e a lista de
pares fica gravada em `data/processed/ibov_conciliacao.csv`.

Quando o cadastro falha e a conciliação cai para razão social, ela erra em dois sentidos:

- **Falso negativo:** a empresa está no índice, mas a grafia diverge e ela fica de fora do
  agregado. Reduz a cobertura, e o portão de 80% detecta.
- **Falso positivo:** duas companhias com razão social parecida são casadas indevidamente.
  O portão **não detecta isso** — a cobertura sobe e o lucro agregado fica errado.

O segundo caso é o mais perigoso, porque se manifesta como um número plausível. A mitigação
é parcial: prefixo mínimo de 12 caracteres e exigência de 8 caracteres na chave. A auditoria
real exige inspecionar a lista de pares casados, em `data/processed/ibov_conciliacao.csv`
(coluna `via`).

Um detalhe adicional: empresas com múltiplas classes de ação (ON e PN) aparecem duas vezes na
carteira do índice e uma vez na CVM. O agregado de lucro conta a companhia uma vez — correto
—, mas a soma de participação usada no cálculo de cobertura conta as duas linhas. A cobertura
reportada é, portanto, ligeiramente conservadora.

## 4. Contabilidades diferentes, comparação frágil

O S&P 500 reporta em US GAAP; as companhias brasileiras, em IFRS via CVM. Divergências
materiais para o resultado agregado incluem tratamento de arrendamentos, reversões de
impairment (permitidas em IFRS, vedadas em US GAAP) e reconhecimento de ativos fiscais
diferidos.

Some-se a isso a composição setorial: o S&P 500 é dominado por tecnologia, com margens altas
e ativos intangíveis; o Ibovespa, por commodities e bancos, com lucros cíclicos e sensíveis a
preço de minério, petróleo e taxa básica. **Boa parte de qualquer diferença persistente de
múltiplo entre os dois é composição setorial e regime contábil, não "desconto do Brasil".**

E há a moeda: o Ibovespa é medido em reais, com lucros em reais. Uma desvalorização cambial
altera o lucro nominal de exportadoras sem que nada tenha mudado economicamente para um
investidor local. O dashboard não converte para dólar — fazê-lo criaria uma série diferente,
com viés próprio, não uma série melhor.

## 5. Fragilidade das fontes

| Fonte | Risco |
|---|---|
| S&P DJI (`sp-500-eps-est.xlsx`) | Layout muda periodicamente. O parser busca por conteúdo, não por posição, mas uma mudança grande quebra. |
| B3 (endpoint de carteira) | Endpoint interno do portal, sem contrato público de estabilidade. Pode mudar sem aviso. |
| yfinance / Yahoo | Provedor de preço em uso desde 08/2026. Biblioteca de terceiros sobre endpoint não oficial; já respondeu 429 a IP de datacenter. |
| Stooq | Agregador de terceiros, reserva do yfinance. Pode ter ajustes e falhas pontuais. |
| FRED (juros) | Oficial, mas deu ReadTimeout no runner em 26/09/2026. O CSV diário do Tesouro dos EUA entra como reserva. |
| B3 (redutor) | Vem no cabeçalho do mesmo endpoint interno da carteira. Sem ele, o P/L de hoje sai só pela soma de quantidade × preço. |
| yfinance (ações) | Preço de cada papel da carteira, para a série histórica do P/L. Papel sem histórico (renomeado, IPO recente) reduz a cobertura das datas antigas. |
| CVM | Portal estável (ITR desde 2011, DFP desde 2010), mas fica fora do ar às vezes a partir do runner — o pipeline usa o cache da última coleta real e avisa. A estrutura de contas mudou ao longo do tempo. |
| Shiller (`ie_data.xls`) | Hospedado em blob de terceiros; a URL já mudou historicamente. |

Nenhuma dessas fontes tem SLA. Todas podem falhar em qualquer dia útil. O projeto trata isso
mostrando a falha em vez de mascará-la — mas o usuário precisa olhar o painel de diagnóstico,
não só o gráfico.

Ponto específico sobre o preço: para o S&P 500 seria mais rigoroso usar o nível oficial do
índice da própria S&P DJI, para casar numerador e denominador na mesma fonte. Não há endpoint
gratuito estável para isso. Conferido em 25/09/2026, o fechamento usado (7.743,4) bate com o
publicado pela imprensa financeira na casa das unidades, mas a conferência não é automática.

## 6. As estatísticas de posição são ancoradas em um período peculiar

Percentil e z-score são medidos contra 2010–hoje. Esse período contém taxa de juros próxima
de zero por boa parte do tempo nos EUA, expansão de múltiplos, uma pandemia e um ciclo de
aperto monetário. Não é um "período normal" contra o qual medir normalidade.

Com uma série que começa em 2010 e janela de 10 anos, o percentil só existe a partir de
~2015 — e os primeiros anos da estatística são calculados sobre janela incompleta.

Desde 26/09/2026 o dashboard mostra, ao lado, o percentil contra **toda** a planilha de Shiller
(P/E e CAPE desde 1871). A diferença entre as duas leituras é o ponto: com o P/E em 26x, o
percentil de 10 anos marcava 68 — leitura que sugere nível moderado — porque a década de
referência foi, ela própria, das mais caras já registradas. Ver a tabela "Posição na história
longa" no painel.

## 7. Lucro agregado negativo

Quando o lucro agregado é ≤ 0, o P/E é suprimido (`NaN`), não plotado como negativo. Isso é
deliberado: P/E negativo não tem interpretação econômica e, plotado, gera um salto visual que
é lido como informação quando não é. O custo é uma lacuna no gráfico exatamente nos momentos
mais extremos — que é quando alguém mais gostaria de ter o número. Não há solução boa; há a
escolha entre uma lacuna honesta e um artefato enganoso.

## 8. Viés de antecipação na convenção de índice

Descrito em `METODOLOGIA.md`, seção 2.1, e repetido aqui pela consequência: **qualquer
backtest construído sobre a série `pe` (convenção de índice) tem look-ahead bias.** Para
qualquer uso que envolva decisão simulada no tempo, a série correta é `pe_pit`.

---

## 9. Lucro contábil (GAAP) inclui o que não se repete — e em 2026 isso reduziu o P/E

O LPA do S&P 500 usado aqui é o *as reported*: lucro líquido GAAP. Ele inclui baixas contábeis,
reestruturações e, desde a ASU 2016-01 (2018), a **marcação a mercado de participações em
ações** — inclusive de empresas fechadas, a cada nova rodada de captação delas.

Em 2025-26 esse último item deixou de ser detalhe. No 2º trimestre de 2026 a FactSet registrou
crescimento de lucro de 50,4% a/a para o índice, com dois ganhos não operacionais puxando o
número: US$ 98 bi da Alphabet em títulos patrimoniais e US$ 53,4 bi da Amazon na participação
na Anthropic. Sem essas duas companhias, a surpresa de lucro da temporada cairia de 29,2% para
10,9% (FactSet, *Earnings Insight*, 07/08/2026).

No dado deste painel: o LPA 12m da planilha de Shiller subiu **32,7% a/a** até jun/2026
(de 222,5 para 295,4). Ordem de grandeza do efeito, **estimada** e só para os dois ganhos acima,
só no 2T26: cerca de US$ 14 por ação do índice (alíquota de ~23% e divisor do índice de ~8,4 bi
como premissas). Tirados esses US$ 14, o P/E de 26,2x de 25/09/2026 iria para ~27,5x. É um piso
do efeito, não o efeito inteiro: trimestres anteriores também tiveram ganhos dessa natureza.

A consequência para quem lê: **o P/E *trailing* GAAP deste painel está, neste momento,
*abaixo* do P/E sobre lucro recorrente**, e não acima. O cartão "LPA 12m, variação a/a" passou
a sinalizar variação acima de ±20% justamente para isso aparecer sem precisar abrir o CSV.

Três números diferentes circulam como "P/E do S&P 500", e não são contraditórios:

| Medida | Setembro/2026 | O que muda |
|---|---|---|
| P/E projetado 12m (FactSet) | ~20x | Lucro *esperado*, com crescimento de ~25-30% embutido |
| P/E *trailing* GAAP (este painel) | ~26x | Lucro *realizado*, com ganhos não recorrentes |
| P/E *trailing* ex-ganhos de IA (estimativa acima) | ~27,5x | Lucro realizado, sem os dois maiores ganhos do 2T26 |

A S&P DJI publica também o LPA *operating*, que exclui parte desses itens. O coletor dela
existe (`src/sources/spdji.py`), mas o arquivo responde 403 ao runner do GitHub desde a
execução #4 — ver `ESTADO.md`.

## 10. O P/L do Ibovespa em nível: o que foi resolvido e o que continua aberto

Desde 26/09/2026 o Ibovespa tem P/L em nível (`METODOLOGIA.md`, seção 4). Três vieses da série
anterior foram resolvidos na construção: o lucro passou a ser o **atribuível à controladora**, cada
companhia entra na **fração que o índice carrega** (quantidade teórica / ações em circulação), e com
isso holding e controlada no mesmo índice deixaram de ser dupla contagem. O numerador confere com o
da própria B3 (índice × redutor) com diferença de 0,04%.

O que continua aberto, em ordem de peso:

- **Viés de sobrevivência no histórico** (seção 2). O valor de hoje é o P/L da carteira de hoje; o
  histórico é o P/L que esta carteira teria tido. Companhias com lucro deprimido no passado (Petrobras
  em 2014-16 e 2020, Vale em 2015 e 2019) puxam o P/L histórico para cima — a mediana desde 2011
  (~15x) não é "o P/L médio do Ibovespa".
- **P/L agregado explode com lucro perto de zero.** Com o LTM trimestral desde 2011, as baixas do
  4T15 levam o P/L da carteira atual a ~140x no começo de 2017, e em 2016 o lucro agregado chega a ser
  negativo (série vazia). Por isso o percentil e o z-score do Ibovespa são medidos sobre L/P
  (`METODOLOGIA.md`, seção 6). O gráfico usa escala logarítmica.
- **Não é o número dos agregadores.** Conferido em 26/09/2026 contra o Investidor10 (10,80x lá,
  11,25x aqui): o nível de hoje bate em ordem de grandeza, mas as séries divergem de forma
  estrutural. O Investidor10 usa todas as ações com liquidez, não só o Ibovespa, e faz a média
  ponderada dos P/L individuais; aqui é Σ valor / Σ lucro. A média aritmética de P/L é sempre maior
  ou igual ao P/L agregado quando os lucros são positivos — daí este painel sair ~16% abaixo entre
  meados de 2021 e 2023, com lucros de commodities no pico — e, quando há prejuízo, quem faz média de P/L
  individuais descarta a companhia, enquanto o agregado a desconta do denominador — daí sair muito
  acima em 2016-17 e 2020-21. Ver `ESTADO.md`.
- **Lucro contábil, não recorrente.** O LTM é IFRS como publicado. Em 09/2026 a Vale aparece a ~28x
  porque o 4T25 carrega baixas contábeis; o agregado inclui isso. Não há ajuste de itens não
  recorrentes, pelo mesmo motivo da seção 9.
- **Mesmo LPA para ON e PN.** O lucro por ação é L/N para todas as classes. Onde o estatuto dá à PN
  dividendo 10% maior (Bradesco: LPA básico ON 2,13 x PN 2,35 em 2025), a diferença é ignorada.
- **Fração f constante no histórico.** O número de ações é o do último formulário. Emissões e
  recompras passadas não são refeitas; desdobramentos, sim, porque o preço do yfinance vem ajustado
  por eles.
- **Companhias sem lucro consolidado utilizável** saem do numerador e do denominador pelo peso delas:
  TIM (DRE consolidada vazia), Assaí (sem formulário sob o código CVM atual) e Bradespar — 1,3% do
  peso em 09/2026 —, e Tenda (número de ações em escala que não fecha com a quantidade teórica, 0,1%).
  A cobertura aparece no painel e em `status.json` (`pl_ibov`).
- **Composição das units** (BPAC11, ENGI11, IGTI11, KLBN11, SANB11, TAEE11, ALUP11, SAPR11) vem de uma tabela no
  código. Unit fora da tabela é excluída, não presumida; uma mudança de composição exige atualizar a
  tabela.

Corrigido também em 26/09/2026 (ver `ESTADO.md`): o lucro de 12 meses do trecho trimestral deixava o
4º trimestre de fora, e lucro exatamente zero (DRE consolidada vazia) entrava como zero. E o ITR era
coletado só dos últimos cinco anos, com base numa afirmação falsa sobre o portal da CVM: até 2021 o
histórico usava lucro anual defasado em até 15 meses.

## O que estas séries não permitem concluir

- **Que um índice está "caro" ou "barato" em termos absolutos.** P/E alto é compatível com
  juros baixos, crescimento esperado alto ou lucro deprimido no denominador. Os três têm
  implicações opostas.
- **Que um índice está barato em relação ao outro.** Ver seções 2 e 4. Diferença de múltiplo
  entre Brasil e EUA é dominada por composição setorial, contabilidade, moeda e viés de
  amostra.
- **Qualquer coisa sobre retorno futuro em horizonte curto.** A capacidade preditiva de
  múltiplos é reconhecida em horizontes longos e é fraca em horizontes curtos — e mesmo em
  horizontes longos a evidência é sensível ao período amostral escolhido.
- **Que uma reversão à média vai ocorrer.** A média de um múltiplo não é uma constante física.
  Mudanças duradouras em estrutura setorial, tributação, custo de capital e norma contábil
  deslocam o nível de equilíbrio, e não há como distinguir em tempo real "desvio da média" de
  "média nova".

## O que elas permitem

- Observar **quando** o preço se moveu sem que o lucro se movesse, e vice-versa
  (`decompose_price_change`).
- Comparar o múltiplo de hoje com **a própria história recente** do mesmo índice, com a
  ressalva da seção 6.
- Medir a distância entre a convenção de índice e a série point-in-time, que é uma medida
  direta de quanta informação futura a série convencional embute.
- Ter um número **auditável**: toda observação vem de fonte identificada, com data de coleta
  registrada e código aberto que reproduz o cálculo.
