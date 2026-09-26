"""Monta o resumo diario a partir do que foi publicado em data/processed/.

Tres arquivos saem daqui:

  data/processed/digest.html    corpo do e-mail
  data/processed/digest.txt     mesmo conteudo em texto puro
  data/processed/digest_assunto.txt   linha de assunto

E um quarto, que nao e saida e sim memoria:

  data/processed/digest_estado.json   estado da execucao anterior

O estado existe por um motivo especifico. Um resumo que repete todo dia os
mesmos avisos deixa de ser lido na segunda semana, e o dia em que um aviso NOVO
aparece e justamente o dia em que ele se perde no meio dos antigos. Entao o
e-mail separa duas coisas: o que MUDOU desde ontem, que vai no topo, e o estado
corrente, que vai abaixo. A comparacao e contra o arquivo de estado, versionado
junto com os dados.

Regra herdada do resto do repositorio e valida aqui tambem: este modulo nao
calcula indicador nenhum. Ele le o que o build publicou. Se um numero nao esta
no CSV, ele nao aparece no e-mail -- nao ha "ultimo valor conhecido" aqui.
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
ESTADO = PROCESSED / "digest_estado.json"

DASHBOARD_URL = "https://jmagomez.github.io/ibov-spx-pe-dashboard/"
REPO_URL = "https://github.com/jmagomez/ibov-spx-pe-dashboard"

# Um valor com mais dias que isto nao e "de hoje". Cobre feriado prolongado em
# qualquer das duas pracas sem disparar alarme falso.
IDADE_MAXIMA_DIAS = 7

# Faixas de percentil que valem uma linha no topo do e-mail quando sao
# cruzadas. Nao sao sinal de compra ou venda -- sao mudanca de regime
# estatistico da propria serie, que e o que o painel mede.
FAIXA_ALTA = 80.0
FAIXA_BAIXA = 20.0


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def _ler_csv(nome: str) -> pd.DataFrame:
    p = PROCESSED / nome
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, parse_dates=["data"]).set_index("data")


def _ler_status() -> dict:
    p = PROCESSED / "status.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def ultimo(df: pd.DataFrame, col: str, referencia: pd.Timestamp | None) -> dict | None:
    """Ultimo valor da coluna, com variacao contra a observacao anterior.

    "Observacao anterior" e da propria serie, nao o dia anterior do calendario:
    o CAPE e mensal e o lucro e trimestral. Chamar de "variacao diaria" o passo
    de uma serie mensal seria rotulo errado, e o rotulo no e-mail diz isso.
    """
    if df.empty or col not in df.columns:
        return None
    s = df[col].dropna()
    if s.empty:
        return None
    atual = float(s.iloc[-1])
    anterior = float(s.iloc[-2]) if len(s) > 1 else None
    data = s.index[-1]
    idade = int((referencia - data).days) if referencia is not None else 0
    return {
        "valor": atual,
        "data": data.strftime("%d/%m/%Y"),
        "data_iso": data.strftime("%Y-%m-%d"),
        "delta": (atual - anterior) if anterior is not None else None,
        "delta_pct": ((atual / anterior - 1) * 100.0
                      if anterior not in (None, 0) else None),
        "idade_dias": idade,
        "vencido": idade > IDADE_MAXIMA_DIAS,
    }


def coletar(spx: pd.DataFrame, ibov: pd.DataFrame, status: dict) -> dict:
    referencia = max([d.index.max() for d in (spx, ibov) if not d.empty], default=None)
    metricas = {
        "spx_pe": ("S&P 500 - P/E trailing 12m", "", ultimo(spx, "pe", referencia)),
        "spx_cape": ("S&P 500 - CAPE", "", ultimo(spx, "cape", referencia)),
        "spx_ey": ("S&P 500 - earnings yield", "%", ultimo(spx, "earnings_yield", referencia)),
        "spx_pct": ("S&P 500 - percentil do P/E (10a)", "", ultimo(spx, "pe_pct", referencia)),
        "ibov_pl": ("Ibovespa - P/L 12m da carteira atual", "x",
                    ultimo(ibov, "pl_nivel", referencia)),
        "ibov_pl_pct": ("Ibovespa - percentil do P/L (10a)", "",
                        ultimo(ibov, "pl_nivel_pct", referencia)),
        "ibov_val": ("Ibovespa - indice de valuation (base 100, serie anterior)", "",
                     ultimo(ibov, "valuation_idx", referencia)),
        "spx_eps_yoy": ("S&P 500 - LPA 12m, variacao a/a", "%",
                        ultimo(spx, "eps_yoy_pct", referencia)),
        "spx_ey_real": ("S&P 500 - earnings yield menos juro real 10a", " pp",
                        ultimo(spx, "ey_menos_real", referencia)),
        "spx_cape_real": ("S&P 500 - 1/CAPE menos juro real 10a", " pp",
                          ultimo(spx, "cape_yield_menos_real", referencia)),
    }
    estagios = {e["nome"]: bool(e.get("ok")) for e in status.get("estagios", [])}
    vencidas = sorted(v["fonte"] for v in status.get("vigencias", []) if v.get("vencida"))
    return {
        "referencia": referencia.strftime("%d/%m/%Y") if referencia is not None else "-",
        "referencia_iso": referencia.strftime("%Y-%m-%d") if referencia is not None else "",
        "metricas": metricas,
        "estagios": estagios,
        "vencidas": vencidas,
        "avisos": list(status.get("avisos", [])),
        "gerado_em_utc": status.get("gerado_em_utc", ""),
        "historico": dict(status.get("historico_longo", {}) or {}),
    }


# ---------------------------------------------------------------------------
# O que mudou desde ontem
# ---------------------------------------------------------------------------

def _faixa(pct: float | None) -> str:
    if pct is None:
        return "sem_dado"
    if pct >= FAIXA_ALTA:
        return "alta"
    if pct <= FAIXA_BAIXA:
        return "baixa"
    return "intermediaria"


def _sinal(m: dict | None) -> str:
    if not m:
        return "sem_dado"
    return "negativo" if m["valor"] < 0 else "positivo"


def estado_atual(d: dict) -> dict:
    def _pct(chave):
        m = d["metricas"].get(chave, (None, None, None))[2]
        return m["valor"] if m else None
    return {
        "referencia_iso": d["referencia_iso"],
        "estagios": d["estagios"],
        "vencidas": d["vencidas"],
        "faixa_spx": _faixa(_pct("spx_pct")),
        # O percentil do P/L em nivel substitui o do indice base 100 quando existe.
        "faixa_ibov": _faixa(_pct("ibov_pl_pct") if _pct("ibov_pl_pct") is not None
                             else _pct("ibov_pct")),
        "sinal_premio_cape": _sinal(d["metricas"].get("spx_cape_real", (None, None, None))[2]),
        "series_vazias": sorted(k for k, (_, _, m) in d["metricas"].items() if m is None),
    }


PRIMEIRA_EXECUCAO = ("Primeira execucao com o resumo diario ligado: nao ha execucao "
                     "anterior contra a qual comparar. A partir de amanha esta secao "
                     "traz so o que mudou.")


def mudancas(atual: dict, anterior: dict | None) -> list[str]:
    """Diferencas entre esta execucao e a anterior, em linguagem de gente.

    Primeira execucao nao produz lista de mudancas: nao ha contra o que comparar,
    e inventar "tudo novo" encheria o primeiro e-mail de ruido.
    """
    if not anterior:
        return []
    out = []

    ant_est, at_est = anterior.get("estagios", {}), atual.get("estagios", {})
    for nome, ok in at_est.items():
        if nome in ant_est and ant_est[nome] != ok:
            out.append(f"Estagio '{nome}' passou a {'FUNCIONAR' if ok else 'FALHAR'}.")
    for nome in at_est.keys() - ant_est.keys():
        out.append(f"Estagio novo no pipeline: '{nome}'.")

    novas = set(atual.get("vencidas", [])) - set(anterior.get("vencidas", []))
    for f in sorted(novas):
        out.append(f"A fonte '{f}' VENCEU: a ultima observacao dela perdeu lastro e o "
                   f"trecho final da serie fica vazio.")
    voltou = set(anterior.get("vencidas", [])) - set(atual.get("vencidas", []))
    for f in sorted(voltou):
        out.append(f"A fonte '{f}' voltou a ter observacao vigente.")

    sumiram = set(atual.get("series_vazias", [])) - set(anterior.get("series_vazias", []))
    for s in sorted(sumiram):
        out.append(f"A serie '{s}' ficou SEM valor publicavel nesta execucao.")
    voltaram = set(anterior.get("series_vazias", [])) - set(atual.get("series_vazias", []))
    for s in sorted(voltaram):
        out.append(f"A serie '{s}' voltou a ter valor publicavel.")

    rotulo = {"alta": f"acima do percentil {FAIXA_ALTA:.0f}",
              "baixa": f"abaixo do percentil {FAIXA_BAIXA:.0f}",
              "intermediaria": "na faixa intermediaria",
              "sem_dado": "sem dado"}
    a, b = anterior.get("sinal_premio_cape"), atual.get("sinal_premio_cape")
    if a in ("positivo", "negativo") and b in ("positivo", "negativo") and a != b:
        out.append("S&P 500: o rendimento do lucro normalizado (1/CAPE) passou a ficar "
                   + ("ABAIXO" if b == "negativo" else "ACIMA")
                   + " do juro real de 10 anos (TIPS). E leitura de valuation relativo a "
                     "juros, nao sinal de compra ou venda.")
    for chave, nome in (("faixa_spx", "S&P 500"), ("faixa_ibov", "Ibovespa")):
        a, b = anterior.get(chave), atual.get(chave)
        if a and b and a != b:
            out.append(f"{nome}: o percentil saiu de '{rotulo.get(a, a)}' para "
                       f"'{rotulo.get(b, b)}'. E mudanca de posicao na propria "
                       f"distribuicao, nao sinal de compra ou venda.")
    return out


# ---------------------------------------------------------------------------
# Formatacao
# ---------------------------------------------------------------------------

def _num(v: float, casas: int = 2) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _linha_delta(m: dict) -> str:
    if m["delta"] is None:
        return "-"
    sinal = "+" if m["delta"] > 0 else ""
    if m["delta_pct"] is None:
        return f"{sinal}{_num(m['delta'])}"
    return f"{sinal}{_num(m['delta'])} ({sinal}{_num(m['delta_pct'])}%)"


def assunto(d: dict, muds: list[str]) -> str:
    """Linha de assunto.

    Um numero vencido NAO entra aqui com a cara de numero do dia. A linha de
    assunto e o unico pedaco do e-mail que a pessoa le sem falta, e no celular
    ela aparece sozinha, sem a data em letra pequena embaixo. Serie sem lastro
    recente vira "sem lastro" em vez de virar um valor de dois anos atras.
    """
    partes = []
    ibov = (("ibov_pl", "IBOV P/L") if d["metricas"].get("ibov_pl", (0, 0, None))[2]
            else ("ibov_val", "IBOV val"))
    for chave, rotulo in (("spx_pe", "S&P P/E"), ibov):
        m = d["metricas"].get(chave, (None, None, None))[2]
        if not m:
            partes.append(f"{rotulo} indisponivel")
        elif m["vencido"]:
            partes.append(f"{rotulo} sem lastro")
        else:
            partes.append(f"{rotulo} {_num(m['valor'])}")
    corpo = " | ".join(partes)
    prefixo = "[!] " if muds else ""
    return f"{prefixo}P/E Ibovespa x S&P 500 - {d['referencia']} - {corpo}"


def historia_longa_linhas(d: dict) -> list[str]:
    """O percentil de 10 anos dos cartoes, recolocado contra a historia inteira."""
    h = d.get("historico") or {}
    L = []
    if "pe" in h:
        x = h["pe"]
        L.append(f"P/E {_num(x['atual'])} no percentil {_num(x['percentil'], 0)} desde "
                 f"{x['inicio'][:4]} (mediana historica {_num(x['mediana'], 1)})")
    if "cape" in h:
        x = h["cape"]
        L.append(f"CAPE {_num(x['atual'])} no percentil {_num(x['percentil'], 0)} desde "
                 f"{x['inicio'][:4]} (mediana {_num(x['mediana'], 1)}; maximo "
                 f"{_num(x['maximo'], 1)} em {x['data_maximo'][:7]})")
    if not L:
        return []
    return ["HISTORIA LONGA (planilha de Shiller)"] + [f"  {x}" for x in L]


def texto(d: dict, muds: list[str]) -> str:
    L = [f"P/E Ibovespa x S&P 500 - dados ate {d['referencia']}", ""]
    if muds:
        L.append("MUDOU DESDE A EXECUCAO ANTERIOR")
        L += [f"  - {m}" for m in muds]
        L.append("")
    else:
        L += ["Nada mudou de estado desde a execucao anterior.", ""]
    L.append("NUMEROS")
    for _, (rotulo, suf, m) in d["metricas"].items():
        if not m:
            L.append(f"  {rotulo}: indisponivel (fonte nao retornou dado)")
            continue
        marca = f"  [sem atualizacao ha {m['idade_dias']} dias]" if m["vencido"] else ""
        L.append(f"  {rotulo}: {_num(m['valor'])}{suf}  "
                 f"vs anterior {_linha_delta(m)}  (em {m['data']}){marca}")
    L += [""] + historia_longa_linhas(d)
    falhos = [n for n, ok in d["estagios"].items() if not ok]
    L += ["", f"COLETA: {len(d['estagios']) - len(falhos)}/{len(d['estagios'])} estagios ok"]
    if falhos:
        L.append("  falharam: " + ", ".join(falhos))
    if d["avisos"]:
        L += ["", "AVISOS DO PIPELINE"]
        L += [f"  - {a}" for a in d["avisos"]]
    L += ["", f"Dashboard: {DASHBOARD_URL}", f"Repositorio: {REPO_URL}", "",
          "Material informativo. Nao e recomendacao de investimento.",
          "O P/L do Ibovespa e o da carteira atual (vies de sobrevivencia no historico).",
          "Comparar os dois indices em nivel e fragil: setores, contabilidade e moeda",
          "explicam boa parte da diferenca. Ver LIMITACOES.md."]
    return "\n".join(L)


_CSS_TD = "padding:7px 10px;border-bottom:1px solid #DCE6EB;font-size:14px"


def html(d: dict, muds: list[str]) -> str:
    """Corpo do e-mail. Estilo inline: cliente de e-mail nao aplica <style>."""
    linhas = []
    for _, (rotulo, suf, m) in d["metricas"].items():
        if not m:
            linhas.append(
                f'<tr><td style="{_CSS_TD}">{rotulo}</td>'
                f'<td style="{_CSS_TD};text-align:right;color:#B4442E">indisponivel</td>'
                f'<td style="{_CSS_TD};text-align:right;color:#6E8087">-</td>'
                f'<td style="{_CSS_TD};color:#6E8087">fonte nao retornou dado</td></tr>')
            continue
        cor = "#2E7D52" if (m["delta"] or 0) > 0 else ("#B4442E" if (m["delta"] or 0) < 0
                                                       else "#6E8087")
        obs = (f'<span style="color:#8A5A12">sem atualizacao ha {m["idade_dias"]} dias</span>'
               if m["vencido"] else f'em {m["data"]}')
        linhas.append(
            f'<tr><td style="{_CSS_TD}">{rotulo}</td>'
            f'<td style="{_CSS_TD};text-align:right;font-weight:700;font-size:16px">'
            f'{_num(m["valor"])}{suf}</td>'
            f'<td style="{_CSS_TD};text-align:right;color:{cor}">{_linha_delta(m)}</td>'
            f'<td style="{_CSS_TD};color:#6E8087;font-size:12.5px">{obs}</td></tr>')

    if muds:
        bloco = ('<div style="border:1px solid #E0A458;background:#FDF6EC;border-radius:6px;'
                 'padding:12px 16px;margin:0 0 18px">'
                 '<b style="color:#11324A">Mudou desde a execucao anterior</b>'
                 '<ul style="margin:8px 0 0;padding-left:20px">'
                 + "".join(f"<li style='font-size:13.5px;margin:3px 0'>{m}</li>" for m in muds)
                 + "</ul></div>")
    else:
        bloco = ('<p style="font-size:13.5px;color:#6E8087;margin:0 0 18px">'
                 'Nada mudou de estado desde a execucao anterior: mesmas fontes vigentes, '
                 'mesmos estagios funcionando, percentis na mesma faixa.</p>')

    falhos = [n for n, ok in d["estagios"].items() if not ok]
    coleta = (f'{len(d["estagios"]) - len(falhos)}/{len(d["estagios"])} estagios ok'
              + (f' &middot; <b style="color:#B4442E">falharam: {", ".join(falhos)}</b>'
                 if falhos else ""))
    avisos = ""
    if d["avisos"]:
        avisos = ('<p style="font-size:13px;color:#11324A;margin:16px 0 4px"><b>'
                  'Avisos do pipeline</b></p><ul style="margin:0;padding-left:20px">'
                  + "".join(f"<li style='font-size:12.5px;color:#6E8087;margin:3px 0'>{a}</li>"
                            for a in d["avisos"]) + "</ul>")

    hl = historia_longa_linhas(d)
    historia_html = ""
    if hl:
        historia_html = ('<p style="font-size:13px;color:#11324A;margin:16px 0 4px"><b>'
                         'Historia longa (planilha de Shiller)</b></p>'
                         '<ul style="margin:0;padding-left:20px">'
                         + "".join(f"<li style='font-size:13px;margin:3px 0'>{x}</li>"
                                   for x in hl[1:]) + "</ul>")

    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"></head>
<body style="margin:0;background:#F4F7F9;
             font-family:'Segoe UI',Calibri,system-ui,sans-serif;color:#1E2933">
<div style="max-width:720px;margin:0 auto;background:#fff">
  <div style="background:#0E2A3B;color:#fff;padding:22px 26px">
    <div style="font-size:20px;font-weight:700">P/E do Ibovespa e do S&amp;P 500</div>
    <div style="font-size:13px;color:#CADCEC;margin-top:4px">
      Dados ate {d['referencia']} &middot; execucao de {d['gerado_em_utc'] or '-'}</div>
  </div>
  <div style="padding:22px 26px">
    {bloco}
    <table style="width:100%;border-collapse:collapse">
      <thead><tr>
        <th style="{_CSS_TD};background:#EAF1F5;text-align:left;color:#11324A">Metrica</th>
        <th style="{_CSS_TD};background:#EAF1F5;text-align:right;color:#11324A">Valor</th>
        <th style="{_CSS_TD};background:#EAF1F5;text-align:right;color:#11324A">vs. anterior</th>
        <th style="{_CSS_TD};background:#EAF1F5;text-align:left;color:#11324A">Referencia</th>
      </tr></thead>
      <tbody>{"".join(linhas)}</tbody>
    </table>
    {historia_html}
    <p style="font-size:13px;color:#6E8087;margin:14px 0 0">Coleta: {coleta}</p>
    {avisos}
    <p style="margin:22px 0 6px">
      <a href="{DASHBOARD_URL}" style="background:#065A82;color:#fff;text-decoration:none;
         padding:10px 18px;border-radius:5px;font-size:14px;display:inline-block">
         Abrir o dashboard</a></p>
    <p style="font-size:12px;color:#6E8087;margin:16px 0 0;line-height:1.6">
      O P/L do Ibovespa e o da carteira atual da B3 (quantidade teorica x preco sobre o
      lucro de 12 meses de cada companhia, na fracao que o indice carrega); o historico e o
      que esta carteira teria tido. Comparar os dois indices em nivel e fragil: setores,
      contabilidade e moeda explicam boa parte da diferenca. Material informativo; nao e
      recomendacao de investimento. <a href="{REPO_URL}" style="color:#065A82">Metodologia e limitacoes</a>.
    </p>
  </div>
</div></body></html>"""


# ---------------------------------------------------------------------------

def main() -> int:
    spx, ibov = _ler_csv("spx.csv"), _ler_csv("ibov.csv")
    status = _ler_status()
    if spx.empty and ibov.empty and not status:
        print("digest: nada publicado em data/processed; nada a resumir.")
        return 1

    d = coletar(spx, ibov, status)
    anterior = json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else None
    atual = estado_atual(d)
    muds = mudancas(atual, anterior) if anterior else [PRIMEIRA_EXECUCAO]

    PROCESSED.mkdir(parents=True, exist_ok=True)
    (PROCESSED / "digest.html").write_text(html(d, muds), encoding="utf-8")
    (PROCESSED / "digest.txt").write_text(texto(d, muds), encoding="utf-8")
    (PROCESSED / "digest_assunto.txt").write_text(assunto(d, muds), encoding="utf-8")
    atual["escrito_em_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ESTADO.write_text(json.dumps(atual, ensure_ascii=False, indent=2), encoding="utf-8")

    print(texto(d, muds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
