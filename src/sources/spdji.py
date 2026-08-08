"""S&P 500: lucro por acao do indice, direto da S&P Dow Jones Indices.

Fonte: "S&P 500 Earnings and Estimate Report" (sp-500-eps-est.xlsx), publicado
pela propria administradora do indice. E a fonte primaria: o mesmo numero que
alimenta o P/E divulgado pela S&P DJI. Nao usamos agregacao propria de
componentes para o S&P 500 porque a fonte oficial existe e e gratuita.

A planilha traz, por trimestre, o EPS "as reported" (GAAP) e o "operating".
O dashboard usa as-reported como serie principal, por ser a menos sujeita a
exclusao discricionaria de despesas, e mostra operating como alternativa.
"""
from __future__ import annotations

import io
import logging

import pandas as pd

from ..config import SPDJI_EPS_XLSX
from .http import SourceUnavailable, get

log = logging.getLogger(__name__)

# Rotulos procurados no cabecalho das colunas de EPS. A planilha muda de layout
# ocasionalmente, entao a busca e por conteudo, nao por posicao fixa.
_AS_REPORTED_HINTS = ("as reported", "as-reported")
_OPERATING_HINTS = ("operating",)


def _scan_for_quarterly_eps(df: pd.DataFrame) -> pd.DataFrame:
    """Varre a aba em busca das colunas de data e de EPS trimestral.

    Estrategia: localizar a coluna cujos valores sejam majoritariamente datas de
    fim de trimestre e, a partir da linha de cabecalho, identificar as colunas
    de EPS pelo texto. Se nada for encontrado, levanta excecao.
    """
    date_col = None
    for col in df.columns:
        parsed = pd.to_datetime(df[col], errors="coerce")
        if parsed.notna().sum() >= 40:
            date_col = col
            break
    if date_col is None:
        raise SourceUnavailable("nao foi possivel localizar coluna de datas na planilha S&P DJI")

    header_row = None
    for i in range(min(20, len(df))):
        row = " ".join(str(v).lower() for v in df.iloc[i].tolist())
        if any(h in row for h in _AS_REPORTED_HINTS) or any(h in row for h in _OPERATING_HINTS):
            header_row = i
            break
    if header_row is None:
        raise SourceUnavailable("nao foi possivel localizar cabecalho de EPS na planilha S&P DJI")

    labels = {c: str(df.iloc[header_row][c]).lower() for c in df.columns}
    as_rep = [c for c, t in labels.items() if any(h in t for h in _AS_REPORTED_HINTS)]
    oper = [c for c, t in labels.items() if any(h in t for h in _OPERATING_HINTS)]
    if not as_rep and not oper:
        raise SourceUnavailable("colunas de EPS nao identificadas na planilha S&P DJI")

    out = pd.DataFrame({"date": pd.to_datetime(df[date_col], errors="coerce")})
    if as_rep:
        out["eps_as_reported"] = pd.to_numeric(df[as_rep[0]], errors="coerce")
    if oper:
        out["eps_operating"] = pd.to_numeric(df[oper[0]], errors="coerce")
    out = out.dropna(subset=["date"]).set_index("date").sort_index()
    out = out.dropna(how="all")
    if out.empty:
        raise SourceUnavailable("planilha S&P DJI lida, mas sem linhas de EPS validas")
    return out


def fetch_sp500_quarterly_eps() -> pd.DataFrame:
    """DataFrame indexado por fim de trimestre com eps_as_reported e/ou eps_operating.

    Observacao importante: a planilha inclui trimestres FUTUROS com estimativas
    de consenso. Estes sao removidos aqui. O dashboard e sobre P/E realizado
    (trailing); misturar estimativa em uma serie rotulada como historica seria
    exatamente o tipo de contaminacao que o projeto se propoe a evitar.
    """
    raw = get(SPDJI_EPS_XLSX)
    xls = pd.ExcelFile(io.BytesIO(raw))
    errors = []
    for sheet in xls.sheet_names:
        try:
            df = xls.parse(sheet, header=None)
            parsed = _scan_for_quarterly_eps(df)
            today = pd.Timestamp.utcnow().tz_localize(None).normalize()
            parsed = parsed.loc[:today]
            if len(parsed) >= 40:
                log.info("S&P DJI: aba '%s', %d trimestres ate %s",
                         sheet, len(parsed), parsed.index.max().date())
                return parsed
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{sheet}: {exc}")
    raise SourceUnavailable(
        "nenhuma aba da planilha S&P DJI produziu serie trimestral utilizavel. "
        + " | ".join(errors[:5])
    )
