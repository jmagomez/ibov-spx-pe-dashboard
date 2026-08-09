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


def diagnosticar(url: str, *, connect_timeout: int = 10) -> dict:
    """Separa os estagios de uma conexao para dizer ONDE ela quebra.

    "HTTPSConnectionPool ... Max retries exceeded" e um diagnostico inutil: cabe
    igualmente em DNS que nao resolve, rota que nao existe, porta filtrada e TLS
    recusado. Esta funcao testa os quatro em sequencia e devolve o primeiro que
    falha, com o errno. E a diferenca entre "ha o que consertar aqui" e "o host
    bloqueia a faixa de IP do runner, va para o plano B".
    """
    from urllib.parse import urlparse
    u = urlparse(url)
    host = u.hostname or ""
    porta = u.port or (443 if u.scheme == "https" else 80)
    d = {"url": url, "host": host, "porta": porta}
    try:
        infos = _getaddrinfo_original(host, porta, socket.AF_INET, socket.SOCK_STREAM)
        d["dns"] = sorted({i[4][0] for i in infos})
    except Exception as exc:  # noqa: BLE001
        d["dns"] = f"FALHA: {type(exc).__name__}: {exc}"
        return d
    try:
        sk = socket.create_connection((d["dns"][0], porta), timeout=connect_timeout)
        d["tcp"] = "ok"
    except Exception as exc:  # noqa: BLE001
        d["tcp"] = f"FALHA: {type(exc).__name__}: {getattr(exc, 'errno', '')} {exc}"
        return d
    try:
        if u.scheme == "https":
            import ssl
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(sk, server_hostname=host) as ss:
                d["tls"] = ss.version()
        else:
            d["tls"] = "n/a"
            sk.close()
    except Exception as exc:  # noqa: BLE001
        d["tls"] = f"FALHA: {type(exc).__name__}: {exc}"
        return d
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=(connect_timeout, 30),
                         stream=True)
        d["http"] = r.status_code
        d["content_type"] = r.headers.get("Content-Type", "")
        r.close()
    except Exception as exc:  # noqa: BLE001
        d["http"] = f"FALHA: {type(exc).__name__}: {exc}"
    return d


def get_qualquer(urls, **kw) -> tuple[bytes, str]:
    """Tenta uma lista de URLs equivalentes; devolve o conteudo e a URL que serviu.

    Existe para espelhos e para alternar entre esquemas (https/http) do mesmo
    host. Nao e fallback de VALOR -- e alternancia de ENDERECO para o mesmo
    dado, e quem serviu fica registrado no diagnostico.
    """
    erros = []
    for u in urls:
        try:
            return get(u, **kw), u
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{u} -> {type(exc).__name__}: {str(exc)[:160]}")
    raise SourceUnavailable(" || ".join(erros))


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
            log.warning("FALHA tentativa %d/%d em %s: %s: %s", attempt, retries, url,
                        type(exc).__name__, str(exc)[:300])
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise SourceUnavailable(
        f"{url} indisponivel apos {retries} tentativas: "
        f"{type(last).__name__}: {last}")
