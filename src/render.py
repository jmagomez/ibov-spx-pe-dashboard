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

from .config import DOCS, PROCESSED

log = logging.getLogger("render")

# Amostragem para o grafico: manter todos os pregoes desde 2010 gera um JSON
# grande sem ganho visual. Amostrar preserva a forma da serie; o CSV completo
# continua disponivel para quem quiser o dado bruto.
PASSO_PLOT = 3


def _serie(df: pd.DataFrame, col: str) -> list:
    if df.empty or col not in df.columns:
        return []
    s = df[col].dropna().iloc[::PASSO_PLOT]
    return [[d.strftime("%Y-%m-%d"), round(float(v), 4)] for d, v in s.items()]


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
    }

    def _ult(df: pd.DataFrame, col: str):
        if df.empty or col not in df.columns:
            return None
        s = df[col].dropna()
        if s.empty:
            return None
        return {"data": s.index[-1].strftime("%Y-%m-%d"), "valor": round(float(s.iloc[-1]), 2)}

    cartoes = {
        "spx_pe": _ult(spx, "pe"),
        "spx_cape": _ult(spx, "cape"),
        "spx_ey": _ult(spx, "earnings_yield"),
        "spx_pct": _ult(spx, "pe_pct"),
        "ibov_val": _ult(ibov, "valuation_idx"),
        "ibov_pct": _ult(ibov, "valuation_pct"),
    }

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
    html = html.replace("__GERADO__",
                        datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"))
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
</header>
<div class="wrap">

<div class="alert">
  <b>Leia antes de usar.</b> As duas series nao sao diretamente comparaveis em nivel.
  O S&amp;P 500 tem P/E em nivel verdadeiro, calculado com o LPA do indice publicado pela propria
  S&amp;P Dow Jones Indices. O Ibovespa nao tem equivalente gratuito: o que se mostra e um
  <i>indice de valuation normalizado (base 100)</i>, construido com a carteira vigente e lucros da CVM,
  sujeito a vies de sobrevivencia. Comparar as duas linhas em nivel e um erro de leitura.
  Ver <code>METODOLOGIA.md</code> e <code>LIMITACOES.md</code>.
</div>

<h2>Situacao atual</h2>
<div class="cards" id="cards"></div>

<h2>S&amp;P 500 - P/E em nivel</h2>
<div class="chartbox">
  <h3>P/E trailing 12 meses</h3>
  <p class="sub">Preco de fechamento dividido pelo LPA as-reported acumulado em 12 meses (S&amp;P DJI).
     A linha tracejada aplica defasagem de 75 dias entre o fim do trimestre e a data em que o lucro
     era efetivamente conhecido - a diferenca entre as duas e o quanto a convencao de indice antecipa informacao.</p>
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

<h2>Ibovespa - indice de valuation (base 100)</h2>
<div class="chartbox">
  <h3>Preco do indice dividido pelo lucro agregado das componentes, normalizado</h3>
  <p class="sub">Nao e P/E em nivel. E a mesma razao medida de forma consistente ao longo do tempo,
     reescalada para 100 na primeira data valida. Serve para ler direcao e amplitude, nao patamar.
     O trecho anterior a cobertura de ITR usa lucro anual da DFP.</p>
  <div id="w-ibov"><canvas id="c-ibov"></canvas></div>
</div>

<h2>Diagnostico da coleta</h2>
<p style="font-size:13.5px;color:var(--gray);margin-top:-4px">
  Estado real de cada fonte na ultima execucao. Um estagio com falha significa grafico vazio,
  nunca grafico preenchido por estimativa.</p>
<table id="t-status"><thead><tr>
  <th>Estagio</th><th>Situacao</th><th class="num">Observacoes</th><th>Periodo</th><th>Detalhe</th>
</tr></thead><tbody></tbody></table>
<div id="avisos"></div>

<h2>Carteira vigente do Ibovespa (30 maiores pesos)</h2>
<p style="font-size:13.5px;color:var(--gray);margin-top:-4px">
  Composicao atual, obtida da B3. A B3 nao publica em formato aberto o historico de composicao
  desde 2010 - e essa ausencia que gera o vies de sobrevivencia descrito nas limitacoes.</p>
<table id="t-comp"><thead><tr>
  <th>Codigo</th><th>Empresa</th><th>Tipo</th><th class="num">Participacao (%)</th>
</tr></thead><tbody></tbody></table>

<footer>
  Gerado em __GERADO__ - Atualizacao automatica aos sabados as 9h (BRT) -
  Este material e informativo e nao constitui recomendacao de investimento.
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

function linha(canvasId, wrapId, series, opts){
  const vazio = series.every(s => !s.data || s.data.length === 0);
  if (vazio){
    document.getElementById(wrapId).innerHTML =
      '<div class="empty">Sem dados publicaveis para este grafico nesta execucao.<br>' +
      'Consulte o diagnostico da coleta abaixo para a causa.</div>';
    return;
  }
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
        tooltip:{callbacks:{label:x => x.dataset.label + ': ' + Number(x.parsed.y).toFixed(2)}}
      },
      scales:{
        x:{type:'time', time:{unit:'year'}, grid:{display:false},
           ticks:{font:{size:11}, color:c('--gray')}},
        y:{grid:{color:c('--line')}, ticks:{font:{size:11}, color:c('--gray')},
           title:{display:!!(opts&&opts.y), text:(opts&&opts.y)||'',
                  font:{size:11}, color:c('--gray')}}
      }
    }
  });
}

const defs = [
  ['spx_pe','S&P 500 - P/E trailing',''],
  ['spx_cape','S&P 500 - CAPE',''],
  ['spx_ey','S&P 500 - Earnings yield','%'],
  ['spx_pct','S&P 500 - Percentil do P/E',''],
  ['ibov_val','Ibovespa - Indice de valuation',''],
  ['ibov_pct','Ibovespa - Percentil',''],
];
document.getElementById('cards').innerHTML = defs.map(function(d){
  const k = d[0], lbl = d[1], suf = d[2];
  const v = CARTOES[k];
  return '<div class="card"><div class="lbl">'+lbl+'</div>' +
    (v ? '<div class="val">'+v.valor+suf+'</div><div class="dt">em '+v.data+'</div>'
       : '<div class="na">indisponivel</div><div class="dt">fonte nao retornou dados</div>') +
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
linha('c-ibov','w-ibov',[
  {label:'Ibovespa - indice de valuation (base 100)', data:DADOS.ibov_val, cor:c('--gold'), w:1.8},
], {y:'base 100'});

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
