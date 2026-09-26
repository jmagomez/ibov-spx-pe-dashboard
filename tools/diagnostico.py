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
como as duas primeiras foram descobertas. As quatro de diagnostico2.py tambem
foram respondidas. A pergunta aberta agora e a de diagnostico3.py: da para
calcular o P/L do Ibovespa em NIVEL (redutor da B3, LPA por classe na CVM)?
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import diagnostico3  # noqa: E402

if __name__ == "__main__":
    diagnostico3.main()
