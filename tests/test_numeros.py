"""Testes do leitor de números. Os exemplos vêm dos próprios PDFs do desafio."""

import pytest

from analise_financeira.numeros import (
    Numero,
    achar_numeros,
    detectar_escala,
    em_reais,
    ler_numero,
    numero_aparece,
)


@pytest.mark.parametrize(
    ("texto", "valor", "unidade"),
    [
        ("1.325.059", 1325059.0, ""),             # Brasal, receita (p. 8)
        ("13.253.286", 13253286.0, ""),           # Light, receita (p. 20)
        ("(1.910.411)", -1910411.0, ""),          # Light, EBIT negativo (p. 20)
        ("2.693", 2693.0, ""),                    # ponto é milhar, não decimal
        ("19,30%", 0.193, "%"),
        ("−13%", -0.13, "%"),
        ("3,32x", 3.32, "x"),                     # Light, covenant (p. 10)
        ("0,08", 0.08, ""),
        ("R$1.817 milhões", 1817.0, "milhões"),   # Light, relatório (p. 8)
        ("-R$5.673 milhões", -5673.0, "milhões"), # Light, relatório (p. 10)
        ("R$ 9 bi", 9.0, "bilhões"),
        ("3.417 mil", 3417.0, "mil"),
        ("-", 0.0, ""),                           # traço sozinho = zero
        ("—", 0.0, ""),
    ],
)
def test_ler_numero(texto, valor, unidade):
    n = ler_numero(texto)
    assert n is not None
    assert n.valor == pytest.approx(valor)
    assert n.unidade == unidade


def test_texto_sem_numero():
    assert ler_numero("não encontrado") is None


def test_parenteses_numa_frase_nao_viram_negativo():
    # Light, p. 10: "(3,48x)" é um aparte, não um número negativo.
    numeros = achar_numeros("encerrou 2021 em 3,32x, menor do que no 2021 (3,48x).")
    assert [n.valor for n in numeros] == [2021.0, 3.32, 2021.0, 3.48]


def test_menos_entre_parenteses_continua_negativo():
    # Light, p. 8: "(-R$1.081 milhões)"
    n = ler_numero("conforme Lei 14.385/22 (-R$1.081 milhões), revisão")
    assert n is not None and n.valor == 14385.0  # o primeiro número é o da lei
    valores = [x.valor for x in achar_numeros("conforme Lei 14.385/22 (-R$1.081 milhões), revisão")]
    assert -1081.0 in valores


def test_hifen_dentro_de_palavra_nao_e_sinal():
    assert [n.valor for n in achar_numeros("efeitos da COVID-19 em 31-12-2022")] == [19.0, 31.0, 12.0, 2022.0]


def test_linha_de_tabela_com_tracos_e_parenteses():
    # Light, DRE (p. 20). Os traços são células vazias da controladora.
    linha = "CUSTO TOTAL | 32 | - | - (11.271.467) (12.476.958)"
    assert [n.valor for n in achar_numeros(linha)] == [32.0, -11271467.0, -12476958.0]


def test_numero_aparece_confere_o_sinal():
    linha = "LUCRO (PREJUÍZO) LÍQUIDO DO EXERCÍCIO | (5.672.203) | 397.945 | (5.672.203) | 397.945"
    assert numero_aparece(-5672203, linha)
    assert not numero_aparece(5672203, linha)  # sem o sinal, não vale
    assert not numero_aparece(-5672204, linha)


def test_detectar_escala():
    assert detectar_escala("DEMONSTRAÇÕES DE RESULTADOS\n(Em milhares de reais, exceto lucro por ação)") == "mil"
    assert detectar_escala("Valores expressos em milhões de reais") == "milhões"
    assert detectar_escala("Em 2022, o EBITDA CVM foi de R$1.180 milhões") == ""  # a escala está no número


def test_em_reais_usa_a_escala_do_numero_ou_da_pagina():
    assert em_reais(ler_numero("R$1.180 milhões")) == 1_180_000_000
    assert em_reais(ler_numero("(1.910.411)"), escala_da_pagina="mil") == -1_910_411_000


def test_em_reais_recusa_percentual():
    with pytest.raises(ValueError):
        em_reais(Numero(0.193, "%", "19,30%"))
