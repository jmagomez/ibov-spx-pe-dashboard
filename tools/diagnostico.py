"""Ponto de entrada do diagnostico executado no runner.

O runner alcanca B3, CVM e a planilha do Shiller; o ambiente onde este codigo e
escrito, nao. Sem ver a resposta real dessas fontes, qualquer correcao vira
chute -- e ja errei duas vezes assim antes de criar este arquivo.

As duas perguntas originais (qual coluna traz o CAPE, e por que 22 ativos nao
conciliavam) foram respondidas e viraram correcao com teste. O que roda agora
sao as quatro perguntas abertas, em diagnostico2.py:

  (a) existe fonte de LPA do S&P mais recente que 06/2024?
  (b) quais anos de DFP falham, e por que?
  (c) qual a cobertura POR PESO ao longo do tempo?
  (d) a CVM publica lucro por acao, e a B3 quantidade teorica?

O arquivo diagnostico_cape_conciliacao.py fica no repositorio como registro de
como as duas primeiras foram descobertas.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from diagnostico2 import (a_fontes_de_lpa, b_anos_de_dfp,       # noqa: E402
                          c_cobertura_no_tempo, d_lucro_por_acao)

if __name__ == "__main__":
    a_fontes_de_lpa()
    b_anos_de_dfp()
    d_lucro_por_acao()
    c_cobertura_no_tempo()
