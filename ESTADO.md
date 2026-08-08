# Estado de validacao

Registro honesto do que ja foi exercitado contra a realidade e do que ainda nao.
Atualizado em 08/08/2026, apos tres execucoes reais do workflow.

## O que esta comprovadamente funcionando

| Componente | Evidencia |
|---|---|
| Testes de calculo | 22 testes passam no runner (`pytest tests -q`) |
| Orquestracao e diagnostico | `status.json` gerado, com estagio, situacao e detalhe por fonte |
| Renderizacao do dashboard | `docs/index.html` produzido mesmo com todas as fontes falhando |
| Degradacao explicita | Graficos vazios com a causa escrita; nenhum numero inventado |
| Artefato e Step Summary | Publicados a cada execucao |
| Portao final | Falha a execucao quando nenhuma fonte responde — comportamento correto |
| Agendamento | GitHub confirma: *"Runs at 12:00, only on Saturday"* = 9h BRT |

Em outras palavras: **o encanamento esta validado ponta a ponta**. O que falta
e agua.

## O que esta bloqueado

**Provedores de preco de indice recusam IPs de datacenter.**

| Execucao | Provedor | Resultado |
|---|---|---|
| #2 | Stooq | Pagina de bloqueio em vez de CSV (`colunas=['This site...']`) |
| #3 | Yahoo Finance chart v8 | `429 Client Error` apos 3 tentativas, para ambos os simbolos |

Os dois casos sao o mesmo fenomeno: a requisicao parte de um runner do GitHub
Actions, e ambos os provedores limitam ou bloqueiam faixas de nuvem. Rodando
localmente, de um IP residencial, a tendencia e funcionar.

Como os precos sao o primeiro estagio, a falha deles impede que os demais
rodem — as fontes de lucro (S&P DJI, Shiller, B3, CVM) **ainda nao foram
testadas contra a rede**. Elas podem funcionar perfeitamente; simplesmente
nao chegaram a ser chamadas.

## Caminhos para destravar

Em ordem de custo crescente:

1. **Rodar localmente.** `python -m src.build && python -m src.render` de uma
   maquina comum. Serve para validar de uma vez todas as fontes que ainda nao
   foram exercitadas, e para medir a cobertura real da conciliacao do Ibovespa.
2. **Chave gratuita de um provedor com API estavel** (Alpha Vantage, Tiingo,
   Twelve Data). Nenhum e pago no nivel de uso deste projeto. Entraria como
   terceiro provedor em `src/sources/prices.py`, com a chave em
   *Settings > Secrets and variables > Actions*.
3. **Self-hosted runner** em IP residencial. Resolve o bloqueio na raiz, mas
   e infraestrutura para manter.

A opcao 1 e a mais informativa e nao custa nada: revela de uma vez se as quatro
fontes de lucro respondem e qual a cobertura efetiva do portao do Ibovespa.

## O que NAO foi feito para "resolver" o bloqueio

Nao foi adicionado dado embutido, serie de exemplo, valor plausivel ou cache
commitado para que o dashboard "tivesse alguma coisa". Um dashboard vazio que
diz por que esta vazio e um resultado; um dashboard com numero de origem
desconhecida e um passivo.
