"""Testes escritos a partir do que as fontes DE FATO devolvem.

Ate aqui eu vinha corrigindo estas duas coisas por hipotese, e errei as duas
vezes. Estes testes reproduzem o layout real, medido no runner em 10/08/2026,
e por isso valem mais do que os anteriores: nao dependem de eu ter adivinhado
certo.
"""
from __future__ import annotations

import io
import json
import unittest.mock as mock
import zipfile

import numpy as np
import pandas as pd
import pytest

from src.sources import b3, shiller
from src.sources.http import SourceUnavailable


# ---------------------------------------------------------------------------
# Planilha ie_data: cabecalho de 8 linhas, rotulo empilhado na vertical
# ---------------------------------------------------------------------------

def _ie_data_real(n: int = 300) -> pd.DataFrame:
    """Replica o layout medido: 22 colunas, cabecalho nas linhas 0..7.

    O ponto que importa e a posicao das palavras. Lendo de cima para baixo:
      col 12 -> Cyclically Adjusted Price Earnings Ratio  P/E10 or  CAPE
      col 14 -> Cyclically Adjusted Total Return Price... TR P/E10 or  TR CAPE
      col 16 -> Excess ... CAPE  Yield
    A palavra "CAPE" aparece na linha 6 na coluna 16 e so na linha 7 nas
    colunas 12 e 14 -- e foi isso que fez a busca ingenua escolher a coluna
    errada e, depois, coluna nenhuma.
    """
    linhas = [["" for _ in range(22)] for _ in range(8)]
    linhas[1][0] = "Stock Market Data"
    linhas[1][12] = linhas[1][14] = "Cyclically"
    linhas[2][12] = linhas[2][14] = "Adjusted"
    linhas[3][12] = "Price"
    linhas[3][14] = "Total Return Price"
    linhas[4][4] = "Consumer"
    linhas[4][12] = linhas[4][14] = "Earnings"
    linhas[5][1] = "S&P"
    linhas[5][12] = linhas[5][14] = "Ratio"
    linhas[5][16] = "Excess"
    linhas[6][0] = ""
    linhas[6][1] = "Comp."
    linhas[6][2] = "Dividend"
    linhas[6][3] = "Earnings"
    linhas[6][12] = "P/E10 or"
    linhas[6][14] = "TR P/E10 or"
    linhas[6][16] = "CAPE"
    linhas[7][0] = "Date"
    linhas[7][1] = "P"
    linhas[7][2] = "D"
    linhas[7][3] = "E"
    linhas[7][4] = "CPI"
    linhas[7][12] = "CAPE"
    linhas[7][14] = "TR CAPE"
    linhas[7][16] = "Yield"

    dados = []
    for i in range(n):
        ano = 2000 + i // 12
        mes = i % 12 + 1
        lin = [""] * 22
        lin[0] = float(f"{ano}.{mes:02d}")
        lin[1] = 1000.0 + i          # preco
        lin[2] = 20.0                # dividendo
        lin[3] = 60.0 + i * 0.2      # lucro 12m
        lin[4] = 200.0
        lin[12] = 16.0 + (i % 20)    # CAPE  -> plausivel
        lin[14] = 20.0 + (i % 20)    # TR CAPE -> tambem plausivel
        lin[16] = 0.03               # Excess CAPE Yield -> implausivel
        dados.append(lin)
    return pd.DataFrame(linhas + dados)


def test_cape_vem_da_coluna_12_e_nao_da_16_nem_da_14():
    """A coluna certa e a do CAPE simples, nao a do TR CAPE nem a do rendimento."""
    df = _ie_data_real()
    with mock.patch.object(shiller, "get", return_value=b"x"), \
         mock.patch.object(shiller.pd, "ExcelFile") as xl:
        xl.return_value.sheet_names = ["Disclaimer", "Data"]
        xl.return_value.parse.return_value = df
        t = shiller.fetch_tabela()

    assert t["cape"].notna().sum() > 0, "o CAPE nao pode sair vazio"
    mediana = float(t["cape"].median())
    assert 10 <= mediana <= 40, f"mediana {mediana} fora da faixa do CAPE simples"
    assert mediana < 30, "pegou o TR CAPE, que e mais alto, em vez do CAPE"
    assert "cape" in t.attrs["cape_rotulo"]
    assert "yield" not in t.attrs["cape_rotulo"]


def test_lucro_e_preco_continuam_certos_com_o_novo_cabecalho():
    """Mudar a deteccao do cabecalho nao pode deslocar as colunas P e E."""
    df = _ie_data_real()
    with mock.patch.object(shiller, "get", return_value=b"x"), \
         mock.patch.object(shiller.pd, "ExcelFile") as xl:
        xl.return_value.sheet_names = ["Disclaimer", "Data"]
        xl.return_value.parse.return_value = df
        t = shiller.fetch_tabela()
    # A serie e filtrada a partir de START_DATE (2010), entao o primeiro valor
    # visivel nao e o primeiro da planilha. O que importa e a ORDEM de grandeza:
    # se as colunas tivessem deslocado, viriam precos no lugar de lucros.
    assert t["preco"].min() >= 1000.0, "coluna de preco (1) deslocou"
    assert t["lucro_ttm"].max() < 500.0, "coluna de lucro (3) deslocou"
    assert (t["preco"] > t["lucro_ttm"]).all(), "preco e lucro trocaram de lugar"


def test_cabecalho_sem_linha_de_dados_falha_alto():
    df = pd.DataFrame([["Date", "P"], ["x", "y"]])
    with mock.patch.object(shiller, "get", return_value=b"x"), \
         mock.patch.object(shiller.pd, "ExcelFile") as xl:
        xl.return_value.sheet_names = ["Data"]
        xl.return_value.parse.return_value = df
        with pytest.raises(SourceUnavailable) as e:
            shiller.fetch_tabela()
    assert "primeira linha de dados" in str(e.value)


# ---------------------------------------------------------------------------
# Cadastro da B3: lista paginada que estava sendo truncada
# ---------------------------------------------------------------------------

def _payload(pagina: int, por_pagina: int, total: int):
    ini = (pagina - 1) * por_pagina

    def codigo(n: int) -> str:
        # 4 letras unicas por indice: AAAA, AAAB, ... (o cadastro real usa
        # codigos alfabeticos como VALE, PETR, ITUB)
        letras = ""
        for _ in range(4):
            letras = chr(65 + n % 26) + letras
            n //= 26
        return letras

    res = [{"codeCVM": str(9000 + i), "issuingCompany": codigo(i),
            "companyName": f"EMPRESA {i}", "cnpj": f"{i+1:014d}"}
           for i in range(ini, min(ini + por_pagina, total))]
    return {"page": {"totalPages": -(-total // por_pagina), "totalRecords": total},
            "results": res}


def test_cadastro_da_b3_percorre_todas_as_paginas():
    """Com 2500 companhias, o teto antigo de 20 paginas parava em 2000.

    Nao era uma falha visivel: a lista voltava bem-formada, so que sem o final.
    As 22 raizes que nao conciliavam -- ITUB, PETR, VIVT, RENT, entre outras --
    estavam justamente na parte cortada.
    """
    total = 2500
    chamadas = []

    def falso_get(url, **kw):
        import base64
        params = json.loads(base64.b64decode(url.rsplit("/", 1)[1]))
        chamadas.append(params["pageNumber"])
        return json.dumps(_payload(params["pageNumber"], 100, total)).encode()

    with mock.patch.object(b3, "get", side_effect=falso_get):
        out = b3.fetch_empresas_listadas()

    assert len(chamadas) == 25, f"deveria pedir 25 paginas, pediu {len(chamadas)}"
    assert len(out) == total, f"deveria trazer {total} companhias, trouxe {len(out)}"


def test_cadastro_da_b3_para_no_total_informado():
    """Nao pode girar alem do que a B3 diz existir."""
    def falso_get(url, **kw):
        import base64
        params = json.loads(base64.b64decode(url.rsplit("/", 1)[1]))
        return json.dumps(_payload(params["pageNumber"], 100, 150)).encode()

    with mock.patch.object(b3, "get", side_effect=falso_get):
        out = b3.fetch_empresas_listadas()
    assert len(out) == 150
