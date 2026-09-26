"""Aplica o teto de validade retroativamente aos CSVs ja processados.

Existe para um caso especifico: os dados publicados em 08/08/2026 foram gerados
antes de o teto existir, e por isso trazem o LPA de 03/06/2024 repetido por 795
dias. Enquanto a proxima coleta nao acontece, este utilitario corrige o que ja
esta em disco -- truncando as series onde a fonte de fato parou e recalculando
tudo que depende delas.

Nao inventa nem completa nada: apenas APAGA o trecho que nunca teve lastro.

Uso: python -m tools.reparar_validade   (ou python tools/reparar_validade.py)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import metrics                                            # noqa: E402
from src.config import (MAX_STALE_DAYS_CAPE, MAX_STALE_DAYS_EPS_MENSAL,  # noqa: E402
                        PROCESSED, STAT_WINDOW)


def ultima_mudanca(s: pd.Series) -> pd.Timestamp:
    """Ultima data em que uma serie-degrau efetivamente mudou de valor.

    E o que permite recuperar, a partir do CSV diario ja preenchido, a data em
    que a fonte mensal/trimestral parou de ser atualizada.
    """
    v = s.dropna()
    if v.empty:
        return pd.NaT
    mud = v[v.diff().fillna(1) != 0]
    return mud.index.max() if not mud.empty else v.index.min()


def truncar(s: pd.Series, teto_dias: int) -> tuple[pd.Series, dict]:
    fim = ultima_mudanca(s)
    if pd.isna(fim):
        return s, {}
    limite = fim + pd.Timedelta(days=teto_dias)
    cortados = int((s.notna() & (s.index > limite)).sum())
    return s.where(s.index <= limite), {
        "ultima_mudanca": str(fim.date()),
        "vigente_ate": str(limite.date()),
        "pregoes_removidos": cortados,
    }


def main() -> int:
    p = PROCESSED / "spx.csv"
    if not p.exists():
        print("nada a reparar: spx.csv ausente")
        return 0
    d = pd.read_csv(p, parse_dates=["data"]).set_index("data")
    rel = {}

    for col, teto in (("eps_ttm", MAX_STALE_DAYS_EPS_MENSAL),
                      ("eps_ttm_pit", MAX_STALE_DAYS_EPS_MENSAL),
                      ("cape", MAX_STALE_DAYS_CAPE)):
        if col in d.columns:
            d[col], info = truncar(d[col], teto)
            if info:
                rel[col] = info

    # CAPE fora da faixa historica nao e CAPE: e outra coluna da planilha. Os
    # dados de 08/08/2026 trazem valores entre 0,01 e 0,06, compativeis com o
    # "Excess CAPE Yield" e nao com o multiplo. Nao renomeio a serie por conta
    # propria -- a suposicao e forte e a coleta seguinte resolve a duvida. Aqui
    # ela e apenas retirada do ar, com o motivo registrado.
    if "cape" in d.columns:
        from src.config import CAPE_MAX_PLAUSIVEL, CAPE_MIN_PLAUSIVEL
        v = d["cape"].dropna()
        if v.size and not (CAPE_MIN_PLAUSIVEL <= float(v.median()) <= CAPE_MAX_PLAUSIVEL):
            rel["cape_implausivel"] = {
                "mediana_encontrada": round(float(v.median()), 6),
                "faixa_exigida": [CAPE_MIN_PLAUSIVEL, CAPE_MAX_PLAUSIVEL],
                "acao": "serie suprimida ate a proxima coleta identificar a coluna certa",
            }
            d["cape"] = float("nan")

    # Tudo que descende do LPA e recalculado a partir da serie ja truncada.
    if "eps_ttm" in d.columns:
        d["pe"] = metrics.pe_ratio(d["preco"], d["eps_ttm"])
        d["earnings_yield"] = metrics.earnings_yield(d["pe"])
        d["pe_z"] = metrics.rolling_zscore(d["pe"], STAT_WINDOW)
        d["pe_pct"] = metrics.rolling_percentile(d["pe"], STAT_WINDOW)
    if "eps_ttm_pit" in d.columns:
        d["pe_pit"] = metrics.pe_ratio(d["preco"], d["eps_ttm_pit"])
    # Idem para o que descende do earnings yield e do CAPE: sem isto, um
    # truncamento aqui deixaria os premios sobre juro calculados com o LPA de
    # antes do reparo.
    if "tips10" in d.columns and "earnings_yield" in d.columns:
        d["ey_menos_real"] = metrics.premio_sobre_juro(d["earnings_yield"], d["tips10"])
    if "ust10" in d.columns and "earnings_yield" in d.columns:
        d["ey_menos_nominal"] = metrics.premio_sobre_juro(d["earnings_yield"], d["ust10"])
    if "cape" in d.columns and "cape_yield" in d.columns:
        d["cape_yield"] = 100.0 / d["cape"].where(d["cape"] > 0)
        if "tips10" in d.columns:
            d["cape_yield_menos_real"] = metrics.premio_sobre_juro(d["cape_yield"], d["tips10"])

    d.round(6).to_csv(p, index_label="data")

    # O reparo entra no status.json para aparecer no painel de diagnostico.
    sp = PROCESSED / "status.json"
    if sp.exists():
        st = json.loads(sp.read_text(encoding="utf-8"))
        st["reparo_validade"] = rel
        # O aviso so entra quando o reparo de fato removeu algo. Ate 26/09/2026
        # ele era anexado em TODA execucao, inclusive nas que nao mexiam em nada,
        # e aparecia todo dia no resumo por e-mail descrevendo um reparo de
        # 08/08/2026 como se estivesse acontecendo agora.
        removeu = any(int(v.get("pregoes_removidos", 0) or 0) > 0 for v in rel.values()
                      if isinstance(v, dict)) or "cape_implausivel" in rel
        if removeu:
            st.setdefault("avisos", []).append(
                "Teto de validade aplicado aos dados em disco: havia trecho de LPA ou "
                "CAPE sem lastro, que foi esvaziado e nao corrigido por estimativa. "
                "Detalhe em status.json, campo reparo_validade.")
        sp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

    for k, v in rel.items():
        if "vigente_ate" in v:
            print(f"{k:18s} vigente ate {v['vigente_ate']} "
                  f"({v['pregoes_removidos']} pregoes sem lastro removidos)")
        else:
            print(f"{k:18s} {v.get('acao', v)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
