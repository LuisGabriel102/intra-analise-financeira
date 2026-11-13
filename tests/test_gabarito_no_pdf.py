"""O gabarito confere com o PDF original: cada valor esperado está na página indicada, com o mesmo sinal.

Isso impede que o próprio gabarito tenha número errado. Ele foi montado lendo as
páginas; este teste confere em código, direto no PDF.
"""

import json
from pathlib import Path

import pytest

from analise_financeira.numeros import ler_numero, numero_aparece
from analise_financeira.pdf import ler_pdf

GABARITO = json.loads(Path("avaliacao/gabarito.json").read_text(encoding="utf-8"))
DOCUMENTOS = [nome for nome in GABARITO if not nome.startswith("_")]


def _casos():
    for doc in DOCUMENTOS:
        for campo, esperado in GABARITO[doc]["campos"].items():
            for item in (esperado, esperado.get("tambem")):
                if item and "valor" in item:
                    yield doc, campo, item["valor"], item["paginas"]


@pytest.fixture(scope="module")
def pdfs():
    return {doc: ler_pdf(f"dados/pdfs/{doc}") for doc in DOCUMENTOS}


@pytest.mark.parametrize(("doc", "campo", "valor", "paginas"), list(_casos()))
def test_valor_do_gabarito_esta_na_pagina(pdfs, doc, campo, valor, paginas):
    numero = ler_numero(valor)
    assert numero is not None, f"{doc} {campo}: '{valor}' não é número"
    for pagina in paginas:
        assert numero_aparece(numero.valor, pdfs[doc].pagina(pagina).texto), f"{doc} {campo}: {valor} não está na p. {pagina}"
