"""Diagnostico com dados reais, executado no runner.

Existe porque o ambiente onde escrevo o codigo nao alcanca B3, CVM nem a
planilha do Shiller -- e sem ver a resposta real dessas fontes, qualquer
correcao seria chute. Este script nao corrige nada: ele imprime o que as fontes
de fato devolvem, para que a correcao seguinte seja informada.

Duas perguntas em aberto que ele responde:

  1. Qual e o layout real do cabecalho da aba Data da ie_data, e qual coluna
     contem o CAPE. A busca por rotulo vem falhando e a serie esta ausente.
  2. Por que 22 ativos do Ibovespa -- entre eles ITUB4, PETR4 e PETR3, que
     sozinhos sao 20 pontos de peso -- nao encontram correspondencia na CVM.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import reconcile                                    # noqa: E402
from src.sources import b3, cvm, shiller                     # noqa: E402
from src.sources.http import get                             # noqa: E402
from src.config import SHILLER_XLS                           # noqa: E402


def secao(t): print(f"\n{'='*72}\n{t}\n{'='*72}")


# ---------------------------------------------------------------------------
def diagnosticar_cape():
    secao("1. CABECALHO REAL DA PLANILHA ie_data (aba Data)")
    try:
        raw = get(SHILLER_XLS)
        xls = pd.ExcelFile(io.BytesIO(raw))
        print("abas:", xls.sheet_names)
        sheet = next((s for s in xls.sheet_names if s.strip().lower() == "data"),
                     xls.sheet_names[0])
        df = xls.parse(sheet, header=None)
        print(f"aba '{sheet}': {df.shape[0]} linhas x {df.shape[1]} colunas\n")

        print("--- primeiras 12 linhas, colunas 0..24 (truncadas em 18 chars) ---")
        for i in range(min(12, len(df))):
            cels = []
            for c in list(df.columns)[:25]:
                v = str(df.iloc[i][c]).strip()
                cels.append("." if v in ("nan", "") else v[:18])
            print(f"L{i:<2} " + " | ".join(cels))

        print("\n--- mediana de cada coluna numerica (linhas 10 em diante) ---")
        corpo = df.iloc[10:]
        for c in list(df.columns)[:25]:
            v = pd.to_numeric(corpo[c], errors="coerce").dropna()
            if v.size < 100:
                continue
            rot = " / ".join(str(df.iloc[r][c]).strip() for r in range(0, 10)
                             if str(df.iloc[r][c]).strip() not in ("nan", ""))
            print(f"  col {c:<3} n={v.size:<6} mediana={float(v.median()):>12.4f} "
                  f"min={float(v.min()):>10.4f} max={float(v.max()):>10.4f}  rotulos: {rot[:60]}")
    except Exception as exc:  # noqa: BLE001
        print(f"FALHOU: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
def diagnosticar_conciliacao():
    secao("2. POR QUE 22 ATIVOS NAO CONCILIAM")
    try:
        comp = b3.fetch_ibov_composition()
        emp = b3.fetch_empresas_listadas()
        print(f"carteira: {len(comp)} ativos | cadastro de listadas: {len(emp)} companhias")
        print(f"colunas do cadastro: {list(emp.columns)}")
        print("\n--- amostra do cadastro (10 primeiras) ---")
        print(emp.head(10).to_string(index=False))
    except Exception as exc:  # noqa: BLE001
        print(f"B3 FALHOU: {type(exc).__name__}: {exc}")
        return

    ano = pd.Timestamp.utcnow().year
    try:
        dfp = cvm.fetch_range(range(2010, ano), "DFP")
        try:
            itr = cvm.fetch_range(range(ano - 5, ano + 1), "ITR")
            lucros = pd.concat([dfp, itr], ignore_index=True)
        except Exception:  # noqa: BLE001
            lucros = dfp
    except Exception as exc:  # noqa: BLE001
        cache, _ = cvm.carregar_cache()
        if cache.empty:
            print(f"CVM FALHOU e sem cache: {exc}")
            return
        lucros = cache
        print("(usando cache da CVM)")

    casadas, cob, rel = reconcile.conciliar(comp, emp, lucros)
    print(f"\ncobertura {cob:.1%} | por codigo CVM {rel['por_codigo_cvm']}, "
          f"por CNPJ {rel['por_cnpj']}, por nome {rel['por_nome']}")

    cds = set(lucros["cd_cvm"].astype(str).str.strip().str.lstrip("0"))
    cnpjs = set(lucros["cnpj"].map(reconcile.normalizar_cnpj)) if "cnpj" in lucros else set()
    por_raiz = {str(r["raiz"]).upper(): r for _, r in emp.iterrows()}

    print(f"\n--- os {len(rel['sem_correspondencia'])} sem correspondencia ---")
    print(f"{'ativo':<8} {'raiz':<6} {'peso':>6}  {'no cadastro B3?':<16} "
          f"{'codeCVM':<9} {'na CVM?':<8} {'CNPJ':<15} {'na CVM?'}")
    for x in sorted(rel["sem_correspondencia"], key=lambda x: -x["peso"]):
        cod = x["codigo"]
        raiz = reconcile.raiz_ticker(cod)
        r = por_raiz.get(raiz)
        if r is None:
            print(f"{cod:<8} {raiz:<6} {x['peso']:>6.2f}  {'NAO ESTA':<16}")
            continue
        cd = str(r.get("cd_cvm", "")).strip().lstrip("0")
        cnpj = reconcile.normalizar_cnpj(r.get("cnpj", ""))
        print(f"{cod:<8} {raiz:<6} {x['peso']:>6.2f}  {'sim':<16} "
              f"{cd:<9} {'sim' if cd in cds else 'NAO':<8} {cnpj:<15} "
              f"{'sim' if cnpj in cnpjs else 'NAO'}")

    # Se a raiz nao esta no cadastro, qual e a chave que a B3 usa?
    faltantes = [reconcile.raiz_ticker(x["codigo"]) for x in rel["sem_correspondencia"]]
    ausentes = [r for r in faltantes if r not in por_raiz]
    if ausentes:
        print(f"\n--- {len(ausentes)} raizes ausentes do cadastro; procurando por prefixo ---")
        for raiz in ausentes[:12]:
            cands = emp[emp["raiz"].str.startswith(raiz[:3])]
            print(f"  {raiz}: {len(cands)} candidatos por prefixo de 3 letras -> "
                  f"{list(cands['raiz'])[:6]}")

    # Nomes das companhias na CVM que se parecem com os ativos faltantes
    print("\n--- busca por razao social na CVM (5 maiores faltantes) ---")
    nomes = lucros[["cd_cvm", "empresa"]].drop_duplicates()
    for x in sorted(rel["sem_correspondencia"], key=lambda x: -x["peso"])[:5]:
        raiz = reconcile.raiz_ticker(x["codigo"])
        alvo = raiz[:4]
        hits = nomes[nomes["empresa"].str.upper().str.contains(alvo, na=False)]
        print(f"  {x['codigo']} (raiz {raiz}): {len(hits)} companhias com '{alvo}' no nome")
        for _, h in hits.head(4).iterrows():
            print(f"      cd_cvm={h['cd_cvm']:<8} {h['empresa'][:52]}")


if __name__ == "__main__":
    diagnosticar_cape()
    diagnosticar_conciliacao()
