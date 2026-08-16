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
    """Devolve a aba Data crua, com o bloco de cabecalho ja delimitado."""
    raw = get(SHILLER_XLS)
    xls = pd.ExcelFile(io.BytesIO(raw))
    sheet = next((s for s in xls.sheet_names if s.strip().lower() == "data"),
                 xls.sheet_names[0])
    df = xls.parse(sheet, header=None)

    # O cabecalho da ie_data ocupa OITO linhas, com o rotulo de cada coluna
    # empilhado verticalmente: a coluna do CAPE, por exemplo, se le de cima para
    # baixo como "Cyclically / Adjusted / Price / Earnings / Ratio / P/E10 or /
    # CAPE". Procurar "a primeira linha que contem 'cape'" achava a linha 6, em
    # que a palavra CAPE pertence a OUTRA coluna -- a do "Excess CAPE Yield",
    # cujo rotulo se completa uma linha abaixo. Dai a serie ter saido ausente.
    #
    # O corpo comeca na primeira linha cuja coluna 0 e uma data no formato
    # AAAA.MM da planilha. Tudo acima disso e cabecalho.
    primeira_dado = None
    for i in range(min(40, len(df))):
        if not pd.isna(_shiller_date_to_ts(df.iloc[i][df.columns[0]])):
            primeira_dado = i
            break
    if primeira_dado is None or primeira_dado == 0:
        raise SourceUnavailable(
            "nao encontrei a primeira linha de dados da planilha Shiller "
            "(coluna 0 deveria trazer a data no formato AAAA.MM)")
    df.attrs["header_row"] = primeira_dado - 1
    df.attrs["header_inicio"] = 0
    return df


def cape_plausivel(serie: pd.Series) -> bool:
    """Uma coluna so e aceita como CAPE se a mediana couber na faixa historica."""
    v = pd.to_numeric(serie, errors="coerce").dropna()
    if v.size < 24:
        return False
    return bool(CAPE_MIN_PLAUSIVEL <= float(v.median()) <= CAPE_MAX_PLAUSIVEL)


def _escolher_cape(df: pd.DataFrame, body: pd.DataFrame, cols: list, h: int):
    """Escolhe a coluna de CAPE por rotulo E por plausibilidade do valor.

    Medido na planilha real em 10/08/2026:

      col 12 -> "Cyclically Adjusted Price Earnings Ratio  P/E10 or  CAPE"
                mediana 16,52  min 4,78  max 44,20   <- o CAPE
      col 14 -> "Cyclically Adjusted Total Return ...  TR P/E10 or  TR CAPE"
                mediana 20,54  min 6,58  max 48,11   <- CAPE de retorno total
      col 16 -> "Excess  CAPE  Yield"
                mediana 0,0336                        <- rendimento, nao multiplo

    As tres contem a palavra CAPE. A escolha passa por dois crivos: o rotulo
    completo da coluna no bloco de cabecalho, e a plausibilidade do valor. Um
    rotulo certo com valor absurdo continua sendo valor absurdo.
    """
    # Rotulo = a coluna inteira do bloco de cabecalho, lida de cima para baixo.
    # Na ie_data real, a coluna 12 se le "cyclically adjusted price earnings
    # ratio p/e10 or cape" e a 14, "... total return ... tr p/e10 or tr cape".
    # Ler so as ultimas linhas nao distingue as duas nem exclui a terceira.
    rotulos = {}
    for c in cols:
        partes = []
        for r in range(0, h + 1):
            v = str(df.iloc[r][c]).strip().lower()
            if v and v != "nan":
                partes.append(v)
        rotulos[c] = " ".join(partes)

    def _pontuar(rotulo: str) -> int:
        if "yield" in rotulo or "excess" in rotulo:
            return -1          # rendimento, nao multiplo
        if "cape" not in rotulo and "p/e10" not in rotulo:
            return -1
        # "TR CAPE" e o CAPE de retorno total: indicador legitimo, mas nao e o
        # CAPE que o dashboard anuncia. Fica como segunda opcao, nao como igual.
        if "total return" in rotulo or " tr " in f" {rotulo} " or "tr cape" in rotulo:
            return 1
        return 3

    candidatos = sorted(((_pontuar(r), c) for c, r in rotulos.items() if _pontuar(r) > 0),
                        key=lambda t: -t[0])
    recusadas = []
    for _, c in candidatos:
        serie = pd.to_numeric(body[c], errors="coerce")
        if cape_plausivel(serie):
            return serie, rotulos[c]
        v = serie.dropna()
        recusadas.append(f"'{rotulos[c][:40]}' (mediana={float(v.median()):.4g})"
                         if v.size else f"'{rotulos[c][:40]}' (vazia)")
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

    # REGRESSAO CORRIGIDA: ate a execucao #6, uma falha aqui abortava fetch_tabela
    # e, com ela, fetch_eps_ttm -- que le a MESMA tabela. O resultado foi o pior
    # possivel: um problema no CAPE apagou tambem o P/E do S&P, que estava
    # correto e disponivel. Uma serie ruim deve derrubar a si mesma, nao as
    # vizinhas. O motivo fica registrado e sai no diagnostico.
    try:
        cape, cape_rotulo = _escolher_cape(df, body, cols, h)
        cape_erro = ""
    except SourceUnavailable as exc:
        cape = pd.Series(index=body.index, dtype="float64")
        cape_rotulo, cape_erro = "recusada", str(exc)
        log.warning("CAPE indisponivel (%s); o lucro da mesma planilha segue valido", exc)

    out = pd.DataFrame({"preco": preco.values, "lucro_ttm": lucro.values,
                        "cape": cape.values}, index=datas)
    out = out[~out.index.isna()].sort_index().loc[START_DATE:]
    if out.empty:
        raise SourceUnavailable("tabela Shiller vazia apos filtro de data")
    if out["lucro_ttm"].notna().sum() < 12:
        raise SourceUnavailable(
            "coluna de lucro da planilha Shiller nao parece numerica; layout mudou")
    out.attrs["cape_rotulo"] = cape_rotulo
    out.attrs["cape_erro"] = cape_erro
    log.info("Shiller: %d meses de %s a %s (lucro=%d, cape=%d via '%s')", len(out),
             out.index.min().date(), out.index.max().date(),
             int(out["lucro_ttm"].notna().sum()), int(out["cape"].notna().sum()),
             cape_rotulo[:40])
    return out


def fetch_cape() -> pd.Series:
    """Serie mensal do CAPE."""
    t = fetch_tabela()
    s = t["cape"].dropna()
    if s.empty:
        raise SourceUnavailable(t.attrs.get("cape_erro") or "serie CAPE vazia")
    return s


def fetch_eps_ttm() -> pd.Series:
    """Serie mensal do LPA 12m do S&P 500 (coluna E). JA acumulada em 12 meses."""
    s = fetch_tabela()["lucro_ttm"].dropna()
    if s.empty:
        raise SourceUnavailable("serie de lucro da Shiller vazia")
    return s
