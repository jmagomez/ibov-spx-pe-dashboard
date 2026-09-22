"""Estado global zerado entre testes.

O coletor da Shiller memoiza o download por URL: dentro de uma execucao do
pipeline a planilha e lida duas vezes (CAPE e LPA 12m) e nao ha motivo para
baixa-la duas vezes. Memoizacao, porem, e estado de processo -- e em pytest o
processo e um so para a suite inteira. Sem este fixture, um teste que substitui
`get` deixaria os bytes dele no cache e o teste seguinte leria a planilha do
vizinho, passando ou falhando por motivo errado.
"""
from __future__ import annotations

import pytest

from src.sources import shiller


@pytest.fixture(autouse=True)
def _limpar_cache_shiller():
    shiller._BYTES.clear()
    yield
    shiller._BYTES.clear()
