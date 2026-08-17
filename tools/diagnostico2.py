"""Diagnostico das quatro lacunas do dashboard, com dados reais.

Nao corrige nada. Mede o que as fontes oferecem, para que a correcao seguinte
seja informada. O ambiente onde escrevo o codigo nao alcanca CVM, B3 nem a
planilha do Shiller; o runner alcanca.

Perguntas:
  (a) existe fonte de LPA do S&P mais recente que 06/2024?
  (b) quais anos de DFP falham, e por que?
  (c) qual a cobertura POR PESO ao longo do tempo (nao por contagem)?
  (d) a CVM publica lucro por acao? e a B3, quantidade teorica? com os dois,
      o P/E do Ibovespa deixa de ser indice base 100 e vira multiplo em nivel.
"""
from __future__ import annotations
import io, json, sys, zipfile
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import reconcile                                   # noqa: E402
from src.sources import b3, cvm                             # noqa: E402
from src.sources.http import get, get_qualquer              # noqa: E402
from src.config import CVM_DFP_BASES, SHILLER_XLS, SPDJI_EPS_XLSX  # noqa: E402

sec = lambda t: print(f"\n{'='*72}\n{t}\n{'='*72}")


def a_fontes_de_lpa():
    sec("(a) FONTES DE LPA DO S&P -- ATE QUANDO CADA UMA VAI")
    try:
        raw = get(SHILLER_XLS)
        df = pd.ExcelFile(io.BytesIO(raw)).parse("Data", header=None)
        d = pd.to_numeric(df[df.columns[0]], errors="coerce").dropna()
        d = d[(d > 1800) & (d < 2200)]
        print(f"  ie_data (Shiller): ultima data = {d.max():.2f}  ({len(d)} linhas)")
    except Exception as e:
        print(f"  ie_data FALHOU: {type(e).__name__}: {str(e)[:120]}")

    cabecalhos = [
        ("padrao", {}),
        ("navegador", {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                                     "Chrome/126.0 Safari/537.36",
                       "Accept": "application/vnd.openxmlformats-officedocument."
                                 "spreadsheetml.sheet,*/*",
                       "Referer": "https://www.spglobal.com/spdji/en/",
                       "Accept-Language": "en-US,en;q=0.9"}),
    ]
    for nome, h in cabecalhos:
        try:
            raw = get(SPDJI_EPS_XLSX, headers=h, retries=1, timeout=60)
            print(f"  S&P DJI [{nome}]: OK, {len(raw)} bytes")
            try:
                xl = pd.ExcelFile(io.BytesIO(raw))
                print(f"    abas: {xl.sheet_names[:6]}")
            except Exception as e:
                print(f"    nao e xlsx legivel: {type(e).__name__}")
            break
        except Exception as e:
            print(f"  S&P DJI [{nome}]: {str(e)[:110]}")


def b_anos_de_dfp():
    sec("(b) QUAIS ANOS DE DFP FALHAM")
    ok, falhas = [], []
    for ano in range(2010, 2027):
        try:
            conteudo, url = cvm._baixar(CVM_DFP_BASES, f"dfp_cia_aberta_{ano}.zip")
            with zipfile.ZipFile(io.BytesIO(conteudo)) as zf:
                n = len([x for x in zf.namelist() if "dre_con" in x.lower()])
            ok.append(ano)
            print(f"  {ano}: OK  ({len(conteudo)//1024} KB, {n} arquivo(s) DRE_con)")
        except Exception as e:
            falhas.append(ano)
            print(f"  {ano}: FALHOU -- {type(e).__name__}: {str(e)[:100]}")
    print(f"\n  obtidos: {ok}\n  falhos:  {falhas}")


def d_lucro_por_acao():
    sec("(d) A CVM PUBLICA LUCRO POR ACAO? E A B3, QUANTIDADE TEORICA?")
    try:
        conteudo, _ = cvm._baixar(CVM_DFP_BASES, "dfp_cia_aberta_2024.zip")
        df = cvm._read_zip_csv(conteudo, "dre_con")
        print(f"  DRE_con 2024: {len(df)} linhas, colunas={list(df.columns)[:9]}")
        contas = (df[df["CD_CONTA"].astype(str).str.startswith("3.99")]
                  [["CD_CONTA", "DS_CONTA"]].drop_duplicates().sort_values("CD_CONTA"))
        print(f"\n  contas 3.99* (lucro por acao): {len(contas)}")
        for _, r in contas.head(14).iterrows():
            print(f"    {r['CD_CONTA']:<14} {str(r['DS_CONTA'])[:58]}")
        alvo = df[df["CD_CONTA"].astype(str).str.startswith("3.99")]
        alvo = alvo[alvo["ORDEM_EXERC"].str.strip().str.upper() == "ÚLTIMO"]
        print(f"\n  companhias com alguma conta 3.99 no ultimo exercicio: "
              f"{alvo['CD_CVM'].nunique()}")
        v = pd.to_numeric(alvo["VL_CONTA"].str.replace(",", ".", regex=False),
                          errors="coerce").dropna()
        if len(v):
            print(f"  valores: mediana {v.median():.4f}  min {v.min():.2f}  max {v.max():.2f}")
            print("  (se a mediana esta na casa de unidades, e LPA em R$ por acao)")
    except Exception as e:
        print(f"  FALHOU: {type(e).__name__}: {str(e)[:160]}")

    try:
        comp = b3.fetch_ibov_composition()
        print(f"\n  carteira B3: {len(comp)} ativos, colunas={list(comp.columns)}")
        print(comp.head(4).to_string(index=False))
        if "qtd_teorica" in comp.columns:
            q = comp["qtd_teorica"].dropna()
            print(f"\n  qtd_teorica: soma {q.sum():,.0f} | mediana {q.median():,.0f}")
            print("  Com quantidade teorica + LPA por acao, o P/E do indice e")
            print("  soma(preco*qtd)/soma(LPA*qtd) -- multiplo em NIVEL, nao base 100.")
    except Exception as e:
        print(f"  B3 FALHOU: {type(e).__name__}: {str(e)[:120]}")


def c_cobertura_no_tempo():
    sec("(c) COBERTURA POR PESO AO LONGO DO TEMPO")
    try:
        comp = b3.fetch_ibov_composition()
        emp = b3.fetch_empresas_listadas()
        cache, _ = cvm.carregar_cache()
        if cache.empty:
            print("  sem cache de lucros; pulando")
            return
        casadas, cob, rel = reconcile.conciliar(comp, emp, cache)
        print(f"  cobertura da carteira: {cob:.1%} ({rel['ativos']})")
        peso = dict(zip(casadas["cd_cvm"].map(reconcile.normalizar_cd_cvm),
                        casadas["participacao_pct"]))
        lu = cache.copy()
        lu["cd"] = lu["cd_cvm"].map(reconcile.normalizar_cd_cvm)
        lu = lu[lu["freq"] == "A"]
        print("\n  ano | companhias com DFP | peso coberto | peso total")
        total = sum(peso.values())
        for ano in range(2010, 2026):
            g = lu[lu["data_fim"].dt.year == ano]
            cds = set(g["cd"].unique())
            p = sum(peso.get(c, 0.0) for c in cds)
            print(f"  {ano} | {len(cds & set(peso)):>18} | {p:>11.1f} | {p/total:>6.1%}")
        print("\n  Se o criterio for POR PESO em vez de contagem, a serie pode")
        print("  comecar antes de 2014 sem afrouxar o portao.")
    except Exception as e:
        print(f"  FALHOU: {type(e).__name__}: {str(e)[:160]}")


if __name__ == "__main__":
    a_fontes_de_lpa()
    b_anos_de_dfp()
    d_lucro_por_acao()
    c_cobertura_no_tempo()
