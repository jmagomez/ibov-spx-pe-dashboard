"""Orquestrador do pipeline.

Principios que governam este arquivo:

1. Cada estagio e independente. A falha de um nao derruba os demais; ela e
   registrada em data/processed/status.json e exibida no dashboard.
2. Nenhum estagio produz numero que nao tenha vindo de uma fonte. Nao ha
   fallback com media, interpolacao de lucro, valor default ou ultimo valor
   conhecido travado. Alternar entre FONTES documentadas e outra coisa: a fonte
   efetivamente usada aparece no diagnostico.
3. Series com lastro insuficiente sao SUPRIMIDAS, nao publicadas com ressalva
   em letra miuda. O portao de cobertura do Ibovespa implementa isso, e desde
   a correcao da agregacao ele vale data a data, nao so uma vez.
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import metrics, reconcile
from .config import (MAX_STALE_DAYS_CAPE, MAX_STALE_DAYS_EPS_MENSAL,
                     MAX_STALE_DAYS_EPS_TRIMESTRAL, MAX_STALE_DAYS_LUCRO_ANUAL,
                     MAX_STALE_DAYS_LUCRO_TRIMESTRAL, PROCESSED,
                     REPORTING_LAG_DAYS_INDEX, REPORTING_LAG_DAYS_PIT, STAT_WINDOW)
from .sources import b3, cvm, prices, shiller, spdji

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s")
log = logging.getLogger("build")

# Fracao minima do PESO do Ibovespa que precisa ter lucro conciliado para que a
# serie seja publicada. Abaixo disso o agregado nao representa o indice e a
# serie e suprimida. O mesmo numero, na mesma unidade, limita quanto do peso
# pode faltar na soma de uma data especifica.
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
    vigencias: list = field(default_factory=list)
    conciliacao: dict = field(default_factory=dict)
    dfp_ausentes: list = field(default_factory=list)

    def add(self, s: Stage) -> None:
        self.estagios.append(asdict(s))


def _registrar_vigencia(status: Status, fonte: str, step: pd.Series, lag: int,
                        teto: int, daily_index: pd.DatetimeIndex) -> None:
    """Anota ate quando a fonte tem lastro e quanto do fim da serie ficou vazio.

    Sem isto, a unica pista de que uma fonte parou de ser atualizada e a serie
    parar de andar no grafico -- e nem isso, quando o ffill a estende. O aviso
    abaixo e o que transforma silencio em informacao.
    """
    venc = metrics.vencimento(step, lag, teto)
    if pd.isna(venc):
        return
    ultimo_pregao = daily_index.max()
    atraso = metrics.defasagem_dias(step, ultimo_pregao)
    status.vigencias.append({
        "fonte": fonte,
        "ultima_observacao": str(pd.Series(step).dropna().index.max().date()),
        "vigente_ate": str(pd.Timestamp(venc).date()),
        "defasagem_dias": atraso,
        "vencida": bool(venc < ultimo_pregao),
    })
    if venc < ultimo_pregao:
        dias = int((ultimo_pregao - venc).days)
        status.avisos.append(
            f"{fonte}: a fonte parou em {pd.Series(step).dropna().index.max().date()} e a "
            f"ultima observacao venceu ha {dias} dias. O trecho final da serie fica VAZIO "
            f"em vez de repetir o ultimo valor -- ver METODOLOGIA.md, secao de validade.")


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
        out["eps_ttm"] = metrics.step_to_daily(
            ttm, out.index, REPORTING_LAG_DAYS_INDEX, MAX_STALE_DAYS_EPS_TRIMESTRAL)
        out["eps_ttm_pit"] = metrics.step_to_daily(
            ttm, out.index, REPORTING_LAG_DAYS_PIT, MAX_STALE_DAYS_EPS_TRIMESTRAL)
        _registrar_vigencia(status, "eps_spx", ttm, REPORTING_LAG_DAYS_INDEX,
                            MAX_STALE_DAYS_EPS_TRIMESTRAL, out.index)
        if "eps_operating" in q.columns and col != "eps_operating":
            ttm_op = metrics.ttm_from_quarterly(q["eps_operating"])
            out["eps_ttm_operating"] = metrics.step_to_daily(
                ttm_op, out.index, REPORTING_LAG_DAYS_INDEX,
                MAX_STALE_DAYS_EPS_TRIMESTRAL)
        st.ok, st.obs = True, int(out["eps_ttm"].notna().sum())
        st.detalhe = f"fonte: S&P Dow Jones Indices ({col}), trimestral"
    except Exception as exc:  # noqa: BLE001
        erros_eps.append(f"spdji: {str(exc)[:150]}")
        log.warning("EPS via S&P DJI indisponivel: %s", str(exc)[:200])
        try:
            # A coluna E da planilha Shiller JA e LPA acumulado em 12 meses:
            # entra direto, sem soma movel de quatro trimestres.
            eps_m = shiller.fetch_eps_ttm()
            out["eps_ttm"] = metrics.step_to_daily(
                eps_m, out.index, 0, MAX_STALE_DAYS_EPS_MENSAL)
            out["eps_ttm_pit"] = metrics.step_to_daily(
                eps_m, out.index, REPORTING_LAG_DAYS_PIT, MAX_STALE_DAYS_EPS_MENSAL)
            _registrar_vigencia(status, "eps_spx", eps_m, 0,
                                MAX_STALE_DAYS_EPS_MENSAL, out.index)
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
        out["cape"] = metrics.step_to_daily(cape, out.index, 0, MAX_STALE_DAYS_CAPE)
        _registrar_vigencia(status, "cape_shiller", cape, 0, MAX_STALE_DAYS_CAPE,
                            out.index)
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
        # ate ano+1: o exercicio corrente pode ja ter arquivo no portal, e
        # exclui-lo por convencao descartaria dado que existe.
        dfp = cvm.fetch_range(range(2010, ano + 1), "DFP")
        try:
            itr = cvm.fetch_range(range(ano - 5, ano + 1), "ITR")
        except Exception as exc:  # noqa: BLE001
            itr = pd.DataFrame()
            status.avisos.append(f"ITR indisponivel; serie do IBOV fica so anual. {exc}")
        lucros = pd.concat([dfp, itr], ignore_index=True) if not itr.empty else dfp
        st.ok, st.obs = True, len(lucros)
        ausentes = list(dfp.attrs.get("anos_ausentes", []))
        outras = list(dfp.attrs.get("anos_falhos", []))
        st.detalhe = (f"DFP {dfp['data_fim'].min().date()}..{dfp['data_fim'].max().date()}"
                      + (f" | ITR {itr['data_fim'].min().date()}..{itr['data_fim'].max().date()}"
                         if not itr.empty else " | ITR ausente")
                      + (f" | DFP nao publicado: {ausentes}" if ausentes else "")
                      + (f" | DFP com erro: {len(outras)}" if outras else ""))
        status.dfp_ausentes = ausentes
        if ausentes:
            status.avisos.append(
                f"Exercicio(s) {', '.join(map(str, ausentes))} sem DFP no portal da CVM "
                f"(HTTP 404 -- o arquivo nao existe, nao e falha de rede). Enquanto nao "
                f"for publicado, o trecho correspondente da serie do Ibovespa se apoia "
                f"no ITR, que cobre os ultimos cinco anos em frequencia trimestral.")
        cvm.salvar_cache(lucros, st.detalhe)
    except Exception as exc:  # noqa: BLE001
        st.detalhe = str(exc)[:600]
        log.error("lucros_cvm falhou: %s", str(exc)[:400])
        # Onde a conexao quebrou, em vez de "Max retries exceeded".
        try:
            diag = cvm.diagnostico_conectividade()
            st.detalhe += " || diagnostico: " + json.dumps(diag, ensure_ascii=False)
            log.error("diagnostico CVM: %s", diag)
        except Exception as exc2:  # noqa: BLE001
            log.warning("diagnostico da CVM falhou: %s", exc2)
        # Cache: dado real de uma coleta anterior, com idade declarada.
        cache, meta = cvm.carregar_cache()
        if not cache.empty:
            lucros = cache
            st.ok, st.obs = True, len(cache)
            idade = meta.get("idade_dias", "?")
            st.detalhe = (f"CACHE de {meta.get('coletado_em_utc', '?')} ({idade} dias); "
                          f"{meta.get('data_fim_min', '?')}..{meta.get('data_fim_max', '?')}. "
                          f"CVM indisponivel agora: {st.detalhe[:220]}")
            status.avisos.append(
                f"Lucros da CVM vindos do CACHE local, coletado ha {idade} dias. "
                f"Sao numeros de uma coleta real anterior, nao estimativas -- mas "
                f"exercicios divulgados depois dessa data NAO estao aqui.")
            log.warning("usando cache da CVM (%d linhas, %s dias)", len(cache), idade)
    status.add(st)
    if lucros.empty:
        status.avisos.append(
            "Sem lucros da CVM e sem cache: a serie de valuation do IBOV nao foi "
            "construida. Ver ESTADO.md para o estado do bloqueio.")
        return out, comp

    # --- Conciliacao composicao B3 <-> companhias CVM -----------------------
    # Por identificador, com CD_CVM como chave estavel. Ver src/reconcile.py
    # para o motivo -- em resumo: nome nao e chave, e CNPJ muda.
    st = Stage("cadastro_b3")
    empresas = pd.DataFrame()
    try:
        empresas = b3.fetch_empresas_listadas()
        st.ok, st.obs = True, len(empresas)
        st.detalhe = "ponte codigo de negociacao -> CNPJ"
    except Exception as exc:  # noqa: BLE001
        st.detalhe = str(exc)[:400]
        status.avisos.append(
            f"Cadastro de listadas da B3 indisponivel: a conciliacao cai para razao "
            f"social, que e menos confiavel. {str(exc)[:200]}")
        log.error("cadastro_b3 falhou: %s", str(exc)[:300])
    status.add(st)

    st = Stage("conciliacao_ibov")
    casadas = pd.DataFrame()
    cobertura = 0.0
    try:
        casadas, cobertura, rel = reconcile.conciliar(comp, empresas, lucros)
        status.conciliacao = rel
        st.ok, st.obs = True, len(casadas)
        st.detalhe = (f"{rel['ativos']} ativos; cobertura por peso = {cobertura:.1%}; "
                      f"{rel['por_codigo_cvm']} via codigo CVM, {rel['por_cnpj']} via CNPJ, "
                      f"{rel['por_nome']} via razao social")
        if rel["trocas_de_cnpj"]:
            status.avisos.append(
                f"{len(rel['trocas_de_cnpj'])} companhia(s) trocaram de CNPJ no periodo. "
                f"Os numeros antigos continuam resolvendo para o mesmo codigo CVM, de "
                f"modo que o lucro anterior a troca NAO se perde. Detalhe em "
                f"status.json, campo conciliacao.trocas_de_cnpj.")
        if rel["cnpj_ambiguo"]:
            status.avisos.append(
                f"{len(rel['cnpj_ambiguo'])} CNPJ(s) apontam para mais de um codigo CVM "
                f"e foram RECUSADOS em vez de desempatados por criterio arbitrario.")
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
        # Os dois lados passam pela MESMA normalizacao. Sem isso a conciliacao
        # reportava 100% de cobertura e a selecao devolvia zero linhas: a CVM
        # publica "000906" e a B3, "906". O portao abria e a serie saia vazia.
        keys = set(casadas["cd_cvm"].map(reconcile.normalizar_cd_cvm))
        sel = lucros[lucros["cd_cvm"].map(reconcile.normalizar_cd_cvm).isin(keys)].copy()
        if sel.empty:
            raise RuntimeError(
                f"conciliacao casou {len(casadas)} ativos mas nenhuma linha de lucro "
                f"foi selecionada -- codigos CVM em formatos incompativeis. "
                f"exemplos casados={list(keys)[:5]}; "
                f"exemplos na CVM={list(lucros['cd_cvm'].astype(str).unique()[:5])}")
        # Cobertura medida em PESO do indice, nao em contagem de companhias.
        # Contar dava a uma empresa de 0,06% o mesmo poder de veto de uma de
        # 8,5%, e era isso que cortava a serie em 2014: a cobertura POR PESO ja
        # era de 84,8% em 2010.
        pesos = dict(zip(casadas["cd_cvm"].map(reconcile.normalizar_cd_cvm),
                         casadas["participacao_pct"].astype(float)))
        peso_total = sum(pesos.values()) or 1.0
        lucro_diario_a, cob_a = metrics.soma_por_entidade(
            sel[sel["freq"] == "A"], out.index, REPORTING_LAG_DAYS_PIT,
            MAX_STALE_DAYS_LUCRO_ANUAL, pesos=pesos)
        lucro_diario_t, cob_t = metrics.soma_por_entidade(
            sel[sel["freq"] == "T"], out.index, REPORTING_LAG_DAYS_PIT,
            MAX_STALE_DAYS_LUCRO_TRIMESTRAL, trimestral=True, pesos=pesos)

        # Mesmo criterio do portao de cobertura, agora aplicado data a data em
        # vez de uma vez so -- e na mesma unidade dele.
        min_peso = COBERTURA_MINIMA_IBOV * peso_total
        lucro_diario_a = lucro_diario_a.where(cob_a >= min_peso)
        lucro_diario_t = lucro_diario_t.where(cob_t >= min_peso)

        # O trimestral tem precedencia onde existe; o anual cobre o trecho antigo.
        out["lucro_agregado"] = lucro_diario_t.combine_first(lucro_diario_a)
        out["peso_coberto_pct"] = (np.where(lucro_diario_t.notna(), cob_t, cob_a)
                                   / peso_total * 100.0)
        out["freq_lucro"] = np.where(lucro_diario_t.notna(), "trimestral", "anual")
        out.loc[out["lucro_agregado"].isna(), "freq_lucro"] = ""
        out.loc[out["lucro_agregado"].isna(), "peso_coberto_pct"] = np.nan

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
        pc = out.loc[out["lucro_agregado"].notna(), "peso_coberto_pct"]
        st.detalhe = (f"cobertura da carteira {cobertura:.1%}; {len(sel)} linhas de lucro "
                      f"de {sel['cd_cvm'].nunique()} companhias; exigido >= "
                      f"{COBERTURA_MINIMA_IBOV:.0%} do PESO em cada data (coberto: min "
                      f"{pc.min():.1f}%, mediana {pc.median():.1f}%)" if len(pc) else
                      f"cobertura da carteira {cobertura:.1%}; nenhuma data atingiu o "
                      f"minimo de peso")
        st.detalhe += ("; indicador normalizado (base 100), NAO e P/E em nivel -- "
                       "ver METODOLOGIA.md secao 4")
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
