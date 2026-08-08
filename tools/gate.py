"""Falha a execucao apenas se NENHUMA fonte respondeu.

Falha parcial e estado legitimo: o dashboard mostra o que existe e declara o
que faltou. Falha total, nao -- ai o silencio seria enganoso.
"""
from __future__ import annotations

import json
import pathlib
import sys

STATUS = pathlib.Path("data/processed/status.json")


def main() -> int:
    if not STATUS.exists():
        print("status.json ausente: nenhuma fonte foi coletada.")
        return 1
    s = json.loads(STATUS.read_text(encoding="utf-8"))
    estagios = s.get("estagios", [])
    ok = sum(1 for e in estagios if e.get("ok"))
    print(f"{ok}/{len(estagios)} estagios com sucesso")
    if not ok:
        print("Nenhuma fonte respondeu. Falhando a execucao.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
