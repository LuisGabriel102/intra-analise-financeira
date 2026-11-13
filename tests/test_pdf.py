"""Leitura dos 3 PDFs do desafio (os arquivos ficam em dados/pdfs)."""

import pytest

from analise_financeira.pdf import ler_pdf

PASTA = "dados/pdfs"


@pytest.fixture(scope="module")
def docs():
    return {nome: ler_pdf(f"{PASTA}/{nome}.pdf") for nome in ("Brasal", "Millet", "Light")}


def test_le_os_tres_pdfs_inteiros(docs):
    assert [len(docs[n].paginas) for n in ("Brasal", "Millet", "Light")] == [51, 43, 124]


def test_abre_o_pdf_criptografado_da_brasal(docs):
    assert docs["Brasal"].pagina(8).linhas  # armadilha B4: o PDF é criptografado


def test_linha_de_tabela_vem_inteira_com_as_colunas_separadas(docs):
    assert "RECEITA LÍQUIDA | 31 | - | - | 13.253.286 | 14.897.920" in docs["Light"].pagina(20).linhas


def test_texto_corrido_nao_ganha_separador(docs):
    linhas = docs["Light"].pagina(9).linhas
    assert any(linha.startswith("Em 2022, o EBITDA CVM foi de R$1.180 milhões") for linha in linhas)


def test_pagina_em_branco_da_light(docs):
    p = docs["Light"].pagina(110)
    assert p.vazia and not p.precisa_ocr


def test_escala_e_pagina_impressa(docs):
    dre = docs["Light"].pagina(20)
    assert dre.escala == "mil"
    assert dre.pagina_impressa == 3  # na Light, a página impressa é a do PDF menos 17
    assert docs["Brasal"].pagina(8).pagina_impressa == 6  # na Brasal, menos 2


def test_recusa_arquivo_que_nao_existe():
    with pytest.raises(FileNotFoundError):
        ler_pdf(f"{PASTA}/nao_existe.pdf")


def test_pagina_de_nota_sem_aviso_usa_a_escala_do_documento(docs):
    light = docs["Light"]
    assert light.pagina(105).escala == ""      # a p. 105 não repete "(Em milhares de reais)"
    assert light.escala_padrao == "mil"
    assert light.escala_de(105) == "mil"
    assert light.escala_de(20) == "mil"
