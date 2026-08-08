"""Escreve o resumo da execucao no GitHub Step Summary."""
from __future__ import annotations

import json
import os
import pathlib
import sys

STATUS = pathlib.Path("data/processed/status.json")


def main() -> int:
    out = []
    if not STATUS.exists():
        out.append("## Resultado da coleta\n")
        out.append("`status.json` nao foi gerado - a coleta falhou antes de escrever "
                   "o diagnostico. Ver o log do passo `Coletar e processar`.\n")
    else:
        s = json.loads(STATUS.read_text(encoding="utf-8"))
        estagios = s.get("estagios", [])
        ok = sum(1 for e in estagios if e.get("ok"))
        out.append("## Resultado da coleta\n")
        out.append(f"Gerado em `{s.get('gerado_em_utc', '?')}` - "
                   f"**{ok}/{len(estagios)}** estagios com sucesso.\n")
        out.append("| Estagio | Situacao | Obs | Periodo | Detalhe |")
        out.append("|---|---|---:|---|---|")
        for e in estagios:
            periodo = (f"{e.get('inicio') or '?'} -> {e.get('fim') or '?'}"
                       if (e.get("inicio") or e.get("fim")) else "-")
            det = (e.get("detalhe") or "").replace("|", "\\|")[:180]
            out.append(f"| `{e['nome']}` | {'ok' if e.get('ok') else '**FALHOU**'} "
                       f"| {e.get('obs', 0)} | {periodo} | {det} |")
        for a in s.get("avisos", []):
            out.append(f"\n> {a}\n")
    texto = "\n".join(out) + "\n"
    print(texto)
    dest = os.environ.get("GITHUB_STEP_SUMMARY")
    if dest:
        with open(dest, "a", encoding="utf-8") as fh:
            fh.write(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
