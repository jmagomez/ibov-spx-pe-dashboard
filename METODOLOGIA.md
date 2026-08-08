# Metodologia

## 1. Definição da métrica

O múltiplo preço/lucro de um índice é, por construção:

```
P/E_índice = Σ(preço_i × quantidade_i) / Σ(LPA_i × quantidade_i)
```

isto é, a capitalização agregada dos componentes dividida pelo lucro agregado dos mesmos
componentes, com os mesmos pesos. É um múltiplo **ponderado por capitalização**, não a média
dos P/E individuais. A distinção não é acadêmica: a média simples dos P/E de 500 empresas é
dominada por casos de lucro próximo de zero, que produzem P/E arbitrariamente grandes, e não
descreve o índice. Todos os provedores relevantes usam a forma agregada acima.

## 2. S&P 500 — P/E em nível

**Numerador.** Fechamento diário do índice.

**Denominador.** LPA do índice acumulado em 12 meses, obtido da planilha *S&P 500 Earnings
and Estimate Report*, publicada pela S&P Dow Jones Indices — a própria administradora do
índice. Usa-se a soma móvel de quatro trimestres consecutivos. **Trimestre faltante não é
preenchido**: a janela exige as quatro observações, e o resultado é `NaN` caso contrário.

**As-reported como série principal.** A planilha traz LPA *as reported* (GAAP) e *operating*.
A série principal é a as-reported, porque o LPA operating exclui itens a critério das
companhias e do provedor, e essas exclusões são sistematicamente assimétricas: despesas
extraordinárias são excluídas com muito mais frequência do que receitas extraordinárias.
O resultado é um denominador estruturalmente maior e um P/E estruturalmente menor. O
operating é publicado como série secundária, para que a diferença seja visível em vez de
escondida na escolha de fonte.

**Remoção de estimativas.** A planilha inclui trimestres futuros com consenso de analistas.
São descartados. Uma série rotulada como histórica não pode conter projeção.

### 2.1 Convenção de índice versus point-in-time

Este é o ponto metodológico mais frequentemente ignorado em séries de P/E.

Provedores de índice datam o lucro de um trimestre pelo **fim do trimestre**. Assim, o P/E
de 30/06 usa no denominador o lucro do 2º trimestre — que naquela data ainda não havia sido
divulgado por praticamente nenhuma companhia. A série resultante é internamente consistente
e comparável ao que o mercado publica, mas **não é observável em tempo real**: ela embute
informação futura.

O pipeline gera as duas versões:

| Série | `lag` | Significado |
|---|---|---|
| `pe` | 0 dia | Convenção de índice. Comparável ao P/E divulgado pelo mercado. |
| `pe_pit` | 75 dias | Point-in-time. O lucro só entra depois de plausivelmente divulgado. |

75 dias cobrem com folga o prazo regulatório brasileiro de ITR (45 dias) e o ciclo típico de
reporte nos EUA. A distância entre as duas linhas mede exatamente **quanta informação futura
a convenção de índice antecipa** — e ela é maior justamente nas viradas de ciclo, que é
quando a leitura do múltiplo mais importa. Qualquer backtest construído sobre a série de
convenção de índice tem viés de antecipação (*look-ahead bias*).

## 3. CAPE e earnings yield

**CAPE** (*cyclically adjusted P/E*): preço real dividido pela média móvel de 10 anos do
lucro real. Vem da planilha `ie_data` de Robert Shiller. Existe no dashboard porque o P/E
trailing tem uma patologia conhecida: em recessão o denominador colapsa mais rápido que o
preço, e o múltiplo **sobe** no exato momento em que o mercado ficou mais barato. O CAPE
suaviza isso. Em contrapartida, tem críticas próprias — mudanças de norma contábil ao longo
de 10 anos, e a discussão sobre se sua média de longo prazo ainda é referência válida.
Nenhuma das duas métricas é suficiente sozinha.

**Earnings yield** = 1 ÷ (P/E), em % a.a. É a forma comparável a taxa de juros. "P/E de 22"
não responde a "caro em relação a quê"; "earnings yield de 4,5% contra um título de 10 anos
a X%" responde. O dashboard publica o earnings yield, mas **não** calcula prêmio de risco:
isso exigiria uma série de juro real de cada mercado que não está nas fontes deste projeto,
e estimá-la seria inventar número.

## 4. Ibovespa — índice de valuation, e por que não é P/E

Aqui o projeto não consegue entregar P/E em nível, e é importante ser explícito sobre onde
exatamente a construção quebra.

**O que se tem.** Fechamento diário do Ibovespa; carteira vigente com quantidade teórica e
participação; lucro líquido consolidado por companhia, da CVM (DFP anual desde 2010; ITR
trimestral apenas nos últimos cinco anos).

**O que falta.** O redutor histórico do índice e a composição histórica. Sem eles não é
possível reconstruir `Σ(preço_i × quantidade_i)` no passado, que é o numerador correto.

**O que se faz.** Calcula-se a razão entre o nível do índice e o lucro agregado das
componentes conciliadas, e ela é **normalizada para 100 na primeira data válida**. As duas
grandezas têm escalas diferentes — o índice é uma média ponderada com redutor; o agregado é
lucro em reais — de modo que o **nível** da razão não tem significado. A **variação** tem:
a mesma razão, medida de forma consistente ao longo do tempo, informa se o mercado está
pagando mais ou menos por unidade de lucro do que pagava antes.

Daí a rotulagem "índice de valuation (base 100)" em vez de "P/E". A diferença de nomenclatura
não é preciosismo: um número rotulado como P/E é comparado, por reflexo, com o P/E do S&P 500,
e essa comparação seria inválida.

**Emenda anual/trimestral.** O trecho anterior à cobertura do ITR usa lucro anual em degrau;
o trecho recente usa soma móvel de quatro trimestres. Cada observação carrega a marca da
frequência de origem (`freq_lucro`). O trecho anual tem resolução muito menor e reage às
viradas de ciclo com atraso de até um ano.

**Defasagem.** A série do Ibovespa usa exclusivamente a convenção point-in-time (75 dias).
Não faria sentido oferecer a convenção de índice para uma construção que já é aproximada.

## 5. Portão de cobertura

A conciliação entre a carteira da B3 e as companhias da CVM é feita por razão social
normalizada — sem acento, sem sufixo societário, com correspondência por prefixo como
segunda tentativa. É um casamento imperfeito por natureza: não existe, em fonte aberta,
tabela de-para entre ticker da B3 e código CVM.

Por isso o pipeline mede a **cobertura por peso**: a soma da participação no índice dos
ativos efetivamente conciliados. Se ficar abaixo de **80%**, a série do Ibovespa é
**suprimida inteira**, e o motivo aparece no dashboard.

O raciocínio: um agregado que deixa de fora 30% do peso do índice não é o lucro do Ibovespa
— é o lucro de um subconjunto arbitrário dele, e a razão calculada sobre isso não mede o que
o rótulo diz medir. Publicar com ressalva em nota de rodapé seria pior que não publicar,
porque o gráfico é lido e a nota não.

## 6. Estatísticas de posição

**Z-score** e **percentil** são calculados contra janela móvel de 2.520 pregões (~10 anos),
com mínimo de metade da janela. Servem para responder "onde este múltiplo está em relação à
sua própria história recente", que é uma pergunta melhor que "o múltiplo está alto".

Limitação incontornável: a janela de 10 anos sobre uma série que começa em 2010 significa
que o percentil só passa a existir por volta de 2015, e que ele é medido contra um período
histórico específico — juros baixos, expansão de múltiplos, uma pandemia. Um percentil de
90 não significa "caro em termos absolutos"; significa "alto em relação a estes 10 anos".

## 7. Decomposição preço = múltiplo × lucro

`metrics.decompose_price_change` separa a variação do preço em contribuição do lucro e
contribuição do múltiplo, usando logaritmos:

```
ln(P_t / P_t-n) = ln(PE_t / PE_t-n) + ln(E_t / E_t-n)
```

A identidade em log é **exatamente aditiva**, sem termo cruzado — motivo pelo qual é usada
aqui em vez da versão em variação percentual simples, que deixa resíduo. Um teste unitário
verifica que o resíduo é numericamente zero.

A leitura é o ponto: uma alta de índice puxada por expansão de múltiplo tem natureza
diferente de uma alta puxada por crescimento de lucro, e o gráfico de preço não distingue as
duas.

## 8. Reprodutibilidade

Versões travadas em `requirements.txt`. Funções de cálculo isoladas de I/O em `src/metrics.py`
e cobertas por testes que rodam sem rede. Cada execução grava `data/processed/status.json`
com o estado de cada fonte, a contagem de observações e o período coberto — de modo que
qualquer gráfico pode ser auditado contra o que a coleta efetivamente obteve naquele dia.
