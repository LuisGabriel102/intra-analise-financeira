"""O roteamento acha as demonstrações certas nos 3 PDFs, sem regra feita para uma empresa."""

import pytest

from analise_financeira.pdf import ler_pdf
from analise_financeira.roteamento import LIMITE_ANALISE, TABELAS, rotear

NOMES = ("Brasal", "Millet", "Light")


@pytest.fixture(scope="module")
def documentos():
    return {nome: ler_pdf(f"dados/pdfs/{nome}.pdf") for nome in NOMES}


@pytest.fixture(scope="module")
def rotas(documentos):
    return {nome: rotear(doc) for nome, doc in documentos.items()}


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
    # Light: relatório inteiro, contexto, continuidade, segmento, ativos à venda, risco, eventos, parecer
    assert set(range(1, 16)) | {17, 25, 28, 45, 46, 101, 107, 111, 112} <= set(rotas["Light"].analise)
    assert {1, 3, 12, 28, 46, 49, 51} <= set(rotas["Brasal"].analise)   # parecer, contexto, créditos, riscos, STF
    assert {11, 27, 28, 29, 43} <= set(rotas["Millet"].analise)         # contexto, Alibra no ano cheio, eventos


@pytest.mark.parametrize("nome", NOMES)
def test_analise_cabe_no_orcamento_e_nao_le_tabelas(documentos, rotas, nome):
    r = rotas[nome]
    assert sum(len(documentos[nome].pagina(n).texto) for n in r.analise) <= LIMITE_ANALISE
    assert not [n for n in r.analise if r.tipos[n] in TABELAS]


def test_nao_auditado_nas_tabelas_nao_puxa_pagina_sozinho(rotas):
    # Brasal: "(não auditado)" é rótulo de coluna em quase todas as notas; não é assunto da página.
    from analise_financeira.roteamento import prioridade_na_analise

    r = rotas["Brasal"]
    assert prioridade_na_analise(r.tipos[26], r.assuntos[26]) == 3
