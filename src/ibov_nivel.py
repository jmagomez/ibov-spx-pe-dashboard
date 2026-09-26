"""P/L do Ibovespa EM NIVEL, com a carteira vigente.

Ate 09/2026 o painel publicava, para o Ibovespa, so um indice de valuation
normalizado (base 100): preco do indice sobre a SOMA do lucro total das
companhias. Tres defeitos, todos corrigidos aqui:

  1. Lucro total nao e o lucro da carteira. O indice carrega uma FRACAO de
     cada companhia (a quantidade teorica, que segue o free float). Somar o
     lucro inteiro da Petrobras, com ~37% dela no indice, pesa a Petrobras
     mais do que o indice pesa. Aqui cada companhia entra com
     f = quantidade teorica / acoes em circulacao.
  2. Holding e controlada no indice (Itausa e Itau, Bradespar e Vale,
     Metalurgica Gerdau e Gerdau, Cosan e Rumo). Com a ponderacao por f, isso
     deixa de ser dupla contagem e passa a ser exatamente o que o indice e:
     ele carrega as duas, e o P/L do indice e soma(valor)/soma(lucro) das duas.
  3. Lucro consolidado inclui minoritarios das controladas. Aqui entra o lucro
     atribuivel aos socios da controladora (ver cvm._lucro_controladora).

A identidade usada:

    P/L = soma(q_i x P_i) / soma(q_i x LPA_i) = soma(q_i x P_i) / soma(f_c x L_c)

com q_i a quantidade teorica do papel, L_c o lucro de 12 meses da companhia
atribuivel a controladora, e f_c = soma dos q dos papeis da companhia (em
acoes) / acoes em circulacao. Uma unit (BPAC11 = 1 ON + 2 PN) conta como as
acoes que representa.

Duas medidas do numerador, que se conferem uma a outra:

  * indice x redutor (metodologia da B3: indice = soma(q x P) / redutor), que
    vale so para a carteira do dia -- o redutor muda a cada rebalanceamento;
  * soma(q x P) com o preco de cada papel (yfinance), que permite a serie
    historica com a carteira vigente congelada.

A serie historica herda o vies de sobrevivencia de sempre (carteira de hoje
aplicada ao passado), agora explicito de outro jeito: e o P/L que a carteira
ATUAL teria tido. Nao e o P/L historico do indice.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Composicao das units da carteira, em acoes (ON, PN). A B3 publica a unit como
# um papel; a CVM conta acoes. Unit fora desta tabela e EXCLUIDA do P/L em
# nivel (e aparece no relatorio), em vez de contada com composicao presumida.
UNITS = {
    "BPAC11": (1, 2),   # BTG Pactual: 1 ON + 2 PNA
    "ENGI11": (1, 4),   # Energisa
    "IGTI11": (1, 2),   # Iguatemi
    "KLBN11": (1, 4),   # Klabin
    "SANB11": (1, 1),   # Santander Brasil
    "TAEE11": (1, 2),   # Taesa
    "ALUP11": (1, 2),   # Alupar
    "SAPR11": (1, 4),   # Sanepar
}

# f fora desta faixa nao e fracao de companhia no indice: e numero de acoes em
# escala errada ou composicao de unit errada. Abaixo de 3% nenhuma companhia
# chega ao Ibovespa (o free float minimo e muito maior); acima de 105% a
# quantidade no indice excederia as acoes existentes.
F_MIN, F_MAX = 0.03, 1.05


def acoes_por_papel(codigo: str) -> float | None:
    """Quantas acoes da companhia um papel representa. None = unit desconhecida."""
    codigo = str(codigo).upper().strip()
    if codigo in UNITS:
        return float(sum(UNITS[codigo]))
    if codigo.endswith("11"):
        return None
    return 1.0


def _digitos(cnpj) -> str:
    return "".join(ch for ch in str(cnpj) if ch.isdigit())


def acoes_em_circulacao(acoes: pd.DataFrame, cnpj: str) -> tuple[float, str]:
    """(acoes em circulacao na escala do arquivo, data de referencia).

    Ultima data de referencia, ultima versao. Circulacao = integralizadas
    menos tesouraria.
    """
    if acoes is None or acoes.empty:
        return np.nan, ""
    alvo = _digitos(cnpj)
    g = acoes[acoes["cnpj"].map(_digitos) == alvo]
    if g.empty:
        return np.nan, ""
    g = g.sort_values(["data_ref", "versao"])
    r = g.iloc[-1]
    n = float(r["on"]) + float(r["pn"]) - float(r["tes_on"]) - float(r["tes_pn"])
    return (n if n > 0 else np.nan), str(pd.Timestamp(r["data_ref"]).date())


def fracao_na_carteira(q_acoes: float, n_bruto: float) -> tuple[float, float | None]:
    """(f, escala). Resolve a escala do numero de acoes (unidade ou milhar).

    O arquivo da CVM nao informa a escala e mistura as duas. A quantidade
    teorica da B3 decide: se ela exceder o numero de acoes lido, o numero esta
    em milhares. Se nenhuma escala der f plausivel, devolve NaN.
    """
    if not (q_acoes and n_bruto and n_bruto > 0 and np.isfinite(q_acoes)):
        return np.nan, None
    for escala in (1.0, 1_000.0):
        f = q_acoes / (n_bruto * escala)
        if F_MIN <= f <= F_MAX:
            return float(min(f, 1.0)), escala
    return np.nan, None


def montar_carteira(casadas: pd.DataFrame, acoes: pd.DataFrame,
                    cnpj_por_cd: dict) -> pd.DataFrame:
    """Uma linha por companhia: papeis, peso, q em acoes, acoes em circulacao, f.

    `casadas`: carteira conciliada (codigo, cd_cvm normalizado, qtd_teorica,
    participacao_pct). `cnpj_por_cd`: CNPJ que a propria CVM associa ao codigo
    CVM (o da B3 pode ser de outra entidade do grupo).
    """
    linhas = []
    for cd, g in casadas.groupby("cd_cvm"):
        motivos = []
        q = 0.0
        for _, r in g.iterrows():
            k = acoes_por_papel(r["codigo"])
            if k is None:
                motivos.append(f"unit {r['codigo']} sem composicao conhecida")
                q = np.nan
                break
            q += float(r["qtd_teorica"]) * k
        n_bruto, data_ref = acoes_em_circulacao(acoes, cnpj_por_cd.get(str(cd), ""))
        f, escala = (np.nan, None)
        if np.isnan(n_bruto):
            motivos.append("sem numero de acoes na CVM")
        elif not np.isnan(q):
            f, escala = fracao_na_carteira(q, n_bruto)
            if np.isnan(f):
                motivos.append(f"f implausivel (q={q:,.0f}; acoes={n_bruto:,.0f})")
        linhas.append({
            "cd_cvm": str(cd),
            "codigos": " ".join(sorted(g["codigo"].astype(str))),
            "peso_pct": float(g["participacao_pct"].sum()),
            "q_acoes": q,
            "acoes_circulacao": (n_bruto * escala) if escala else np.nan,
            "escala_acoes": escala,
            "data_acoes": data_ref,
            "f": f,
            "motivo_exclusao": "; ".join(motivos),
        })
    return pd.DataFrame(linhas)


def serie_pl(precos: pd.DataFrame, casadas: pd.DataFrame, carteira: pd.DataFrame,
             lucro_emp: pd.DataFrame, minimo: float = 0.80,
             ffill_limite: int = 5) -> pd.DataFrame:
    """P/L diario da carteira vigente: soma(q x P) / soma(f x L).

    Em cada data entram so as companhias com preco de TODOS os seus papeis e
    lucro vigente. A cobertura e medida em peso da carteira de hoje, e abaixo
    de `minimo` o P/L da data nao e publicado -- mesmo portao da serie antiga.
    Preco sem negocio no dia e repetido por ate `ffill_limite` pregoes; alem
    disso o papel sai da conta.
    """
    idx = lucro_emp.index
    px = precos.reindex(precos.index.union(idx)).ffill(limit=ffill_limite).reindex(idx)
    ok = carteira[np.isfinite(carteira["f"])]
    peso_total = float(carteira["peso_pct"].sum()) or 1.0
    valor = pd.Series(0.0, index=idx)
    lucro = pd.Series(0.0, index=idx)
    cobertura = pd.Series(0.0, index=idx)
    for _, c in ok.iterrows():
        papeis = casadas[casadas["cd_cvm"].astype(str) == c["cd_cvm"]]
        if c["cd_cvm"] not in lucro_emp.columns:
            continue
        v = pd.Series(0.0, index=idx)
        for _, r in papeis.iterrows():
            if r["codigo"] not in px.columns:
                v = pd.Series(np.nan, index=idx)
                break
            v = v + px[r["codigo"]] * float(r["qtd_teorica"])
        e = lucro_emp[c["cd_cvm"]] * float(c["f"])
        m = v.notna() & e.notna()
        valor = valor.add(v.where(m, 0.0))
        lucro = lucro.add(e.where(m, 0.0))
        cobertura = cobertura.add(m.astype(float) * float(c["peso_pct"]))
    cob = cobertura / peso_total
    pl = (valor / lucro.where(lucro > 0)).where(cob >= minimo)
    return pd.DataFrame({"pl": pl, "valor_carteira": valor.where(cob >= minimo),
                         "lucro_carteira": lucro.where(cob >= minimo),
                         "cobertura_pct": cob * 100.0})


def pl_pelo_redutor(indice: float, redutor: float, carteira: pd.DataFrame,
                    lucro_hoje: pd.Series) -> dict:
    """P/L de hoje com o numerador da propria B3: indice x redutor.

    Companhia sem f ou sem lucro sai do denominador E do numerador (pelo peso
    dela na carteira), para que as duas pontas descrevam o mesmo conjunto.
    """
    valor_total = float(indice) * float(redutor)
    peso_total = float(carteira["peso_pct"].sum()) or 1.0
    cob_peso, lucro_cob, linhas = 0.0, 0.0, []
    for _, c in carteira.iterrows():
        l12 = lucro_hoje.get(c["cd_cvm"], np.nan)
        valor_c = valor_total * c["peso_pct"] / peso_total
        entra = np.isfinite(c["f"]) and np.isfinite(l12)
        lucro_c = c["f"] * l12 if entra else np.nan
        if entra:
            cob_peso += c["peso_pct"]
            lucro_cob += lucro_c
        linhas.append({**c.to_dict(), "lucro_12m": l12, "valor_na_carteira": valor_c,
                       "lucro_na_carteira": lucro_c,
                       "pl_implicito": (valor_c / lucro_c) if entra and lucro_c > 0 else np.nan})
    cob = cob_peso / peso_total
    valor_cob = valor_total * cob
    return {
        "pl": (valor_cob / lucro_cob) if lucro_cob > 0 else np.nan,
        "valor_carteira": valor_total,
        "valor_coberto": valor_cob,
        "lucro_coberto": lucro_cob,
        "cobertura_pct": cob * 100.0,
        "tabela": pd.DataFrame(linhas),
    }
