"""Camada HTTP unica do projeto.

Regra do repositorio: se uma fonte nao responde, o coletor levanta excecao.
Nenhum modulo devolve valor default, ultimo valor conhecido silencioso, media,
interpolacao ou qualquer numero que nao tenha vindo da fonte. Um grafico vazio
e um resultado aceitavel; um grafico com numero inventado nao e.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


class SourceUnavailable(RuntimeError):
    """A fonte nao respondeu ou respondeu em formato inesperado."""


def get(url: str, *, timeout: int = 60, retries: int = 3,
        backoff: float = 3.0, headers: Optional[dict] = None) -> bytes:
    """GET com retry exponencial. Levanta SourceUnavailable ao esgotar."""
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    last: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=hdrs, timeout=timeout)
            r.raise_for_status()
            if not r.content:
                raise SourceUnavailable(f"resposta vazia: {url}")
            log.info("OK  %s (%d bytes, tentativa %d)", url, len(r.content), attempt)
            return r.content
        except Exception as exc:  # noqa: BLE001 - queremos capturar tudo e reportar
            last = exc
            log.warning("FALHA tentativa %d/%d em %s: %s", attempt, retries, url, exc)
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise SourceUnavailable(f"{url} indisponivel apos {retries} tentativas: {last}")
