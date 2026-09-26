# Estado de validacao

Registro honesto do que ja foi exercitado contra a realidade e do que ainda nao.
Atualizado em 26/09/2026.

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
| Testes de calculo | 116 testes passam no runner (`pytest tests -q`) |
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
