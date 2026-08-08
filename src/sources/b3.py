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

from ..config import B3_INDEX_PORTFOLIO
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
