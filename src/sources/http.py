"""Camada HTTP unica do projeto.

Regra do repositorio: se uma fonte nao responde, o coletor levanta excecao.
Nenhum modulo devolve valor default, ultimo valor conhecido silencioso, media,
interpolacao ou qualquer numero que nao tenha vindo da fonte. Um grafico vazio
e um resultado aceitavel; um grafico com numero inventado nao e.
"""
from __future__ import annotations

import logging
import socket
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

# --- IPv4 forcado -----------------------------------------------------------
# Na execucao #4 (08/08/2026) todas as chamadas a dados.cvm.gov.br a partir de um
# runner do GitHub Actions falharam com "[Errno 101] Network is unreachable".
# Esse erro aparece tipicamente quando o DNS devolve um registro AAAA e o host
# nao tem rota IPv6. Restringir a resolucao a AF_INET elimina essa hipotese.
# Se o erro persistir depois disto, a causa e bloqueio de rede na origem, e nao
# resolucao de nome -- distincao que importa para saber se ha o que consertar.
_getaddrinfo_original = socket.getaddrinfo


def _somente_ipv4(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
    return _getaddrinfo_original(host, port, socket.AF_INET, type, proto, flags)


def forcar_ipv4() -> None:
    socket.getaddrinfo = _somente_ipv4


forcar_ipv4()


class SourceUnavailable(RuntimeError):
    """A fonte nao respondeu ou respondeu em formato inesperado."""


def get(url: str, *, timeout: int = 60, retries: int = 3,
        backoff: float = 3.0, headers: Optional[dict] = None,
        connect_timeout: int = 12) -> bytes:
    """GET com retry exponencial. Levanta SourceUnavailable ao esgotar.

    `connect_timeout` e separado do timeout de leitura: sem isso, um host
    inalcancavel consome o timeout inteiro em cada tentativa. Na execucao #4
    foram cerca de tres minutos por ano da CVM -- quarenta minutos de job para
    descobrir algo que se sabe em segundos.
    """
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    last: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=hdrs, timeout=(connect_timeout, timeout))
            r.raise_for_status()
            if not r.content:
                raise SourceUnavailable(f"resposta vazia: {url}")
            log.info("OK  %s (%d bytes, tentativa %d)", url, len(r.content), attempt)
            return r.content
        except Exception as exc:  # noqa: BLE001
            last = exc
            log.warning("FALHA tentativa %d/%d em %s: %s", attempt, retries, url,
                        str(exc)[:200])
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise SourceUnavailable(f"{url} indisponivel apos {retries} tentativas: {last}")
