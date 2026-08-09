"""Conciliacao entre a carteira do Ibovespa (B3) e as companhias da CVM.

Por que CNPJ e nao razao social. A B3 devolve nome de pregao ("VALE", "ITAUUNIBANCO")
e a CVM devolve razao social ("VALE S.A.", "ITAU UNIBANCO HOLDING S.A."). Casar
os dois por texto normalizado acertou 39 dos 78 ativos -- 47,9% do peso do
indice -- e o portao de cobertura suprimiu a serie, corretamente. Nome nao e
chave: muda com reestruturacao, tem grafias concorrentes e nao distingue
empresas do mesmo grupo.

Por que CD_CVM e nao CNPJ como chave final. O CNPJ **muda**. Incorporacao,
mudanca de sede, sucessao societaria e migracao de registro trocam o numero, e
a serie de lucro de uma mesma companhia aparece sob dois CNPJs em anos
diferentes. Amarrar a conciliacao ao CNPJ vigente perderia todo o historico
anterior a troca -- silenciosamente, que e o pior modo de perder dado.

O codigo CVM (CD_CVM) sobrevive a essas trocas: e o registro da companhia
perante o regulador, nao a inscricao fiscal. Entao:

  - o CNPJ e usado para ENTRAR (e o unico identificador que a B3 publica);
  - o CD_CVM e a chave em que a conciliacao se apoia;
  - o mapa CNPJ -> CD_CVM e construido a partir de TODOS os anos coletados, e
    nao do cadastro vigente, de modo que um CNPJ antigo continue resolvendo.

As trocas encontradas sao reportadas, com os anos de cada numero. Nao sao
tratadas como erro: sao um fato do registro societario brasileiro, e o valor
esta em enxerga-las.
"""
from __future__ import annotations

import logging
import re
import unicodedata

import pandas as pd

log = logging.getLogger(__name__)


def normalizar_cnpj(v) -> str:
    """So os digitos, com 14 posicoes. Devolve "" quando nao ha CNPJ utilizavel.

    A CVM publica o CNPJ formatado ("33.000.167/0001-01") e a B3, quando publica,
    usa ora formatado ora so digitos, as vezes sem os zeros a esquerda.
    """
    d = re.sub(r"\D", "", str(v or ""))
    if not d or len(d) > 14:
        return ""
    d = d.zfill(14)
    return "" if d == "0" * 14 else d


def raiz_ticker(codigo: str) -> str:
    """VALE3 -> VALE; PETR4 -> PETR. A raiz de 4 letras identifica o emissor."""
    letras = re.sub(r"[^A-Za-z]", "", str(codigo or "")).upper()
    return letras[:4]


def _norm_nome(txt: str) -> str:
    t = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode().upper()
    for suf in (" S.A.", " S/A", " SA", " S.A", " LTDA", " HOLDING", " PARTICIPACOES",
                " PARTICIPACOES E INVESTIMENTOS", " CIA", " COMPANHIA", " DO BRASIL"):
        t = t.replace(suf, " ")
    return " ".join(t.split())


def mapa_cnpj_cdcvm(lucros: pd.DataFrame) -> tuple[dict, list, list]:
    """Constroi CNPJ -> CD_CVM a partir de todas as observacoes coletadas.

    Devolve (mapa, trocas, ambiguos).

      trocas   - um CD_CVM visto com mais de um CNPJ ao longo do tempo. E o caso
                 que motiva este modulo. Ambos os CNPJs entram no mapa, para que
                 o historico anterior a troca continue resolvendo.
      ambiguos - um CNPJ apontando para mais de um CD_CVM. Nao deveria ocorrer;
                 se ocorrer, o CNPJ e RECUSADO em vez de resolvido por desempate
                 arbitrario. Preferir nenhuma resposta a uma resposta inventada.
    """
    if lucros.empty or "cnpj" not in lucros.columns:
        return {}, [], []

    pares = lucros[["cnpj", "cd_cvm", "data_fim"]].dropna(subset=["cnpj", "cd_cvm"]).copy()
    pares["cnpj"] = pares["cnpj"].map(normalizar_cnpj)
    pares = pares[pares["cnpj"] != ""]
    if pares.empty:
        return {}, [], []
    pares["cd_cvm"] = pares["cd_cvm"].astype(str).str.strip()

    trocas = []
    for cd, g in pares.groupby("cd_cvm"):
        cnpjs = sorted(g["cnpj"].unique())
        if len(cnpjs) > 1:
            detalhe = {}
            for c in cnpjs:
                datas = g.loc[g["cnpj"] == c, "data_fim"]
                detalhe[c] = f"{datas.min().date()}..{datas.max().date()}"
            trocas.append({"cd_cvm": cd, "cnpjs": detalhe})

    ambiguos, mapa = [], {}
    for cnpj, g in pares.groupby("cnpj"):
        cds = sorted(g["cd_cvm"].unique())
        if len(cds) > 1:
            ambiguos.append({"cnpj": cnpj, "cd_cvm": cds})
            continue
        mapa[cnpj] = cds[0]

    if trocas:
        log.info("CNPJ trocado ao longo do tempo em %d companhias; ambos os numeros "
                 "resolvem para o mesmo CD_CVM", len(trocas))
    if ambiguos:
        log.warning("%d CNPJ(s) apontando para mais de um CD_CVM; recusados", len(ambiguos))
    return mapa, trocas, ambiguos


def conciliar(composicao: pd.DataFrame, empresas_b3: pd.DataFrame,
              lucros: pd.DataFrame) -> tuple[pd.DataFrame, float, dict]:
    """Liga carteira -> CNPJ -> CD_CVM. Devolve (casadas, cobertura_por_peso, relatorio).

    `empresas_b3` e a ponte: a carteira do indice traz o codigo de negociacao,
    mas nao o CNPJ; o cadastro de companhias listadas traz os dois.

    A cobertura e medida POR PESO, nao por contagem de ativos. Vinte ativos
    pequenos conciliados nao compensam a ausencia de um que sozinho responde por
    um decimo do indice.
    """
    rel = {"por_cnpj": 0, "por_nome": 0, "sem_correspondencia": [],
           "trocas_de_cnpj": [], "cnpj_ambiguo": []}
    if composicao.empty or lucros.empty:
        return pd.DataFrame(), 0.0, rel

    mapa, trocas, ambiguos = mapa_cnpj_cdcvm(lucros)
    rel["trocas_de_cnpj"], rel["cnpj_ambiguo"] = trocas, ambiguos

    # raiz do ticker -> CNPJ, a partir do cadastro de listadas da B3
    raiz_para_cnpj = {}
    if not empresas_b3.empty and {"raiz", "cnpj"} <= set(empresas_b3.columns):
        for _, r in empresas_b3.iterrows():
            c = normalizar_cnpj(r["cnpj"])
            if r["raiz"] and c:
                raiz_para_cnpj[str(r["raiz"]).upper()] = c

    # razao social -> cd_cvm, so para o resto que o CNPJ nao resolver
    nome_para_cd = {}
    if "empresa" in lucros.columns:
        for _, r in lucros[["empresa", "cd_cvm"]].dropna().drop_duplicates().iterrows():
            nome_para_cd.setdefault(_norm_nome(r["empresa"]), str(r["cd_cvm"]).strip())

    linhas = []
    peso_total = float(composicao.get("participacao_pct", pd.Series(dtype=float)).sum() or 0.0)
    peso_casado = 0.0
    for _, row in composicao.iterrows():
        cod = str(row.get("codigo", ""))
        peso = float(row.get("participacao_pct") or 0.0)
        raiz = raiz_ticker(cod)
        cnpj = raiz_para_cnpj.get(raiz, "")
        cd = mapa.get(cnpj, "") if cnpj else ""
        via = "cnpj" if cd else ""
        if not cd:
            cd = nome_para_cd.get(_norm_nome(row.get("empresa", "")), "")
            via = "nome" if cd else ""
        if cd:
            linhas.append({"codigo": cod, "raiz": raiz, "cnpj": cnpj, "cd_cvm": cd,
                           "via": via, "participacao_pct": peso})
            peso_casado += peso
            rel["por_cnpj" if via == "cnpj" else "por_nome"] += 1
        else:
            rel["sem_correspondencia"].append({"codigo": cod, "peso": round(peso, 3)})

    casadas = pd.DataFrame(linhas)
    cobertura = peso_casado / peso_total if peso_total > 0 else 0.0
    rel["cobertura_por_peso"] = round(cobertura, 4)
    rel["ativos"] = f"{len(casadas)}/{len(composicao)}"
    return casadas, cobertura, rel
