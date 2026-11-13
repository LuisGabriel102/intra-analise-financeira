"""O roteamento acha as demonstrações certas nos 3 PDFs, sem regra feita para uma empresa."""

import pytest

from analise_financeira.pdf import ler_pdf
from analise_financeira.roteamento import rotear


@pytest.fixture(scope="module")
def rotas():
    return {nome: rotear(ler_pdf(f"dados/pdfs/{nome}.pdf")) for nome in ("Brasal", "Millet", "Light")}


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("Brasal", {"balanco": [6, 7], "dre": [8], "dmpl": [10], "dfc": [11]}),
        ("Millet", {"balanco": [6], "dre": [7], "dmpl": [9], "dfc": [10]}),
        ("Light", {"balanco": [18, 19], "dre": [20], "dmpl": [22], "dfc": [23]}),
    ],
)
def test_acha_as_demonstracoes(rotas, nome, esperado):
    r = rotas[nome]
    assert {tipo: r.paginas_do_tipo(tipo) for tipo in esperado} == esperado


def test_tabela_com_titulo_de_balanco_dentro_de_nota_nao_vira_balanco(rotas):
    # Light: o balanço por segmento (p. 45) e o da Amazônia Energia (p. 47) são notas.
    assert 45 not in rotas["Light"].paginas_do_tipo("balanco")
    assert 47 not in rotas["Light"].paginas_do_tipo("balanco")


def test_relatorio_da_administracao_da_light(rotas):
    assert set(range(2, 16)) <= set(rotas["Light"].paginas_do_tipo("relatorio_adm"))


def test_extracao_leva_poucas_paginas_e_as_certas(rotas):
    light = rotas["Light"].extracao
    assert {9, 10, 20, 23, 105} <= set(light)  # EBITDA, dívida, DRE, DFC, gestão de capital
    assert len(light) <= 15                      # de 124 páginas
    assert 42 in rotas["Millet"].extracao        # gestão de capital com a dívida líquida


def test_analise_pega_continuidade_riscos_e_eventos(rotas):
    assert {25, 111} <= set(rotas["Light"].analise)      # nota 1.1 e parecer do auditor
    assert {12, 49, 51} <= set(rotas["Brasal"].analise)  # contexto, riscos, evento subsequente
    assert {11, 27, 43} <= set(rotas["Millet"].analise)  # contexto, aquisição, eventos
