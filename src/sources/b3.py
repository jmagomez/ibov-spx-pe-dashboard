"""Composicao vigente do Ibovespa, via portal de indices da B3.

Limitacao central e assumida: a B3 nao publica, em formato aberto, o historico
de composicao da carteira desde 2010. O que se obtem aqui e a carteira VIGENTE.
Aplicar a carteira de hoje ao passado introduz vies de sobrevivencia. Ver
LIMITACOES.md, secao 2. Nao ha contorno gratuito para isso; o projeto declara o
vies em vez de disfarca-lo.
"""
from __future__ import annotations

import base64
import json
import logging

import pandas as pd

from ..config import B3_INDEX_PORTFOLIO, B3_LISTED_COMPANIES
from .http import SourceUnavailable, get

log = logging.getLogger(__name__)


def fetch_ibov_composition() -> pd.DataFrame:
    """DataFrame com codigo, empresa, tipo, quantidade teorica e participacao (%).

    O endpoint da B3 recebe os parametros como JSON codificado em base64 no path.
    E um endpoint interno do portal, sem contrato publico de estabilidade: se a
    B3 mudar a interface, este coletor quebra. Isso esta registrado como risco
    conhecido em LIMITACOES.md, secao 5.
    """
    params = {"language": "pt-br", "pageNumber": 1, "pageSize": 200, "index": "IBOV",
              "segment": "1"}
    token = base64.b64encode(json.dumps(params).encode()).decode()
    raw = get(B3_INDEX_PORTFOLIO + token,
              headers={"Accept": "application/json",
                       "Referer": "https://sistemaswebb3-listados.b3.com.br/"})
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SourceUnavailable(f"resposta da B3 nao e JSON valido: {exc}") from exc

    results = payload.get("results")
    if not results:
        raise SourceUnavailable(f"payload da B3 sem 'results': chaves={list(payload)}")

    df = pd.DataFrame(results)
    rename = {"cod": "codigo", "asset": "empresa", "type": "tipo",
              "theoricalQty": "qtd_teorica", "part": "participacao_pct"}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    for col in ("qtd_teorica", "participacao_pct"):
        if col in df.columns:
            df[col] = (df[col].astype(str)
                       .str.replace(".", "", regex=False)
                       .str.replace(",", ".", regex=False))
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "codigo" not in df.columns:
        raise SourceUnavailable(f"payload da B3 sem coluna de codigo: {list(df.columns)}")
    log.info("Ibovespa: %d ativos na carteira vigente", len(df))
    return df


def fetch_empresas_listadas() -> pd.DataFrame:
    """Cadastro de companhias listadas: raiz do codigo, CNPJ e codigo CVM.

    A carteira do indice traz o codigo (VALE3) e o nome de pregao (VALE); nao
    traz CNPJ nem codigo CVM. A CVM identifica companhia por CNPJ e codigo CVM;
    nao conhece codigo de negociacao. Este cadastro e o unico ponto em que os
    dois universos se tocam, e por isso a conciliacao depende dele.

    PAGINADO. Pedir pageSize=500 devolveu `{"page": ..., "results": []}` -- uma
    resposta HTTP 200, bem formada, e vazia. O endpoint tem um teto de pagina e,
    acima dele, nao recusa o pedido: devolve nada. Foi assim que a execucao #8
    caiu para conciliacao por razao social sem que a causa fosse obvia. O laco
    abaixo pede paginas pequenas e usa o total informado pelo proprio payload.

    Endpoint interno do portal, sem contrato publico -- mesmo risco ja registrado
    para a carteira. Se a resposta vier sem os campos esperados, a funcao levanta
    excecao com a lista de campos recebidos, para que a mudanca de layout apareca
    no diagnostico em vez de virar cobertura baixa sem explicacao.
    """
    linhas, pagina, total_paginas, campos = [], 1, 1, []
    while pagina <= total_paginas and pagina <= 20:
        params = {"language": "pt-br", "pageNumber": pagina, "pageSize": 100}
        token = base64.b64encode(json.dumps(params).encode()).decode()
        raw = get(B3_LISTED_COMPANIES + token,
                  headers={"Accept": "application/json",
                           "Referer": "https://sistemaswebb3-listados.b3.com.br/"})
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise SourceUnavailable(f"cadastro da B3 nao e JSON valido: {exc}") from exc

        page_info = payload.get("page") or {}
        total_paginas = int(page_info.get("totalPages") or 1)
        res = payload.get("results") or []
        if not res:
            if pagina == 1:
                raise SourceUnavailable(
                    f"cadastro da B3 devolveu lista vazia na pagina 1; "
                    f"page={page_info}, chaves={list(payload)}")
            break
        campos = list(res[0].keys())
        linhas.extend(res)
        pagina += 1

    if not linhas:
        raise SourceUnavailable("cadastro da B3 sem nenhum registro")

    df = pd.DataFrame(linhas)
    campos = list(df.columns)

    def _escolher(preferencia: tuple) -> str | None:
        """Escolhe por ORDEM DE PREFERENCIA, nao pela ordem das colunas.

        A versao anterior usava next(c for c in campos if c.lower() in {...}),
        que devolve a primeira COLUNA do payload cujo nome esteja no conjunto --
        a prioridade era a da B3, nao a minha. Como codeCVM vem antes de
        issuingCompany na resposta, a raiz foi extraida de um numero, sobrou
        string vazia em todas as linhas, o filtro apagou tudo e o estagio
        terminou "ok" com zero registros. Falha silenciosa: o pior desfecho.
        """
        for alvo in preferencia:
            for c in campos:
                if c.lower() == alvo:
                    return c
        return None

    col_cnpj = _escolher(("cnpj", "companycnpj"))
    col_raiz = _escolher(("issuingcompany", "tradingname", "code"))
    col_cd = _escolher(("codecvm", "cvmcode"))
    if col_cnpj is None or col_raiz is None:
        raise SourceUnavailable(
            f"cadastro da B3 sem campo de CNPJ ou de codigo; campos recebidos: {campos}")

    out = pd.DataFrame({
        "raiz": df[col_raiz].astype(str).str.upper().str.replace(r"[^A-Z]", "", regex=True).str[:4],
        "cnpj": df[col_cnpj].astype(str).map(lambda v: "" if v.lower() in ("none", "nan") else v),
        # codeCVM e a ligacao DIRETA com o registro na CVM -- mais forte que o
        # CNPJ, porque nao depende de qual entidade do grupo a B3 escolheu
        # cadastrar. Foi o que faltava para ITUB, PETR e outros pesos pesados.
        "cd_cvm": (df[col_cd].astype(str).str.replace(r"\D", "", regex=True).str.lstrip("0")
                   if col_cd else ""),
        "nome": df.get("companyName", pd.Series([""] * len(df))).astype(str),
    })
    # Basta UM identificador utilizavel. Exigir CNPJ descartaria companhias que
    # so trazem codeCVM -- e o codeCVM e justamente a ligacao mais forte.
    out = out[(out["raiz"] != "") & ((out["cnpj"] != "") | (out["cd_cvm"] != ""))]
    out = out.drop_duplicates("raiz")

    # Estagio "ok" com zero linhas nao e sucesso: e uma falha que nao avisou.
    # Depois de ter recebido registros da B3, uma tabela vazia so pode vir de
    # leitura errada dos campos, e isso precisa aparecer como erro.
    if out.empty:
        amostra = {c: str(df[c].iloc[0])[:40] for c in campos[:10]}
        raise SourceUnavailable(
            f"cadastro da B3: {len(df)} registros recebidos mas nenhum par "
            f"(codigo, identificador) utilizavel. Campos={campos}; colunas "
            f"escolhidas={col_raiz}/{col_cnpj}/{col_cd}; primeira linha={amostra}")

    log.info("B3: %d companhias listadas em %d pagina(s) (campos: %s / %s / %s)",
             len(out), pagina - 1, col_raiz, col_cnpj, col_cd)
    return out
