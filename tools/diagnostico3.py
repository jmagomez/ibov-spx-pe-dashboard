"""Diagnostico para o P/L do Ibovespa EM NIVEL.

Pergunta: com o que as fontes abertas publicam, da para calcular

    P/L = soma(qtd_teorica_i * preco_i) / soma(qtd_teorica_i * LPA_i)

em vez do indice base 100? O numerador sai do proprio indice (valor = soma
de preco x quantidade / redutor), se a B3 publicar o redutor. O denominador
precisa de LPA por classe de acao, que a CVM publica na DRE (contas 3.99), ou
do lucro atribuivel a controladora (3.11.01) e do numero de acoes
(composicao do capital).

Nao corrige nada. Imprime o que existe, e grava a mesma saida em
data/processed/diagnostico.txt para que ela fique no commit da execucao.
"""
from __future__ import annotations

import base64
import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import B3_INDEX_PORTFOLIO, CVM_DFP_BASES, CVM_ITR_BASES, PROCESSED  # noqa: E402
from src.sources import cvm  # noqa: E402
from src.sources.http import get  # noqa: E402

# Companhias com estrutura que interessa ao teste: ON+PN (Petrobras, Itau,
# Bradesco, Gerdau), units (BTG, Santander, Taesa, Klabin, Energisa,
# Iguatemi), holding com controlada no indice (Itausa, Cosan, Bradespar,
# Metalurgica Gerdau) e minoritarios relevantes (Rede D'Or, Localiza, Vale).
AMOSTRA = {
    "9512": "PETROBRAS", "19348": "ITAU", "906": "BRADESCO", "4170": "VALE",
    "22616": "BTG", "20532": "SANTANDER", "20257": "TAESA", "12653": "KLABIN",
    "15253": "ENERGISA", "20494": "IGUATEMI", "7617": "ITAUSA", "19836": "COSAN",
    "18724": "BRADESPAR", "8656": "MET GERDAU", "3980": "GERDAU", "24821": "REDE DOR",
    "19739": "LOCALIZA", "1023": "BB", "23159": "BBSE",
}

_linhas: list[str] = []


def p(*args) -> None:
    s = " ".join(str(a) for a in args)
    print(s)
    _linhas.append(s)


def sec(t: str) -> None:
    p("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


def _cd(s) -> str:
    return str(s).strip().lstrip("0")


def e_redutor_b3() -> None:
    sec("(e) B3: A CARTEIRA DO DIA TRAZ O REDUTOR?")
    try:
        params = {"language": "pt-br", "pageNumber": 1, "pageSize": 200,
                  "index": "IBOV", "segment": "1"}
        tok = base64.b64encode(json.dumps(params).encode()).decode()
        raw = get(B3_INDEX_PORTFOLIO + tok,
                  headers={"Accept": "application/json",
                           "Referer": "https://sistemaswebb3-listados.b3.com.br/"})
        payload = json.loads(raw.decode("utf-8"))
        p("chaves do payload:", list(payload))
        p("header:", json.dumps(payload.get("header"), ensure_ascii=False)[:800])
        p("page:", json.dumps(payload.get("page"), ensure_ascii=False)[:300])
        res = payload.get("results") or []
        for r in res[:3]:
            p("result:", json.dumps(r, ensure_ascii=False)[:400])
        p(f"n resultados: {len(res)}")
    except Exception as exc:  # noqa: BLE001
        p("FALHOU:", type(exc).__name__, str(exc)[:300])


def _zip(bases, arquivo):
    conteudo, _ = cvm._baixar(bases, arquivo)
    return zipfile.ZipFile(io.BytesIO(conteudo))


def _csv(zf: zipfile.ZipFile, contem: str) -> pd.DataFrame:
    nomes = [n for n in zf.namelist() if contem in n.lower() and n.lower().endswith(".csv")]
    frames = []
    for n in nomes:
        with zf.open(n) as fh:
            frames.append(pd.read_csv(fh, sep=";", encoding="latin-1", dtype=str,
                                      low_memory=False))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def f_contas_dre(rotulo: str, bases, arquivo: str) -> None:
    sec(f"(f) {rotulo}: CONTAS 3.11.x E 3.99.x NA DRE CONSOLIDADA")
    try:
        zf = _zip(bases, arquivo)
        p("arquivos no zip:", [n for n in zf.namelist()][:40])
        df = _csv(zf, "dre_con")
        df["cd"] = df["CD_CVM"].map(_cd)
        ult = df[df["ORDEM_EXERC"].str.strip().str.upper() == "ÚLTIMO"]
        m311 = ult[ult["CD_CONTA"].str.startswith("3.11")]
        m399 = ult[ult["CD_CONTA"].str.startswith("3.99")]
        p(f"companhias: {ult['cd'].nunique()} | com 3.11: {m311[m311['CD_CONTA']=='3.11']['cd'].nunique()}"
          f" | com 3.11.01: {m311[m311['CD_CONTA']=='3.11.01']['cd'].nunique()}"
          f" | com 3.99.*: {m399['cd'].nunique()}")
        p("descricoes distintas de 3.11.0x (top 8):")
        for (c, d), n in (m311[m311["CD_CONTA"] != "3.11"]
                          .groupby(["CD_CONTA", "DS_CONTA"]).size()
                          .sort_values(ascending=False).head(8).items()):
            p(f"   {c:<10} {str(d)[:55]:<55} {n}")
        p("descricoes distintas de 3.99.x (top 12):")
        for (c, d), n in (m399.groupby(["CD_CONTA", "DS_CONTA"]).size()
                          .sort_values(ascending=False).head(12).items()):
            p(f"   {c:<14} {str(d)[:50]:<50} {n}")
        cols = [c for c in ("CD_CONTA", "DS_CONTA", "VL_CONTA", "ESCALA_MOEDA",
                            "DT_INI_EXERC", "DT_FIM_EXERC") if c in ult.columns]
        for cd, nome in AMOSTRA.items():
            g = ult[(ult["cd"] == cd) & (ult["CD_CONTA"].str.match(r"^3\.(11|99)"))]
            if g.empty:
                p(f"-- {nome} ({cd}): sem linhas")
                continue
            p(f"-- {nome} ({cd}) {g['DENOM_CIA'].iloc[0][:40]} | CNPJ {g['CNPJ_CIA'].iloc[0] if 'CNPJ_CIA' in g else ''}")
            for _, r in g[cols].iterrows():
                p("    " + " | ".join(str(r[c])[:44] for c in cols))
    except Exception as exc:  # noqa: BLE001
        p("FALHOU:", type(exc).__name__, str(exc)[:300])


def g_composicao_capital(rotulo: str, bases, arquivo: str) -> None:
    sec(f"(g) {rotulo}: COMPOSICAO DO CAPITAL (NUMERO DE ACOES)")
    try:
        zf = _zip(bases, arquivo)
        cap = _csv(zf, "composicao_capital")
        if cap.empty:
            p("nao ha arquivo composicao_capital no zip")
            return
        p("colunas:", list(cap.columns))
        p(f"linhas: {len(cap)}")
        dre = _csv(zf, "dre_con")[["CNPJ_CIA", "CD_CVM"]].drop_duplicates()
        dre["cd"] = dre["CD_CVM"].map(_cd)
        cap = cap.merge(dre, on="CNPJ_CIA", how="left")
        for cd, nome in AMOSTRA.items():
            g = cap[cap["cd"] == cd]
            if g.empty:
                p(f"-- {nome} ({cd}): sem linha")
                continue
            p(f"-- {nome} ({cd}):", json.dumps(g.drop(columns=["CD_CVM"]).iloc[-1].to_dict(),
                                                ensure_ascii=False)[:600])
    except Exception as exc:  # noqa: BLE001
        p("FALHOU:", type(exc).__name__, str(exc)[:300])


def main() -> None:
    e_redutor_b3()
    f_contas_dre("DFP 2025", CVM_DFP_BASES, "dfp_cia_aberta_2025.zip")
    f_contas_dre("ITR 2026", CVM_ITR_BASES, "itr_cia_aberta_2026.zip")
    g_composicao_capital("DFP 2025", CVM_DFP_BASES, "dfp_cia_aberta_2025.zip")
    g_composicao_capital("ITR 2026", CVM_ITR_BASES, "itr_cia_aberta_2026.zip")
    PROCESSED.mkdir(parents=True, exist_ok=True)
    (PROCESSED / "diagnostico.txt").write_text("\n".join(_linhas), encoding="utf-8")


if __name__ == "__main__":
    main()
