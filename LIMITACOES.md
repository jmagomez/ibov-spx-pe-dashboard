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
**carteira vigente** e aplica os lucros dessas mesmas empresas ao passado.

O efeito é sistemático e conhecido: empresas que entraram no índice depois de 2010 tendem a
ter entrado **porque cresceram**, e empresas que saíram tendem a ter saído **porque
encolheram ou quebraram**. Usar a carteira de hoje para medir o lucro agregado de 2012
significa medir o lucro de uma amostra selecionada pelo próprio sucesso posterior. O lucro
agregado histórico fica **superestimado**, e o múltiplo, **subestimado** — o mercado parece
mais barato no passado do que estava.

A direção do viés é conhecida; a magnitude, não. Não há como estimá-la sem os dados que
faltam. Por isso a série do Ibovespa é rotulada como índice de valuation e não como P/E, e
por isso a comparação em nível com o S&P 500 é explicitamente desaconselhada.

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
| FRED (juros) | Oficial e estável, mas é a única fonte dos prêmios sobre juro: se falhar, os dois gráficos de juros ficam vazios. |
| CVM | Portal estável, mas o ITR só mantém cinco anos e a estrutura de contas mudou ao longo do tempo. |
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

## 10. O agregado de lucro do Ibovespa: o que a soma ainda não trata

A série do Ibovespa soma o lucro líquido **consolidado** (conta 3.11 da CVM) das companhias da
carteira vigente. Três vieses conhecidos, nenhum corrigido:

- **Participação de não controladores.** A 3.11 inclui a parcela do lucro que pertence aos
  minoritários das controladas. O correto, para comparar com o preço da ação da controladora,
  seria a 3.11.01 (atribuível aos sócios da controladora). A troca de conta exige validar o
  plano de contas de bancos e seguradoras contra os arquivos originais, o que ainda não foi
  feito.
- **Dupla contagem entre holding e controlada.** Quando as duas estão no índice (Itaúsa e Itaú;
  Cosan e Rumo; Banco do Brasil e BB Seguridade), parte do mesmo lucro entra duas vezes. Como a
  série é normalizada, um viés estável se cancela; um que muda ao longo do tempo, não.
- **Lucro total, não por ação.** Emissões e recompras mudam o lucro total sem mudar o lucro por
  ação — e o índice, do outro lado da razão, é por ação.

Corrigido em 26/09/2026 (ver `ESTADO.md`): o lucro de 12 meses do trecho trimestral deixava o
4º trimestre de fora, e lucro exatamente zero (DRE consolidada vazia) entrava como zero.

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
