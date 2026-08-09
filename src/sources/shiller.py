"""Planilha ie_data de Robert Shiller (Yale).

Duas coisas saem daqui:

  CAPE     - contraponto ao P/E trailing; usa lucro real medio de 10 anos.
  Earnings - a coluna E e o lucro por acao do S&P 500 acumulado em 12 meses,
             mensal. E a mesma linhagem de dado da S&P DJI, e serve de fonte
             alternativa quando o arquivo oficial da S&P nao esta acessivel --
             o que ocorreu na execucao #4, com 403 vindo de spglobal.com.

Ponto metodologico importante: a coluna E JA e acumulada em 12 meses. Aplicar
sobre ela a soma movel de quatro trimestres usada na serie da S&P DJI
quadruplicaria o denominador. Por isso ela entra direto como LPA 12m.
"""
from __future__ import annotations

import io
import logging
import math

import pandas as pd

from ..config import (CAPE_MAX_PLAUSIVEL, CAPE_MIN_PLAUSIVEL, SHILLER_XLS,
                      START_DATE)
from .http import SourceUnavailable, get

log = logging.getLogger(__name__)


def _shiller_date_to_ts(v):
    """A planilha codifica data como AAAA.MM com mes fracionario (2010.01 = jan/2010)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return pd.NaT
    if math.isnan(f) or math.isinf(f):
        return pd.NaT
    year = int(f)
    if year < 1800 or year > 2200:
        return pd.NaT
    month = int(round((f - year) * 100))
    if month < 1 or month > 12:
        return pd.NaT
    return pd.Timestamp(year=year, month=month, day=1)


def _abrir_tabela() -> pd.DataFrame:
    """Devolve a aba Data crua, com a linha de cabecalho ja localizada."""
    raw = get(SHILLER_XLS)
    xls = pd.ExcelFile(io.BytesIO(raw))
    sheet = next((s for s in xls.sheet_names if s.strip().lower() == "data"),
                 xls.sheet_names[0])
    df = xls.parse(sheet, header=None)
    header_row = None
    for i in range(min(30, len(df))):
        linha = " ".join(str(v).lower() for v in df.iloc[i].tolist())
        if "cape" in linha:
            header_row = i
            break
    if header_row is None:
        raise SourceUnavailable("linha de cabecalho (com CAPE) nao encontrada na planilha Shiller")
    df.attrs["header_row"] = header_row
    return df


def cape_plausivel(serie: pd.Series) -> bool:
    """Uma coluna so e aceita como CAPE se a mediana couber na faixa historica."""
    v = pd.to_numeric(serie, errors="coerce").dropna()
    if v.size < 24:
        return False
    return bool(CAPE_MIN_PLAUSIVEL <= float(v.median()) <= CAPE_MAX_PLAUSIVEL)


def _escolher_cape(df: pd.DataFrame, body: pd.DataFrame, cols: list, h: int):
    """Escolhe a coluna de CAPE por rotulo E por plausibilidade do valor.

    A selecao anterior era `primeira coluna cujo cabecalho contem "cape"`. A aba
    Data traz, lado a lado, "CAPE", "TR CAPE" e "Excess CAPE Yield" -- as tres
    casam com a substring, e a terceira e um RENDIMENTO, da ordem de 0,02. Foi
    o que acabou publicado em 08/08/2026: a serie rotulada CAPE no dashboard ia
    de 0,01 a 0,06, quando o CAPE do S&P 500 nunca saiu da faixa de um digito a
    quarenta e poucos em cem anos de historia.

    Um rotulo certo com valor absurdo continua sendo valor absurdo. Por isso a
    escolha passa pelos dois crivos: preferencia por rotulo exato, e recusa de
    qualquer coluna cuja mediana nao caiba na faixa historica do indicador.
    """
    rotulos = {c: str(df.iloc[h][c]).strip().lower() for c in cols}

    def _pontuar(rotulo: str) -> int:
        if "yield" in rotulo or "excess" in rotulo:
            return -1          # rendimento, nao multiplo
        if rotulo == "cape":
            return 3
        if rotulo.startswith("cape"):
            return 2
        if "cape" in rotulo:
            return 1
        return -1

    candidatos = sorted(((_pontuar(r), c) for c, r in rotulos.items() if _pontuar(r) > 0),
                        key=lambda t: -t[0])
    recusadas = []
    for _, c in candidatos:
        serie = pd.to_numeric(body[c], errors="coerce")
        if cape_plausivel(serie):
            return serie, rotulos[c]
        v = serie.dropna()
        recusadas.append(f"'{rotulos[c]}' (mediana={float(v.median()):.4g})"
                         if v.size else f"'{rotulos[c]}' (vazia)")
    if candidatos:
        raise SourceUnavailable(
            "nenhuma coluna de CAPE da planilha Shiller ficou na faixa plausivel "
            f"[{CAPE_MIN_PLAUSIVEL:g}, {CAPE_MAX_PLAUSIVEL:g}]; recusadas: "
            + ", ".join(recusadas))
    return pd.Series(index=body.index, dtype="float64"), "ausente"


def fetch_tabela() -> pd.DataFrame:
    """DataFrame mensal com colunas: preco, lucro_ttm, cape.

    Layout historico da aba Data: coluna 0 = Date, 1 = P, 2 = D, 3 = E.
    A posicao e usada apenas para P/D/E; o CAPE e localizado pelo rotulo.
    Um teste de sanidade rejeita a leitura se as colunas nao forem numericas.
    """
    df = _abrir_tabela()
    h = df.attrs["header_row"]
    cols = list(df.columns)
    body = df.iloc[h + 1:]

    datas = pd.DatetimeIndex(body[cols[0]].map(_shiller_date_to_ts))
    preco = pd.to_numeric(body[cols[1]], errors="coerce")
    lucro = pd.to_numeric(body[cols[3]], errors="coerce")

    cape, cape_rotulo = _escolher_cape(df, body, cols, h)

    out = pd.DataFrame({"preco": preco.values, "lucro_ttm": lucro.values,
                        "cape": cape.values}, index=datas)
    out = out[~out.index.isna()].sort_index().loc[START_DATE:]
    if out.empty:
        raise SourceUnavailable("tabela Shiller vazia apos filtro de data")
    if out["lucro_ttm"].notna().sum() < 12:
        raise SourceUnavailable(
            "coluna de lucro da planilha Shiller nao parece numerica; layout mudou")
    out.attrs["cape_rotulo"] = cape_rotulo
    log.info("Shiller: %d meses de %s a %s (lucro=%d, cape=%d via '%s')", len(out),
             out.index.min().date(), out.index.max().date(),
             int(out["lucro_ttm"].notna().sum()), int(out["cape"].notna().sum()),
             cape_rotulo)
    return out


def fetch_cape() -> pd.Series:
    """Serie mensal do CAPE."""
    s = fetch_tabela()["cape"].dropna()
    if s.empty:
        raise SourceUnavailable("serie CAPE vazia")
    return s


def fetch_eps_ttm() -> pd.Series:
    """Serie mensal do LPA 12m do S&P 500 (coluna E). JA acumulada em 12 meses."""
    s = fetch_tabela()["lucro_ttm"].dropna()
    if s.empty:
        raise SourceUnavailable("serie de lucro da Shiller vazia")
    return s
