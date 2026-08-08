"""Orquestrador do pipeline.

Principios que governam este arquivo:

1. Cada estagio e independente. A falha de um nao derruba os demais; ela e
   registrada em data/processed/status.json e exibida no dashboard.
2. Nenhum estagio produz numero que nao tenha vindo de uma fonte. Nao ha
   fallback com media, interpolacao de lucro, valor default ou ultimo valor
   conhecido travado. Alternar entre FONTES documentadas e outra coisa: a fonte
   efetivamente usada aparece no diagnostico.
3. Series com lastro insuficiente sao SUPRIMIDAS, nao publicadas com ressalva
   em letra miuda. O portao de cobertura do Ibovespa implementa isso.
"""
from __future__ import annotations

import json
import logging
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import metrics
from .config import (PROCESSED, REPORTING_LAG_DAYS_INDEX, REPORTING_LAG_DAYS_PIT,
                     STAT_WINDOW)
from .sources import b3, cvm, prices, shiller, spdji

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s")
log = logging.getLogger("build")

# Fracao minima do peso do Ibovespa que precisa ter lucro conciliado para que a
# serie do IBOV seja publicada. Abaixo disso o agregado nao representa o indice
# e a serie e suprimida.
COBERTURA_MINIMA_IBOV = 0.80


@dataclass
class Stage:
    nome: str
    ok: bool = False
    detalhe: str = ""
    obs: int = 0
    inicio: str = ""
    fim: str = ""


@dataclass
class Status:
    gerado_em_utc: str = ""
    estagios: list = field(default_factory=list)
    avisos: list = field(default_factory=list)

    def add(self, s: Stage) -> None:
        self.estagios.append(asdict(s))


def _norm(txt: str) -> str:
    """Normaliza razao social para conciliacao: sem acento, sem sufixo societario."""
    t = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode().upper()
    for suf in (" S.A.", " S/A", " SA", " S.A", " LTDA", " HOLDING", " PARTICIPACOES",
                " PARTICIPACOES E INVESTIMENTOS", " CIA", " COMPANHIA", " DO BRASIL"):
        t = t.replace(suf, " ")
    return " ".join(t.split())


# ---------------------------------------------------------------------------
# S&P 500
# ---------------------------------------------------------------------------

def build_spx(status: Status) -> pd.DataFrame:
    out = pd.DataFrame()

    st = Stage("precos_spx")
    try:
        px, provedor = prices.fetch_index_close("spx")
        out["preco"] = px
        st.ok, st.obs = True, len(px)
        st.detalhe = provedor
        st.inicio, st.fim = str(px.index.min().date()), str(px.index.max().date())
    except Exception as exc:  # noqa: BLE001
        st.detalhe = str(exc)
        log.error("precos_spx falhou: %s", exc)
    status.add(st)
    if out.empty:
        return out

    # LPA do indice: fonte primaria e a S&P DJI; a planilha Shiller e a
    # alternativa. Nao e "fallback com valor default" -- e outra fonte, com
    # linhagem declarada, e o painel de diagnostico diz qual foi usada.
    st = Stage("eps_spx")
    erros_eps = []
    try:
        q = spdji.fetch_sp500_quarterly_eps()
        col = "eps_as_reported" if "eps_as_reported" in q.columns else "eps_operating"
        ttm = metrics.ttm_from_quarterly(q[col])
        out["eps_ttm"] = metrics.step_to_daily(ttm, out.index, REPORTING_LAG_DAYS_INDEX)
        out["eps_ttm_pit"] = metrics.step_to_daily(ttm, out.index, REPORTING_LAG_DAYS_PIT)
        if "eps_operating" in q.columns and col != "eps_operating":
            ttm_op = metrics.ttm_from_quarterly(q["eps_operating"])
            out["eps_ttm_operating"] = metrics.step_to_daily(
                ttm_op, out.index, REPORTING_LAG_DAYS_INDEX)
        st.ok, st.obs = True, int(out["eps_ttm"].notna().sum())
        st.detalhe = f"fonte: S&P Dow Jones Indices ({col}), trimestral"
    except Exception as exc:  # noqa: BLE001
        erros_eps.append(f"spdji: {str(exc)[:150]}")
        log.warning("EPS via S&P DJI indisponivel: %s", str(exc)[:200])
        try:
            # A coluna E da planilha Shiller JA e LPA acumulado em 12 meses:
            # entra direto, sem soma movel de quatro trimestres.
            eps_m = shiller.fetch_eps_ttm()
            out["eps_ttm"] = metrics.step_to_daily(eps_m, out.index, 0)
            out["eps_ttm_pit"] = metrics.step_to_daily(
                eps_m, out.index, REPORTING_LAG_DAYS_PIT)
            st.ok, st.obs = True, int(out["eps_ttm"].notna().sum())
            st.detalhe = ("fonte: planilha Shiller (coluna E, LPA 12m mensal) -- "
                          "S&P DJI indisponivel")
        except Exception as exc2:  # noqa: BLE001
            erros_eps.append(f"shiller: {str(exc2)[:150]}")
            st.detalhe = " | ".join(erros_eps)
            log.error("nenhuma fonte de EPS respondeu: %s", erros_eps)
    status.add(st)

    if "eps_ttm" in out.columns:
        out["pe"] = metrics.pe_ratio(out["preco"], out["eps_ttm"])
        out["pe_pit"] = metrics.pe_ratio(out["preco"], out["eps_ttm_pit"])
        if "eps_ttm_operating" in out.columns:
            out["pe_operating"] = metrics.pe_ratio(out["preco"], out["eps_ttm_operating"])
        out["earnings_yield"] = metrics.earnings_yield(out["pe"])
        out["pe_z"] = metrics.rolling_zscore(out["pe"], STAT_WINDOW)
        out["pe_pct"] = metrics.rolling_percentile(out["pe"], STAT_WINDOW)

    st = Stage("cape_shiller")
    try:
        cape = shiller.fetch_cape()
        out["cape"] = metrics.step_to_daily(cape, out.index, 0)
        st.ok, st.obs = True, len(cape)
        st.inicio, st.fim = str(cape.index.min().date()), str(cape.index.max().date())
    except Exception as exc:  # noqa: BLE001
        st.detalhe = str(exc)
        log.error("cape_shiller falhou: %s", exc)
    status.add(st)
    return out


# ---------------------------------------------------------------------------
# Ibovespa
# ---------------------------------------------------------------------------

def build_ibov(status: Status):
    out, comp = pd.DataFrame(), pd.DataFrame()

    st = Stage("precos_ibov")
    try:
        px, provedor = prices.fetch_index_close("ibov")
        out["preco"] = px
        st.ok, st.obs = True, len(px)
        st.detalhe = provedor
        st.inicio, st.fim = str(px.index.min().date()), str(px.index.max().date())
    except Exception as exc:  # noqa: BLE001
        st.detalhe = str(exc)
        log.error("precos_ibov falhou: %s", exc)
    status.add(st)
    if out.empty:
        return out, comp

    st = Stage("composicao_ibov_b3")
    try:
        comp = b3.fetch_ibov_composition()
        st.ok, st.obs = True, len(comp)
        st.detalhe = "carteira VIGENTE (B3 nao publica historico aberto de composicao)"
    except Exception as exc:  # noqa: BLE001
        st.detalhe = str(exc)
        log.error("composicao_ibov_b3 falhou: %s", exc)
    status.add(st)
    if comp.empty:
        status.avisos.append(
            "Sem composicao do Ibovespa: a serie de valuation do IBOV nao foi construida.")
        return out, comp

    ano = datetime.now(timezone.utc).year
    st = Stage("lucros_cvm")
    lucros = pd.DataFrame()
    try:
        dfp = cvm.fetch_range(range(2010, ano), "DFP")
        try:
            itr = cvm.fetch_range(range(ano - 5, ano + 1), "ITR")
        except Exception as exc:  # noqa: BLE001
            itr = pd.DataFrame()
            status.avisos.append(f"ITR indisponivel; serie do IBOV fica so anual. {exc}")
        lucros = pd.concat([dfp, itr], ignore_index=True) if not itr.empty else dfp
        st.ok, st.obs = True, len(lucros)
        st.detalhe = (f"DFP {dfp['data_fim'].min().date()}..{dfp['data_fim'].max().date()}"
                      + (f" | ITR {itr['data_fim'].min().date()}..{itr['data_fim'].max().date()}"
                         if not itr.empty else " | ITR ausente"))
    except Exception as exc:  # noqa: BLE001
        st.detalhe = str(exc)[:400]
        log.error("lucros_cvm falhou: %s", str(exc)[:300])
    status.add(st)
    if lucros.empty:
        status.avisos.append(
            "Sem lucros da CVM: a serie de valuation do IBOV nao foi construida. "
            "O portal da CVM nao respondeu a partir do runner -- ver ESTADO.md.")
        return out, comp

    # --- Conciliacao composicao B3 <-> companhias CVM -----------------------
    st = Stage("conciliacao_ibov")
    casadas = []
    cobertura = 0.0
    try:
        comp["_key"] = comp["empresa"].map(_norm)
        lucros["_key"] = lucros["empresa"].map(_norm)
        chaves_cvm = {k: g for k, g in lucros.groupby("_key")}

        peso_casado = 0.0
        peso_total = float(
            comp.get("participacao_pct", pd.Series(dtype=float)).sum() or 0.0)
        for _, row in comp.iterrows():
            k = row["_key"]
            hit = chaves_cvm.get(k)
            if hit is None:
                hit = next((g for kk, g in chaves_cvm.items()
                            if kk.startswith(k[:12]) and len(k) >= 8), None)
            if hit is not None:
                casadas.append((row["codigo"], k))
                peso_casado += float(row.get("participacao_pct") or 0.0)
        cobertura = peso_casado / peso_total if peso_total > 0 else 0.0
        st.ok = True
        st.detalhe = (f"{len(casadas)}/{len(comp)} ativos conciliados; "
                      f"cobertura por peso = {cobertura:.1%}")
        st.obs = len(casadas)
    except Exception as exc:  # noqa: BLE001
        st.detalhe = str(exc)
        cobertura = 0.0
        log.error("conciliacao_ibov falhou: %s", exc)
    status.add(st)

    # --- Portao de cobertura ------------------------------------------------
    if cobertura < COBERTURA_MINIMA_IBOV:
        status.avisos.append(
            f"SERIE DO IBOV SUPRIMIDA: cobertura de {cobertura:.1%} do peso do indice, "
            f"abaixo do minimo de {COBERTURA_MINIMA_IBOV:.0%}. Publicar um agregado que "
            f"deixa de fora parte relevante do indice produziria um numero que nao e o do "
            f"Ibovespa. Ver LIMITACOES.md, secao 3.")
        log.warning("Cobertura do IBOV insuficiente (%.1f%%). Serie suprimida.",
                    cobertura * 100)
        return out, comp

    # --- Agregacao ----------------------------------------------------------
    st = Stage("pe_ibov")
    try:
        keys = {k for _, k in casadas}
        sel = lucros[lucros["_key"].isin(keys)].copy()
        anual = (sel[sel["freq"] == "A"].groupby("data_fim")["lucro"].sum().sort_index())
        trim = (sel[sel["freq"] == "T"].groupby("data_fim")["lucro"].sum().sort_index())
        ttm_trim = metrics.ttm_from_quarterly(trim) if not trim.empty else pd.Series(dtype=float)

        lucro_diario_a = metrics.step_to_daily(anual, out.index, REPORTING_LAG_DAYS_PIT)
        lucro_diario_t = (metrics.step_to_daily(ttm_trim, out.index, REPORTING_LAG_DAYS_PIT)
                          if not ttm_trim.empty
                          else pd.Series(index=out.index, dtype="float64"))
        # O trimestral tem precedencia onde existe; o anual cobre o trecho antigo.
        out["lucro_agregado"] = lucro_diario_t.combine_first(lucro_diario_a)
        out["freq_lucro"] = np.where(lucro_diario_t.notna(), "trimestral", "anual")
        out.loc[out["lucro_agregado"].isna(), "freq_lucro"] = ""

        # Ancoragem: o indice e o agregado tem escalas diferentes (o indice e uma
        # media ponderada com redutor; o agregado e lucro em BRL). A razao entre
        # eles nao e um P/E em nivel -- e um indicador de valuation na mesma
        # unidade ao longo do tempo, normalizado para 100 na primeira data valida.
        razao = out["preco"] / out["lucro_agregado"].where(out["lucro_agregado"] > 0)
        primeira = razao.first_valid_index()
        out["valuation_idx"] = (razao / razao.loc[primeira] * 100.0) if primeira else np.nan
        out["valuation_z"] = metrics.rolling_zscore(razao, STAT_WINDOW)
        out["valuation_pct"] = metrics.rolling_percentile(razao, STAT_WINDOW)
        st.ok, st.obs = True, int(razao.notna().sum())
        st.detalhe = (f"cobertura {cobertura:.1%}; indicador normalizado (base 100), "
                      f"NAO e P/E em nivel -- ver METODOLOGIA.md secao 4")
    except Exception as exc:  # noqa: BLE001
        st.detalhe = str(exc)
        log.error("pe_ibov falhou: %s", exc)
    status.add(st)
    return out, comp


# ---------------------------------------------------------------------------

def main() -> int:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    status = Status(gerado_em_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    spx = build_spx(status)
    ibov, comp = build_ibov(status)

    if not spx.empty:
        spx.round(6).to_csv(PROCESSED / "spx.csv", index_label="data")
    if not ibov.empty:
        ibov.round(6).to_csv(PROCESSED / "ibov.csv", index_label="data")
    if not comp.empty:
        comp.drop(columns=[c for c in ("_key",) if c in comp.columns]) \
            .to_csv(PROCESSED / "ibov_composicao.csv", index=False)

    if "pe" in spx.columns and "valuation_idx" in ibov.columns:
        comb = pd.DataFrame({"spx_pe": spx["pe"], "ibov_valuation_idx": ibov["valuation_idx"]})
        comb.dropna(how="all").round(6).to_csv(PROCESSED / "comparativo.csv",
                                               index_label="data")

    (PROCESSED / "status.json").write_text(
        json.dumps(asdict(status), ensure_ascii=False, indent=2), encoding="utf-8")

    ok = sum(1 for e in status.estagios if e["ok"])
    log.info("Concluido: %d/%d estagios com sucesso", ok, len(status.estagios))
    for a in status.avisos:
        log.warning("AVISO: %s", a)
    # Saida 0 mesmo com falhas parciais: o dashboard deve refletir o estado real.
    # Saida != 0 apenas se NADA foi obtido.
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
