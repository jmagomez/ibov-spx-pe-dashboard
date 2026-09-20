# P/E do Ibovespa e do S&P 500 — série diária desde 2010

Pipeline reprodutível que constrói e publica, a cada pregão, a evolução do múltiplo
preço/lucro do **S&P 500** e do **Ibovespa** a partir de 01/01/2010, usando exclusivamente
fontes primárias e gratuitas.

**Atualização automática: de terça a sábado, às 9h (horário de Brasília), com resumo
por e-mail a cada execução.** Cada rodada fecha o pregão do dia anterior — terça cobre
segunda, sábado cobre sexta. Cinco execuções por semana, uma por pregão.

---

## Leia isto antes de olhar qualquer gráfico

Este repositório começa por uma restrição, e não por um resultado. A restrição determina
o que o projeto pode e o que não pode entregar — e ignorá-la levaria a comparar duas
coisas que não são comparáveis.

**Para o S&P 500, existe P/E em nível, e ele é confiável.** A S&P Dow Jones Indices,
administradora do índice, publica gratuitamente o lucro por ação agregado do índice,
trimestre a trimestre, em série longa. O P/E diário é o preço de fechamento dividido por
esse LPA acumulado em 12 meses. É a mesma construção usada por provedores de mercado.

**Para o Ibovespa, não existe equivalente gratuito.** Três lacunas simultâneas:

1. A B3 não publica, em formato aberto, o **histórico de composição** da carteira desde 2010.
   Só a carteira vigente está disponível.
2. A base de **ITR da CVM cobre apenas os últimos cinco anos**. Lucro trimestral brasileiro
   desde 2010 não está publicamente disponível — apenas o anual, via DFP.
3. Não há série pública de LPA agregado do Ibovespa análoga à da S&P DJI.

O que o projeto faz com isso: constrói um **índice de valuation normalizado (base 100)**
para o Ibovespa, com a carteira vigente e os lucros da CVM, declara o viés de sobrevivência,
marca qual trecho usa lucro anual e qual usa trimestral, e **suprime a série inteira** se a
conciliação entre carteira e demonstrações cobrir menos de 80% do peso do índice.

Comparar a linha do Ibovespa com a do S&P 500 **em nível** é um erro de leitura. O que é
comparável é direção, amplitude e posição de cada série na sua própria história.

Detalhamento completo em [`LIMITACOES.md`](LIMITACOES.md).

---

## O que é publicado

| Métrica | Índice | Construção |
|---|---|---|
| P/E trailing 12m | S&P 500 | Preço ÷ LPA as-reported 12m (S&P DJI) |
| P/E trailing point-in-time | S&P 500 | Idem, com defasagem de 75 dias de divulgação |
| P/E operating | S&P 500 | Idem, com LPA operating |
| CAPE (Shiller P/E) | S&P 500 | Planilha `ie_data` de Robert Shiller |
| Earnings yield | S&P 500 | 1 ÷ (P/E), em % a.a. |
| Z-score e percentil | ambos | Janela móvel de 10 anos contra a própria distribuição |
| Índice de valuation (base 100) | Ibovespa | Preço do índice ÷ lucro agregado das componentes, normalizado |
| Carteira vigente | Ibovespa | Composição atual da B3, 30 maiores pesos |

Todas as séries em `data/processed/`, em CSV, com a mesma granularidade do gráfico.

---

## Regra que governa o código

> Se a fonte não respondeu, o número não existe.

Não há, em nenhum ponto do pipeline, valor default, média de preenchimento, interpolação
de lucro, último valor conhecido travado ou estimativa de consenso entrando em série
rotulada como histórica. Um gráfico vazio com a causa escrita é um resultado aceitável.
Um gráfico preenchido por conveniência, não.

Isso é aplicado em três camadas:

- `src/sources/http.py` levanta exceção em vez de devolver conteúdo parcial;
- `src/metrics.py` propaga `NaN` em vez de preencher (`ttm_from_quarterly` exige quatro
  trimestres completos; `pe_ratio` devolve `NaN` quando o lucro agregado é ≤ 0);
- `src/build.py` aplica o portão de cobertura e suprime a série do Ibovespa abaixo do limite.

Além disso, a planilha da S&P DJI contém trimestres **futuros com estimativa de consenso**.
O coletor os remove explicitamente: misturar projeção em série histórica é exatamente o tipo
de contaminação que o projeto existe para evitar.

---

## Estrutura

```
src/
  config.py            parâmetros, URLs e convenções de cálculo
  metrics.py           funções puras de cálculo — sem I/O, 100% testáveis offline
  build.py             orquestração, portões de cobertura, diagnóstico
  render.py            geração do docs/index.html
  sources/
    http.py            camada HTTP única, com retry e falha explícita
    prices.py          fechamentos diários dos índices (yfinance, com Stooq de reserva)
    spdji.py           LPA trimestral do S&P 500 (S&P Dow Jones Indices)
    shiller.py         CAPE e LPA 12m (Robert Shiller, Yale) — escolhe o espelho
                       com o dado mais recente, não o primeiro que responder
    b3.py              composição vigente do Ibovespa (B3)
    cvm.py             lucro consolidado das companhias (CVM — DFP e ITR)
tools/
  summary.py           resumo da execução no Step Summary do Actions
  digest.py            resumo diário enviado por e-mail (HTML + texto)
  gate.py              falha a execução apenas se nenhuma fonte respondeu
tests/
  test_metrics.py      funções de cálculo
  test_espelho_shiller.py  escolha de espelho da ie_data — trava o defeito de 2024
  test_digest.py       o resumo diário não publica número vencido como se fosse do dia
docs/index.html        dashboard estático
data/processed/        séries publicadas + status.json com o diagnóstico
```

---

## Como rodar localmente

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest tests -q          # testa a aritmética, sem rede
python -m src.build      # coleta e processa
python -m src.render     # gera docs/index.html
```

## Rotina diária e e-mail

A cada execução, `tools/digest.py` lê o que o pipeline acabou de publicar e escreve
`data/processed/digest.html`, `digest.txt` e `digest_assunto.txt`. O workflow envia esse
conteúdo por SMTP do Gmail.

O e-mail tem duas partes, e a separação é deliberada:

- **O que mudou desde a execução anterior** — estágio que passou a falhar ou voltou a
  funcionar, fonte que venceu, série que ficou sem valor publicável, percentil que cruzou
  as faixas de 20 ou 80. Nada disso é sinal de compra ou venda; é mudança de estado do
  próprio pipeline ou da posição da série na sua distribuição.
- **O estado corrente** — os números do dia, a variação contra a observação anterior da
  própria série e o diagnóstico da coleta.

A comparação é feita contra `data/processed/digest_estado.json`, versionado junto com os
dados. É o que impede o resumo de repetir todo dia o mesmo aviso: um problema que já foi
comunicado ontem não volta ao topo hoje — ele continua listado abaixo, entre os avisos do
pipeline, mas deixa de ser novidade. Um resumo que grita todo dia deixa de ser lido, e o
dia em que ele teria algo novo a dizer é justamente o dia em que ninguém abre.

### Configuração do envio

Em *Settings → Secrets and variables → Actions*:

| Secret | Conteúdo |
|---|---|
| `MAIL_USERNAME` | endereço Gmail remetente |
| `MAIL_PASSWORD` | **senha de app** do Gmail, não a senha da conta |
| `MAIL_TO` | destinatário (opcional; sem ele, envia para o próprio remetente) |

Sem `MAIL_USERNAME` configurado o passo de envio é **pulado**, não falha — um fork sem
credencial continua rodando o pipeline inteiro. Em execução manual (*workflow_dispatch*)
o envio é opt-in, pelo campo `enviar_email`: rodar o pipeline no meio da tarde para testar
não dispara e-mail de fechamento.

## Publicação do dashboard

O workflow grava `docs/index.html` no próprio repositório. Para servir por GitHub Pages:
**Settings → Pages → Source: Deploy from a branch → Branch: `main` / pasta `/docs`**.
O dashboard também sai como artefato de cada execução, em *Actions → dashboard-e-dados*.

## Estado de validação

Os coletores já foram exercitados contra os endpoints reais e os nove estágios respondem
no runner. O detalhe por fonte, incluindo o que já quebrou e como, está em
[`ESTADO.md`](ESTADO.md).

Um caso vale destaque aqui porque muda como se lê o painel de diagnóstico: por cerca de
dois anos o P/E do S&P 500 ficou vazio no trecho final com **todas as fontes marcadas
`ok`**. A URL da planilha de Shiller apontava para um endereço antigo que continua
respondendo HTTP 200 e continua entregando um arquivo íntegro — congelado em 2024. Status
200 e arquivo bem-formado não são evidência de dado atualizado. Desde a correção, a
escolha entre espelhos é pela **data da última observação dentro do arquivo**, e a tabela
"Validade da última observação de cada fonte", no dashboard, existe para tornar isso
visível sem precisar abrir o `status.json`.

---

## Aviso

Material informativo e educacional. Não é recomendação de investimento, análise de valores
mobiliários na acepção regulatória, nem oferta de qualquer natureza. Múltiplos de valuation
não são sinal de compra ou venda — ver a seção "O que estas séries não permitem concluir"
em [`LIMITACOES.md`](LIMITACOES.md).

Licença MIT. Os dados pertencem às respectivas fontes e estão sujeitos aos termos delas.
