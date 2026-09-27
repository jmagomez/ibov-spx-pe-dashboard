"""Gera docs/index.html a partir de data/processed/.

O dashboard so plota o que existe em disco. Se um estagio falhou, o painel de
diagnostico mostra a falha e o grafico correspondente aparece vazio, com a
razao escrita. Nao ha placeholder numerico em lugar nenhum.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pandas as pd

from .config import DOCS, PROCESSED, RAW_BASE

log = logging.getLogger("render")

# Amostragem para o grafico: manter todos os pregoes desde 2010 gera um JSON
# grande sem ganho visual. Amostrar preserva a forma da serie; o CSV completo
# continua disponivel para quem quiser o dado bruto.
PASSO_PLOT = 3


# Buraco maior que isto (dias corridos) entre dois pontos plotados e lacuna de
# dado, nao fim de semana nem amostragem: o grafico precisa interromper a linha.
LACUNA_DIAS = 15


def _serie(df: pd.DataFrame, col: str) -> list:
    """Pontos [data, valor] para o grafico, com [data, None] onde a serie some.

    Sem o None, o Chart.js liga o ultimo ponto antes do buraco ao primeiro
    depois dele, e o trecho sem dado vira uma reta que parece dado. Foi o que
    aconteceu com o P/L do Ibovespa em 2016: com lucro agregado negativo, o P/L
    nao existe por oito meses, e o grafico desenhava uma rampa de 50x a 126x.
    """
    if df.empty or col not in df.columns:
        return []
    s = df[col].dropna().iloc[::PASSO_PLOT]
    out = []
    anterior = None
    for d, v in s.items():
        if anterior is not None and (d - anterior).days > LACUNA_DIAS:
            out.append([(anterior + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), None])
        out.append([d.strftime("%Y-%m-%d"), round(float(v), 4)])
        anterior = d
    return out


def _load(nome: str) -> pd.DataFrame:
    p = PROCESSED / nome
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, parse_dates=["data"]).set_index("data")


def main() -> int:
    DOCS.mkdir(parents=True, exist_ok=True)
    spx, ibov = _load("spx.csv"), _load("ibov.csv")
    comp_path = PROCESSED / "ibov_composicao.csv"
    comp = pd.read_csv(comp_path) if comp_path.exists() else pd.DataFrame()
    st_path = PROCESSED / "status.json"
    status = json.loads(st_path.read_text(encoding="utf-8")) if st_path.exists() else {}

    ultimo_pregao = max([d.index.max() for d in (spx, ibov) if not d.empty],
                        default=pd.NaT)

    dados = {
        "spx_pe": _serie(spx, "pe"),
        "spx_pe_pit": _serie(spx, "pe_pit"),
        "spx_pe_operating": _serie(spx, "pe_operating"),
        "spx_cape": _serie(spx, "cape"),
        "spx_ey": _serie(spx, "earnings_yield"),
        "spx_z": _serie(spx, "pe_z"),
        "spx_pct": _serie(spx, "pe_pct"),
        "ibov_val": _serie(ibov, "valuation_idx"),
        "ibov_z": _serie(ibov, "valuation_z"),
        "ibov_pct": _serie(ibov, "valuation_pct"),
        "ibov_preco": _serie(ibov, "preco"),
        "spx_preco": _serie(spx, "preco"),
        "ust10": _serie(spx, "ust10"),
        "tips10": _serie(spx, "tips10"),
        "cape_yield": _serie(spx, "cape_yield"),
        "ey_menos_real": _serie(spx, "ey_menos_real"),
        "cape_yield_menos_real": _serie(spx, "cape_yield_menos_real"),
        "eps_yoy": _serie(spx, "eps_yoy_pct"),
        "ibov_pl": _serie(ibov, "pl_nivel"),
        "ibov_pl_pct": _serie(ibov, "pl_nivel_pct"),
        "ibov_pl_z": _serie(ibov, "pl_nivel_z"),
    }

    def _ult(df: pd.DataFrame, col: str):
        """Ultimo valor da serie, com variacao e IDADE.

        A idade e o campo que faltava, e a ausencia dela era um defeito de
        leitura, nao de estilo: sob o titulo "Situacao atual" o cartao exibia,
        em letra garrafal, o P/E de junho de 2024 -- ultimo valor com lastro --
        com a data verdadeira em cinza, 11px, embaixo. Quem bate o olho le o
        numero grande. Agora o cartao diz na propria cara quantos dias tem o
        numero, e se marca como vencido quando a serie parou de andar.
        """
        if df.empty or col not in df.columns:
            return None
        s = df[col].dropna()
        if s.empty:
            return None
        atual = float(s.iloc[-1])
        anterior = float(s.iloc[-2]) if len(s) > 1 else None
        data = s.index[-1]
        idade = int((ultimo_pregao - data).days) if pd.notna(ultimo_pregao) else 0
        return {
            "data": data.strftime("%d/%m/%Y"),
            "valor": round(atual, 2),
            "delta": round(atual - anterior, 2) if anterior is not None else None,
            "delta_pct": (round((atual / anterior - 1) * 100, 2)
                          if anterior not in (None, 0) else None),
            "idade_dias": idade,
            # 7 dias cobre feriado prolongado em qualquer das duas pracas. Acima
            # disso a serie nao e "de hoje", e o cartao para de fingir que e.
            "vencido": idade > 7,
        }

    cartoes = {
        "spx_pe": _ult(spx, "pe"),
        "spx_cape": _ult(spx, "cape"),
        "spx_ey": _ult(spx, "earnings_yield"),
        "spx_pct": _ult(spx, "pe_pct"),
        "ibov_val": _ult(ibov, "valuation_idx"),
        "ibov_pct": _ult(ibov, "valuation_pct"),
        "eps_yoy": _ult(spx, "eps_yoy_pct"),
        "ey_menos_real": _ult(spx, "ey_menos_real"),
        "cape_yield_menos_real": _ult(spx, "cape_yield_menos_real"),
        "ibov_pl": _ult(ibov, "pl_nivel"),
        "ibov_pl_pct": _ult(ibov, "pl_nivel_pct"),
    }
    # Sem a serie por papel, o cartao do P/L do Ibovespa ainda pode vir do
    # calculo pelo redutor da B3 (so a data da carteira, sem historico).
    pl = status.get("pl_ibov") or {}
    if cartoes["ibov_pl"] is None and isinstance(pl.get("pl"), (int, float)) and pl["pl"] == pl["pl"]:
        d = pd.Timestamp(pl["data"])
        cartoes["ibov_pl"] = {"data": d.strftime("%d/%m/%Y"), "valor": round(pl["pl"], 2),
                              "delta": None, "delta_pct": None, "idade_dias": 0,
                              "vencido": False}

    emp_path = PROCESSED / "ibov_pl_empresas.csv"
    pl_emp = []
    if emp_path.exists():
        e = pd.read_csv(emp_path)
        e = e.sort_values("peso_pct", ascending=False).head(20)
        for r in e.itertuples():
            pl_emp.append([r.codigos, round(float(r.peso_pct), 3),
                           None if pd.isna(r.f) else round(float(r.f), 3),
                           None if pd.isna(r.lucro_12m) else round(float(r.lucro_12m) / 1e9, 2),
                           None if pd.isna(r.pl_implicito) else round(float(r.pl_implicito), 1),
                           str(r.motivo_exclusao) if isinstance(r.motivo_exclusao, str) else ""])

    comp_rows = []
    if not comp.empty:
        cols = [c for c in ("codigo", "empresa", "tipo", "participacao_pct")
                if c in comp.columns]
        d = comp[cols]
        if "participacao_pct" in d.columns:
            d = d.sort_values("participacao_pct", ascending=False)
        comp_rows = d.head(30).fillna("").values.tolist()

    html = TEMPLATE.replace("__DADOS__", json.dumps(dados))
    html = html.replace("__CARTOES__", json.dumps(cartoes, ensure_ascii=False))
    html = html.replace("__STATUS__", json.dumps(status, ensure_ascii=False))
    html = html.replace("__COMPOSICAO__", json.dumps(comp_rows, ensure_ascii=False))
    html = html.replace("__PLEMP__", json.dumps(pl_emp, ensure_ascii=False))
    html = html.replace("__GERADO__",
                        datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"))
    html = html.replace("__RAW__", RAW_BASE)
    # "Gerado em" e a hora do job; "dados ate" e a ultima data com numero. Sao
    # coisas diferentes e confundi-las e o jeito mais facil de olhar um painel
    # parado e achar que esta atualizado, porque o rodape mudou de hora.
    html = html.replace("__DADOS_ATE__",
                        ultimo_pregao.strftime("%d/%m/%Y") if pd.notna(ultimo_pregao)
                        else "sem dados")
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    log.info("docs/index.html gerado")
    return 0


TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>P/E Ibovespa x S&P 500 - desde 2010</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/luxon@3.4.4/build/global/luxon.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-luxon@1.3.1/dist/chartjs-adapter-luxon.umd.min.js"></script>
<style>
:root{--navy:#0E2A3B;--navy2:#11324A;--teal:#1C7293;--deep:#065A82;--gold:#E0A458;
--tint:#EAF1F5;--line:#DCE6EB;--gray:#6E8087;--ink:#1E2933;--bad:#B4442E;--ok:#2E7D52;}
*{box-sizing:border-box}
body{margin:0;font:15px/1.55 "Segoe UI",Calibri,system-ui,sans-serif;color:var(--ink);background:#fff}
header{background:var(--navy);color:#fff;padding:28px 32px}
header h1{margin:0 0 6px;font-size:26px;letter-spacing:-.2px}
header p{margin:0;color:#CADCEC;font-size:14px;max-width:960px}
.wrap{max-width:1280px;margin:0 auto;padding:24px 32px 64px}
h2{font-size:18px;margin:34px 0 12px;color:var(--navy2)}
.alert{border:1px solid var(--gold);background:#FDF6EC;border-radius:6px;padding:14px 18px;margin:20px 0;font-size:13.5px}
.alert b{color:var(--navy2)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:18px 0}
.card{border:1px solid var(--line);border-radius:6px;padding:14px 16px;background:#fff}
.card .lbl{font-size:11.5px;text-transform:uppercase;letter-spacing:.6px;color:var(--gray)}
.card .val{font-size:27px;font-weight:700;color:var(--deep);margin:4px 0 2px}
.card .dt{font-size:11.5px;color:var(--gray)}
.card .na{font-size:15px;font-weight:600;color:var(--bad);margin:8px 0 2px}
.card .delta{font-size:12.5px;font-weight:600;margin-left:7px;vertical-align:3px}
.card .delta.up{color:var(--ok)} .card .delta.down{color:var(--bad)}
.card .delta.flat{color:var(--gray)}
/* Valor sem lastro recente nao pode ter a mesma aparencia de valor de hoje. */
.card.stale{border-color:var(--gold);background:#FDF9F2}
.card.stale .val{color:var(--gray)}
.card .stale-tag{display:inline-block;margin-top:6px;padding:2px 8px;border-radius:11px;
  background:#F6E7CE;color:#8A5A12;font-size:11px;font-weight:600}
.chartbox{border:1px solid var(--line);border-radius:6px;padding:16px;margin:14px 0;background:#fff}
.chartbox h3{margin:0 0 2px;font-size:15px;color:var(--navy2)}
.chartbox .sub{margin:0 0 12px;font-size:12.5px;color:var(--gray)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
canvas{max-height:330px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}
th{background:var(--tint);color:var(--navy2);font-weight:600}
td.num,th.num{text-align:right}
.pill{display:inline-block;padding:2px 9px;border-radius:11px;font-size:11.5px;font-weight:600}
.pill.ok{background:#E4F2EA;color:var(--ok)}
.pill.fail{background:#FBE9E5;color:var(--bad)}
.empty{padding:34px 14px;text-align:center;color:var(--gray);font-size:13.5px;background:var(--tint);border-radius:5px}
footer{border-top:1px solid var(--line);margin-top:40px;padding-top:16px;font-size:12px;color:var(--gray)}
a{color:var(--deep)}
code{background:var(--tint);padding:1px 5px;border-radius:3px;font-size:12.5px}
</style>
</head>
<body>
<header>
  <h1>P/E do Ibovespa e do S&amp;P 500 - base diaria desde 2010</h1>
  <p>Pipeline reprodutivel, fontes primarias e nenhum numero estimado. Onde a fonte nao cobre o periodo,
     a serie fica vazia em vez de preenchida. Metodologia, limitacoes e referencias no repositorio.</p>
  <p style="margin-top:10px;color:#8FB7D4;font-size:13px">
     Dados ate <b style="color:#fff">__DADOS_ATE__</b> &middot; execucao de __GERADO__</p>
</header>
<div class="wrap">

<div class="alert">
  <b>Leia antes de usar.</b> As duas series nao sao diretamente comparaveis em nivel.
  O S&amp;P 500 tem P/E em nivel verdadeiro, calculado com o LPA contabil (GAAP, "as reported") do
  indice: o da S&amp;P Dow Jones Indices quando ela responde, e o da planilha de Shiller -- mesma
  linhagem -- quando nao; o painel de diagnostico diz qual foi usado. O Ibovespa nao tem serie
  publica de LPA do indice: o P/L dele e calculado aqui, com a <i>carteira vigente</i> da B3
  (quantidade teorica de cada papel) e o lucro de 12 meses de cada companhia na CVM. O valor de hoje e
  o P/L da carteira de hoje; o historico e o P/L que <i>esta</i> carteira teria tido, e nao o do indice
  na epoca (vies de sobrevivencia). Mesmo em nivel, comparar os dois P/L e fragil: setores, contabilidade
  (IFRS x US GAAP) e moeda explicam boa parte da diferenca. Ver <code>METODOLOGIA.md</code> e
  <code>LIMITACOES.md</code>.
</div>

<h2>Situacao atual</h2>
<div class="cards" id="cards"></div>

<h2>S&amp;P 500 - P/E em nivel</h2>
<div class="chartbox">
  <h3>P/E trailing 12 meses</h3>
  <p class="sub">Preco de fechamento dividido pelo LPA contabil (GAAP) acumulado em 12 meses.
     A linha tracejada aplica defasagem de 75 dias entre o fim do trimestre e a data em que o lucro
     era efetivamente conhecido - a diferenca entre as duas e o quanto a convencao de indice antecipa informacao.
     <b>Nao e o P/E que a imprensa cita.</b> O numero de manchete costuma ser o P/E <i>projetado</i>
     (preco sobre o lucro esperado para os proximos 12 meses), mais baixo sempre que se espera
     crescimento de lucro. E o LPA GAAP inclui itens nao recorrentes: quando eles sao ganhos -- como a
     marcacao a mercado de participacoes em empresas de IA em 2025-26 --, o P/E daqui fica
     <i>abaixo</i> do que seria sobre lucro recorrente. Ver <code>LIMITACOES.md</code>, secao 9.</p>
  <div id="w-spxpe"><canvas id="c-spxpe"></canvas></div>
</div>
<div class="grid2">
  <div class="chartbox">
    <h3>CAPE (Shiller P/E)</h3>
    <p class="sub">Lucro real medio de 10 anos no denominador. Imune ao colapso mecanico do
       lucro em recessao, que e o que distorce o P/E trailing justamente no fundo do ciclo.</p>
    <div id="w-cape"><canvas id="c-cape"></canvas></div>
  </div>
  <div class="chartbox">
    <h3>Earnings yield (% a.a.)</h3>
    <p class="sub">Inverso do P/E. E a forma comparavel a juros - e a unica em que
       a pergunta "caro em relacao a que?" tem resposta.</p>
    <div id="w-ey"><canvas id="c-ey"></canvas></div>
  </div>
</div>
<div class="chartbox">
  <h3>Posicao do P/E na propria historia (percentil, janela de 10 anos)</h3>
  <p class="sub">Percentil contra a propria distribuicao. Nivel absoluto de P/E diz pouco;
     posicao relativa ao proprio historico diz mais - e ainda assim nao e sinal de compra ou venda.</p>
  <div id="w-pct"><canvas id="c-pct"></canvas></div>
</div>

<h2>Caro em relacao a que? O rendimento do lucro contra os juros</h2>
<div class="chartbox">
  <h3>Rendimento do lucro (1/P/E e 1/CAPE) e juros de 10 anos dos EUA, % a.a.</h3>
  <p class="sub">O lucro de uma empresa cresce com a inflacao; por isso o comparavel ao rendimento
     do lucro e o juro <i>real</i> (TIPS), e nao o nominal. Quando 1/CAPE - o rendimento do lucro
     medio de 10 anos - fica abaixo do TIPS, o investidor recebe menos de lucro normalizado por
     dolar aplicado em acoes do que recebe, sem risco de credito e protegido da inflacao, em
     titulo do Tesouro. Fonte dos juros: FRED (DGS10 e DFII10) ou, se ele nao responder, o CSV
     diario do proprio Tesouro dos EUA -- o diagnostico diz qual foi usado.</p>
  <div id="w-juros"><canvas id="c-juros"></canvas></div>
</div>
<div class="chartbox">
  <h3>Premio do rendimento do lucro sobre o juro real de 10 anos, pontos percentuais</h3>
  <p class="sub">Proxy grosseira do premio de risco de acoes: nao desconta crescimento esperado nem
     recompras, e usa lucro contabil. Serve para ler <b>direcao e nivel relativo</b>. Abaixo de
     zero, o lucro normalizado rende menos que o titulo real sem risco. A posicao do valor atual
     dentro da propria serie (desde 2010) esta na tabela de historia longa, logo abaixo.</p>
  <div id="w-premio"><canvas id="c-premio"></canvas></div>
</div>

<h2>Posicao na historia longa (planilha de Shiller)</h2>
<p style="font-size:13.5px;color:var(--gray);margin-top:-4px">
  O percentil dos cartoes e dos graficos acima e medido contra os ultimos 10 anos - uma decada
  que foi, ela propria, das mais caras ja registradas. Esta tabela mede contra toda a historia
  disponivel. 150 anos de lucro nao sao homogeneos (norma contabil, payout, setores mudaram), entao
  o percentil longo mede distancia da historia; nao prova reversao a ela.</p>
<table id="t-hist"><thead><tr>
  <th>Metrica</th><th class="num">Atual</th><th class="num">Percentil</th><th class="num">Mediana</th>
  <th class="num">Faixa p10-p90</th><th class="num">Maximo</th><th>Serie</th>
</tr></thead><tbody></tbody></table>

<h2>Ibovespa - P/L em nivel (carteira vigente)</h2>
<div class="chartbox">
  <h3>P/L trailing 12 meses da carteira atual do Ibovespa</h3>
  <p class="sub">soma(quantidade teorica x preco) / soma(fracao da companhia no indice x lucro de 12 meses
     atribuivel a controladora). A fracao e a quantidade teorica da B3 sobre as acoes em circulacao da
     CVM: o indice carrega so parte de cada companhia, e o lucro entra na mesma proporcao. Lucro
     point-in-time (75 dias apos o trimestre, 92 apos o exercicio). O historico mantem a carteira de
     hoje congelada: e o P/L que ela teria tido, nao o do indice na epoca. Preco dos papeis: yfinance.
     Escala logaritmica: quando o lucro agregado se aproxima de zero o P/L explode (~140x entre 12/2016
     e 03/2017, apos as baixas de Petrobras e Vale no 4T15), e com lucro negativo (04/2016 a meados de 12/2016) ele
     nao existe - o grafico fica vazio.</p>
  <p class="sub" id="pl-b3"></p>
  <div id="w-ibov"><canvas id="c-ibov"></canvas></div>
</div>
<div class="chartbox">
  <h3>Posicao do P/L na propria historia (z-score, janela de 10 anos)</h3>
  <p class="sub">Calculado sobre o rendimento de lucro (L/P), com o sinal invertido: positivo = mais caro
     que a media de 10 anos. Sobre o proprio P/L o z-score nao serve - os meses de lucro perto de zero
     levam a media a ~18x e o desvio-padrao a ~22x (09/2026). O percentil (cartao e grafico comparativo) usa o
     mesmo L/P, o que inclui os meses de prejuizo como os mais caros da janela. Zero e a media da
     janela; nao ha nivel "certo".</p>
  <div id="w-ibovz"><canvas id="c-ibovz"></canvas></div>
</div>
<h3 style="font-size:15px;color:var(--navy2);margin:22px 0 4px">De onde vem o lucro: as 20 maiores posicoes</h3>
<p style="font-size:13.5px;color:var(--gray);margin:0 0 10px">
  P/L implicito = valor da companhia na carteira (peso x indice x redutor) / (fracao x lucro de 12 meses).
  Serve para conferir o agregado contra o que se sabe de cada companhia. Lucro negativo entra na soma
  (reduz o denominador) e aparece sem P/L.</p>
<table id="t-plemp"><thead><tr>
  <th>Papeis</th><th class="num">Peso (%)</th><th class="num">Fracao no indice</th>
  <th class="num">Lucro 12m (R$ bi)</th><th class="num">P/L implicito</th><th>Observacao</th>
</tr></thead><tbody></tbody></table>
<div class="chartbox" style="margin-top:18px">
  <h3>Serie anterior: indice de valuation (base 100)</h3>
  <p class="sub">Preco do indice sobre o lucro TOTAL das companhias (sem ponderar pela fracao de cada uma
     no indice), normalizado em 100 na primeira data. Mantida para comparacao; o P/L em nivel acima a
     substitui.</p>
  <div id="w-ibovold"><canvas id="c-ibovold"></canvas></div>
</div>

<h2>A unica comparacao que os dois indices admitem</h2>
<div class="chartbox">
  <h3>Percentil de cada indice contra a propria historia (janela de 10 anos)</h3>
  <p class="sub">Aqui as duas linhas podem ficar no mesmo eixo, e so aqui. Nao se compara o
     P/E do S&amp;P com o indicador do Ibovespa - compara-se onde CADA UM esta dentro da
     propria distribuicao dos ultimos dez anos. Uma linha em 90 quer dizer "caro para o
     proprio padrao", nao "caro em relacao ao outro indice". As janelas podem comecar em
     datas diferentes, conforme o inicio de cada serie.</p>
  <div id="w-cmp"><canvas id="c-cmp"></canvas></div>
</div>

<h2>Diagnostico da coleta</h2>
<p style="font-size:13.5px;color:var(--gray);margin-top:-4px">
  Estado real de cada fonte na ultima execucao. Um estagio com falha significa grafico vazio,
  nunca grafico preenchido por estimativa.</p>
<table id="t-status"><thead><tr>
  <th>Estagio</th><th>Situacao</th><th class="num">Observacoes</th><th>Periodo</th><th>Detalhe</th>
</tr></thead><tbody></tbody></table>

<h3 style="font-size:15px;color:var(--navy2);margin:26px 0 4px">Validade da ultima observacao de cada fonte</h3>
<p style="font-size:13.5px;color:var(--gray);margin:0 0 10px">
  Uma fonte que para de ser atualizada nao muda de aparencia no grafico - a linha
  simplesmente continua. Esta tabela diz ate quando cada uma tem lastro.</p>
<table id="t-vig"><thead><tr>
  <th>Fonte</th><th>Ultima observacao</th><th>Vigente ate</th>
  <th class="num">Defasagem (dias)</th><th>Situacao</th>
</tr></thead><tbody></tbody></table>

<div id="avisos"></div>

<h2>Carteira vigente do Ibovespa (30 maiores pesos)</h2>
<p style="font-size:13.5px;color:var(--gray);margin-top:-4px">
  Composicao atual, obtida da B3. A B3 nao publica em formato aberto o historico de composicao
  desde 2010 - e essa ausencia que gera o vies de sobrevivencia descrito nas limitacoes.</p>
<table id="t-comp"><thead><tr>
  <th>Codigo</th><th>Empresa</th><th>Tipo</th><th class="num">Participacao (%)</th>
</tr></thead><tbody></tbody></table>

<h2>Dados brutos</h2>
<p style="font-size:13.5px;color:var(--gray);margin-top:-4px">
  Os CSVs tem a mesma granularidade dos graficos - nada foi agregado ou suavizado para a tela.
  O <code>status.json</code> e o diagnostico completo desta execucao, incluindo o que esta
  resumido acima.</p>
<p style="font-size:13.5px">
  <a href="__RAW__/spx.csv">spx.csv</a> &middot;
  <a href="__RAW__/ibov.csv">ibov.csv</a> &middot;
  <a href="__RAW__/comparativo.csv">comparativo.csv</a> &middot;
  <a href="__RAW__/ibov_composicao.csv">ibov_composicao.csv</a> &middot;
  <a href="__RAW__/ibov_pl_empresas.csv">ibov_pl_empresas.csv</a> &middot;
  <a href="__RAW__/ibov_conciliacao.csv">ibov_conciliacao.csv</a> &middot;
  <a href="__RAW__/status.json">status.json</a>
</p>

<footer>
  Execucao de __GERADO__ - dados ate __DADOS_ATE__ - atualizacao automatica em dias uteis,
  as 9h (BRT) - Este material e informativo e nao constitui recomendacao de investimento.
</footer>
</div>

<script>
const DADOS = __DADOS__;
const CARTOES = __CARTOES__;
const STATUS = __STATUS__;
const COMPOSICAO = __COMPOSICAO__;

const CSS = getComputedStyle(document.documentElement);
const c = n => CSS.getPropertyValue(n).trim();

function pts(arr){ return arr.map(([d,v]) => ({x:d, y:v})); }

// Chart.js vem de CDN. Se o CDN nao responder -- rede corporativa, leitura
// offline do artefato, bloqueio de dominio -- o `new Chart` levanta e, sem esta
// guarda, a excecao interrompe o script inteiro: some o diagnostico da coleta,
// some a carteira, some tudo o que e renderizado depois dos graficos. O painel
// sem grafico ainda e util; o painel em branco nao e.
const TEM_CHART = (typeof Chart !== 'undefined');

function aviso(wrapId, texto){
  const el = document.getElementById(wrapId);
  if (el) el.innerHTML = '<div class="empty">' + texto + '</div>';
}

function linha(canvasId, wrapId, series, opts){
  const vazio = series.every(s => !s.data || s.data.length === 0);
  if (vazio){
    aviso(wrapId, 'Sem dados publicaveis para este grafico nesta execucao.<br>' +
                  'Consulte o diagnostico da coleta abaixo para a causa.');
    return;
  }
  if (!TEM_CHART){
    aviso(wrapId, 'A biblioteca de graficos (Chart.js, via CDN) nao carregou.<br>' +
                  'Os dados existem e estao nos CSVs linkados no fim da pagina.');
    return;
  }
  try {
  new Chart(document.getElementById(canvasId), {
    type:'line',
    data:{ datasets: series.map(s => ({
      label:s.label, data:pts(s.data), borderColor:s.cor, backgroundColor:s.cor,
      borderWidth:s.w||1.6, borderDash:s.dash||[], pointRadius:0, tension:0,
      fill:false, spanGaps:false })) },
    options:{
      responsive:true, maintainAspectRatio:false, animation:false,
      interaction:{mode:'index', intersect:false},
      plugins:{
        legend:{display:series.length>1, labels:{boxWidth:12, font:{size:11.5}}},
        tooltip:{filter:x => x.parsed.y !== null && isFinite(x.parsed.y),
                 callbacks:{label:x => x.dataset.label + ': ' + Number(x.parsed.y).toFixed(2)}}
      },
      scales:{
        x:{type:'time', time:{unit:'year'}, grid:{display:false},
           ticks:{font:{size:11}, color:c('--gray')}},
        y:{type:(opts&&opts.log)?'logarithmic':'linear',
           grid:{color:c('--line')}, ticks:{font:{size:11}, color:c('--gray')},
           title:{display:!!(opts&&opts.y), text:(opts&&opts.y)||'',
                  font:{size:11}, color:c('--gray')}}
      }
    }
  });
  } catch (e) {
    aviso(wrapId, 'Falha ao desenhar este grafico: ' + e.message);
  }
}

const defs = [
  ['spx_pe','S&P 500 - P/E trailing',''],
  ['spx_cape','S&P 500 - CAPE',''],
  ['spx_ey','S&P 500 - Earnings yield','%'],
  ['spx_pct','S&P 500 - Percentil do P/E',''],
  (CARTOES.ibov_pl ? ['ibov_pl','Ibovespa - P/L 12m (carteira atual)','x']
                    : ['ibov_val','Ibovespa - Indice de valuation (base 100)','']),
  (CARTOES.ibov_pl_pct ? ['ibov_pl_pct','Ibovespa - Percentil do P/L (10a)','']
                       : ['ibov_pct','Ibovespa - Percentil','']),
  ['eps_yoy','S&P 500 - LPA 12m, variacao a/a','%'],
  ['ey_menos_real','Earnings yield - juro real 10a',' pp'],
  ['cape_yield_menos_real','1/CAPE - juro real 10a',' pp'],
];
// Sinais que o numero sozinho nao mostra. Nao sao alarme de compra/venda:
// sao avisos de LEITURA.
function aviso_cartao(k, v){
  if (k === 'eps_yoy' && Math.abs(v.valor) >= 20)
    return 'variacao atipica do lucro: conferir itens nao recorrentes';
  if ((k === 'ey_menos_real' || k === 'cape_yield_menos_real') && v.valor < 0)
    return 'lucro rende menos que o titulo real sem risco';
  return '';
}
function deltaHtml(v){
  if (v.delta === null || v.delta === undefined) return '';
  const cls = v.delta > 0 ? 'up' : (v.delta < 0 ? 'down' : 'flat');
  const sinal = v.delta > 0 ? '+' : '';
  const pct = (v.delta_pct === null || v.delta_pct === undefined)
      ? '' : ' ('+sinal+v.delta_pct.toFixed(2)+'%)';
  return '<span class="delta '+cls+'">'+sinal+v.delta.toFixed(2)+pct+'</span>';
}

document.getElementById('cards').innerHTML = defs.map(function(d){
  const k = d[0], lbl = d[1], suf = d[2];
  const v = CARTOES[k];
  if (!v){
    return '<div class="card"><div class="lbl">'+lbl+'</div>' +
      '<div class="na">indisponivel</div>' +
      '<div class="dt">fonte nao retornou dados</div></div>';
  }
  // A comparacao e com a observacao anterior DA PROPRIA SERIE, que nem sempre e
  // o pregao anterior: o CAPE e mensal. Por isso o rotulo diz "vs. anterior".
  return '<div class="card'+(v.vencido ? ' stale' : '')+'">' +
    '<div class="lbl">'+lbl+'</div>' +
    '<div class="val">'+v.valor+suf+deltaHtml(v)+'</div>' +
    '<div class="dt">em '+v.data+' &middot; vs. anterior</div>' +
    (v.vencido ? '<div class="stale-tag">sem atualizacao ha '+v.idade_dias+' dias</div>' : '') +
    (aviso_cartao(k, v) ? '<div class="stale-tag">'+aviso_cartao(k, v)+'</div>' : '') +
    '</div>';
}).join('');

linha('c-spxpe','w-spxpe',[
  {label:'P/E trailing (convencao de indice)', data:DADOS.spx_pe, cor:c('--deep'), w:1.8},
  {label:'P/E trailing (point-in-time, 75d)', data:DADOS.spx_pe_pit, cor:c('--teal'), dash:[5,4]},
  {label:'P/E operating', data:DADOS.spx_pe_operating, cor:c('--gold'), w:1.2},
], {y:'vezes'});
linha('c-cape','w-cape',[{label:'CAPE', data:DADOS.spx_cape, cor:c('--navy2'), w:1.8}], {y:'vezes'});
linha('c-ey','w-ey',[{label:'Earnings yield', data:DADOS.spx_ey, cor:c('--teal'), w:1.8}], {y:'% a.a.'});
linha('c-pct','w-pct',[
  {label:'Percentil do P/E (0-100)', data:DADOS.spx_pct, cor:c('--deep'), w:1.8},
], {y:'percentil'});
linha('c-juros','w-juros',[
  {label:'Earnings yield (1/P/E)', data:DADOS.spx_ey, cor:c('--teal'), w:1.6},
  {label:'Rendimento do CAPE (1/CAPE)', data:DADOS.cape_yield, cor:c('--navy2'), w:1.8},
  {label:'TIPS 10a (juro real)', data:DADOS.tips10, cor:c('--bad'), w:1.6},
  {label:'Treasury 10a (nominal)', data:DADOS.ust10, cor:c('--gray'), w:1.2, dash:[5,4]},
], {y:'% a.a.'});
linha('c-premio','w-premio',[
  {label:'Earnings yield - TIPS 10a', data:DADOS.ey_menos_real, cor:c('--teal'), w:1.6},
  {label:'1/CAPE - TIPS 10a', data:DADOS.cape_yield_menos_real, cor:c('--navy2'), w:1.8},
], {y:'pontos percentuais'});
linha('c-ibov','w-ibov',[
  {label:'Ibovespa - P/L 12m da carteira atual', data:DADOS.ibov_pl, cor:c('--gold'), w:1.8},
], {y:'vezes (escala logaritmica)', log:true});
linha('c-ibovz','w-ibovz',[
  {label:'Ibovespa - z-score (sobre L/P, sinal invertido)', data:(DADOS.ibov_pl_z.length ? DADOS.ibov_pl_z : DADOS.ibov_z),
   cor:c('--gold'), w:1.8},
], {y:'desvios-padrao'});
linha('c-ibovold','w-ibovold',[
  {label:'Ibovespa - indice de valuation (base 100)', data:DADOS.ibov_val, cor:c('--gray'), w:1.4},
], {y:'base 100'});
linha('c-cmp','w-cmp',[
  {label:'S&P 500 - percentil do P/E', data:DADOS.spx_pct, cor:c('--deep'), w:1.8},
  {label:'Ibovespa - percentil do P/L', data:(DADOS.ibov_pl_pct.length ? DADOS.ibov_pl_pct : DADOS.ibov_pct),
   cor:c('--gold'), w:1.8},
], {y:'percentil (0-100)'});

const PL = STATUS.pl_ibov || {};
if (typeof PL.pl === 'number' && isFinite(PL.pl)){
  document.getElementById('pl-b3').innerHTML =
    'Pelo numerador da propria B3 (indice x redutor da carteira de ' + (PL.data_carteira||'?') +
    '): <b>P/L ' + PL.pl.toFixed(2) + 'x</b> em ' + PL.data + ', com ' + PL.cobertura_pct.toFixed(1) +
    '% do peso coberto' +
    (typeof PL.checagem_numerador_pct === 'number'
      ? '; soma(quantidade x preco) pelos precos do yfinance difere ' +
        PL.checagem_numerador_pct.toFixed(2) + '% desse valor' : '') + '.';
}
const PLEMP = __PLEMP__;
const tpe = document.querySelector('#t-plemp tbody');
if (PLEMP.length){
  PLEMP.forEach(function(r){
    const f = v => (v === null ? '-' : v);
    const tr = document.createElement('tr');
    tr.innerHTML = '<td><b>'+r[0]+'</b></td><td class="num">'+r[1].toFixed(3)+'</td>' +
      '<td class="num">'+(r[2]===null?'-':(r[2]*100).toFixed(1)+'%')+'</td>' +
      '<td class="num">'+f(r[3])+'</td><td class="num">'+(r[4]===null?'-':r[4].toFixed(1)+'x')+'</td>' +
      '<td style="font-size:12px;color:var(--gray)">'+(r[5]||'')+'</td>';
    tpe.appendChild(tr);
  });
} else {
  tpe.innerHTML = '<tr><td colspan="6" class="empty">P/L por companhia indisponivel nesta execucao ' +
    '(ver estagio pl_ibov_nivel no diagnostico).</td></tr>';
}

const tb = document.querySelector('#t-status tbody');
(STATUS.estagios||[]).forEach(function(e){
  const tr = document.createElement('tr');
  tr.innerHTML =
    '<td><code>'+e.nome+'</code></td>' +
    '<td><span class="pill '+(e.ok?'ok':'fail')+'">'+(e.ok?'ok':'falhou')+'</span></td>' +
    '<td class="num">'+(e.obs||0)+'</td>' +
    '<td>'+((e.inicio||e.fim) ? (e.inicio||'?')+' -> '+(e.fim||'?') : '-')+'</td>' +
    '<td style="font-size:12px;color:var(--gray)">'+(e.detalhe||'')+'</td>';
  tb.appendChild(tr);
});
const th = document.querySelector('#t-hist tbody');
const HL = STATUS.historico_longo || {};
const rotHL = {pe:'S&P 500 - P/E trailing (GAAP)', cape:'S&P 500 - CAPE',
               premio_cape:'1/CAPE - TIPS 10a, pp (aqui, percentil BAIXO = acoes caras)'};
const linhasHL = ['pe','cape','premio_cape'].filter(function(k){ return HL[k]; });
if (linhasHL.length){
  linhasHL.forEach(function(k){
    const h = HL[k];
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>'+rotHL[k]+'</td>' +
      '<td class="num"><b>'+h.atual.toFixed(2)+'</b></td>' +
      '<td class="num"><b>'+h.percentil.toFixed(1)+'</b></td>' +
      '<td class="num">'+h.mediana.toFixed(2)+'</td>' +
      '<td class="num">'+h.p10.toFixed(1)+' - '+h.p90.toFixed(1)+'</td>' +
      '<td class="num">'+h.maximo.toFixed(2)+' ('+h.data_maximo.slice(0,7)+')</td>' +
      '<td style="font-size:12px;color:var(--gray)">'+h.inicio.slice(0,7)+' a '+h.fim.slice(0,7)+
        ', '+h.n+' obs.; '+h.acima_do_atual+' acima do atual</td>';
    th.appendChild(tr);
  });
} else {
  th.innerHTML = '<tr><td colspan="7" class="empty">Historia longa indisponivel nesta execucao ' +
    '(ver estagio historia_longa_shiller no diagnostico).</td></tr>';
}

const tv = document.querySelector('#t-vig tbody');
const vigs = STATUS.vigencias || [];
if (vigs.length){
  vigs.forEach(function(v){
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td><code>'+v.fonte+'</code></td>' +
      '<td>'+(v.ultima_observacao||'-')+'</td>' +
      '<td>'+(v.vigente_ate||'-')+'</td>' +
      '<td class="num">'+(v.defasagem_dias!=null ? v.defasagem_dias : '-')+'</td>' +
      '<td><span class="pill '+(v.vencida?'fail':'ok')+'">' +
        (v.vencida?'vencida':'vigente')+'</span></td>';
    tv.appendChild(tr);
  });
} else {
  tv.innerHTML = '<tr><td colspan="5" class="empty">' +
    'Nenhuma fonte com teto de validade aplicavel nesta execucao.</td></tr>';
}

if ((STATUS.avisos||[]).length){
  document.getElementById('avisos').innerHTML =
    STATUS.avisos.map(function(a){ return '<div class="alert">'+a+'</div>'; }).join('');
}

const tc = document.querySelector('#t-comp tbody');
if (COMPOSICAO.length){
  COMPOSICAO.forEach(function(r){
    const tr = document.createElement('tr');
    tr.innerHTML = '<td><b>'+r[0]+'</b></td><td>'+r[1]+'</td><td>'+r[2]+'</td>' +
                   '<td class="num">'+(typeof r[3]==='number' ? r[3].toFixed(3) : r[3])+'</td>';
    tc.appendChild(tr);
  });
} else {
  tc.innerHTML = '<tr><td colspan="4" class="empty">Composicao nao obtida nesta execucao.</td></tr>';
}
</script>
</body></html>
"""

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
