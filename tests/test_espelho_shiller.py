"""O defeito que ficou dois anos no ar, e o teste que o trava.

Sintoma em producao: `status.json` com os nove estagios marcados `ok`, e a
serie de P/E do S&P 500 terminando em junho de 2024. Nenhuma excecao, nenhum
log de erro, nenhuma fonte "falhou". O CAPE parava em setembro de 2024.

Causa: a URL da planilha ie_data em config.py apontava para
`.../downloads/ie_data.xls`, endereco antigo que continua respondendo HTTP 200
e continua entregando um XLS bem-formado -- congelado em 2024. O endereco
vigente tem um segmento de pasta a mais.

A licao que este arquivo codifica: para uma fonte servida por CDN, status 200 e
arquivo integro NAO sao evidencia de que o dado esta atualizado. A unica
evidencia e a data da ultima observacao dentro do arquivo. Por isso a escolha
entre espelhos e pela data, e nao pela ordem de resposta.
"""
from __future__ import annotations

from unittest import mock

import pandas as pd
import pytest

from src.sources import shiller
from src.sources.http import SourceUnavailable

NOVO = "https://exemplo/downloads/70fec4f5/ie_data.xls"
LEGADO = "https://exemplo/downloads/ie_data.xls"


def _planilha(ate: str) -> pd.DataFrame:
    """Aba Data minima, no layout real: col 0 = AAAA.MM, col 1 = P, col 3 = E."""
    meses = pd.date_range("2010-01-01", ate, freq="MS")
    datas = [round(d.year + d.month / 100, 2) for d in meses]
    n = len(meses)
    df = pd.DataFrame({
        0: ["Date"] + datas,
        1: ["P"] + list(range(1000, 1000 + n)),
        2: ["D"] + [20.0] * n,
        3: ["E"] + [50.0 + i * 0.1 for i in range(n)],
        4: ["CAPE"] + [25.0] * n,
    })
    return df


# ---------------------------------------------------------------------------
# escolher_espelho
# ---------------------------------------------------------------------------

def test_vence_o_espelho_com_dado_mais_recente_nao_o_primeiro_da_lista():
    escolhido = shiller.escolher_espelho({
        LEGADO: pd.Timestamp("2024-06-01"),
        NOVO: pd.Timestamp("2026-08-01"),
    })
    assert escolhido == NOVO


def test_empate_resolve_pela_ordem_de_preferencia_declarada():
    d = pd.Timestamp("2026-08-01")
    assert shiller.escolher_espelho({NOVO: d, LEGADO: d}) == NOVO
    assert shiller.escolher_espelho({LEGADO: d, NOVO: d}) == LEGADO


def test_sem_espelho_nenhum_levanta_em_vez_de_devolver_vazio():
    with pytest.raises(SourceUnavailable):
        shiller.escolher_espelho({})


# ---------------------------------------------------------------------------
# _ultima_observacao
# ---------------------------------------------------------------------------

def test_ultima_observacao_le_a_ultima_linha_com_lucro():
    bruto = _planilha("2026-08-01")
    bruto.attrs["header_row"] = 0
    assert shiller._ultima_observacao(bruto) == pd.Timestamp("2026-08-01")


def test_ultima_observacao_ignora_linha_sem_lucro():
    bruto = _planilha("2026-08-01")
    bruto.loc[bruto.index[-1], 3] = None      # ultimo mes sem lucro publicado
    bruto.attrs["header_row"] = 0
    assert shiller._ultima_observacao(bruto) == pd.Timestamp("2026-07-01")


# ---------------------------------------------------------------------------
# _abrir_tabela: o caminho completo
# ---------------------------------------------------------------------------

def _mock_parse(mapa: dict):
    """_parse_bruto devolvendo a planilha correspondente a cada URL baixada."""
    def _baixar(url):
        if url not in mapa:
            raise SourceUnavailable("404")
        return url.encode()

    def _parse(raw: bytes):
        df = _planilha(mapa[raw.decode()])
        df.attrs["header_row"] = 0
        return df
    return _baixar, _parse


def test_espelho_congelado_perde_para_o_atualizado():
    """O caso de producao, do inicio ao fim: a lista de espelhos comeca pelo
    endereco novo, mas se ele falhar e o legado responder com dado velho, o
    pipeline NAO pode aceitar o velho sem mais nada -- ele consulta os demais e
    fica com o mais recente."""
    baixar, parse = _mock_parse({LEGADO: "2024-06-01", NOVO: "2026-08-01"})
    with mock.patch.object(shiller, "SHILLER_XLS_URLS", (LEGADO, NOVO)), \
         mock.patch.object(shiller, "_baixar", side_effect=baixar), \
         mock.patch.object(shiller, "_parse_bruto", side_effect=parse):
        df = shiller._abrir_tabela()
    assert df.attrs["espelho"] == NOVO
    assert df.attrs["ultima_observacao"] == pd.Timestamp("2026-08-01")


def test_espelho_fresco_encerra_a_busca_sem_baixar_os_demais():
    """Custo: no caso normal, um download, nao tres."""
    baixar, parse = _mock_parse({NOVO: "2026-08-01", LEGADO: "2024-06-01"})
    espiao = mock.Mock(side_effect=baixar)
    # Tolerancia generosa em vez de relogio falso: o que se afirma aqui e "se o
    # primeiro espelho esta dentro da tolerancia, os outros nao sao baixados",
    # e isso independe da data em que a suite roda.
    with mock.patch.object(shiller, "SHILLER_XLS_URLS", (NOVO, LEGADO)), \
         mock.patch.object(shiller, "FRESCOR_ACEITAVEL_DIAS", 100_000), \
         mock.patch.object(shiller, "_baixar", espiao), \
         mock.patch.object(shiller, "_parse_bruto", side_effect=parse):
        shiller._abrir_tabela()
    assert espiao.call_count == 1


def test_espelho_que_nao_responde_nao_derruba_os_outros():
    baixar, parse = _mock_parse({LEGADO: "2024-06-01"})
    with mock.patch.object(shiller, "SHILLER_XLS_URLS", ("https://exemplo/morto", LEGADO)), \
         mock.patch.object(shiller, "_baixar", side_effect=baixar), \
         mock.patch.object(shiller, "_parse_bruto", side_effect=parse):
        df = shiller._abrir_tabela()
    assert df.attrs["espelho"] == LEGADO
    assert any("morto" in r for r in df.attrs["espelhos_recusados"])


def test_nenhum_espelho_responde_levanta_com_os_erros_de_cada_um():
    baixar, parse = _mock_parse({})
    with mock.patch.object(shiller, "SHILLER_XLS_URLS", (NOVO, LEGADO)), \
         mock.patch.object(shiller, "_baixar", side_effect=baixar), \
         mock.patch.object(shiller, "_parse_bruto", side_effect=parse):
        with pytest.raises(SourceUnavailable) as e:
            shiller._abrir_tabela()
    assert "nenhum espelho" in str(e.value)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def test_config_mantem_o_endereco_vigente_antes_do_legado():
    from src import config
    assert len(config.SHILLER_XLS_URLS) >= 2
    assert "70fec4f5" in config.SHILLER_XLS_URLS[0], (
        "o primeiro espelho tem de ser o endereco vigente do shillerdata.com")
    assert config.SHILLER_XLS_URLS[-1].endswith("downloads/ie_data.xls"), (
        "o legado fica por ultimo: ele responde 200 com arquivo de 2024")
