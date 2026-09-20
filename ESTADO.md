# Estado de validacao

Registro honesto do que ja foi exercitado contra a realidade e do que ainda nao.
Atualizado em 20/09/2026.

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
| Testes de calculo | 88 testes passam no runner (`pytest tests -q`) |
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
