"""As contas da solução, conferidas contra o gabarito (seção 4.1 do plano). Valores em R$ mil."""

import pytest

from analise_financeira.calculos import (
    alavancagem,
    divida_liquida_calculada,
    ebitda_calculado,
    margem,
    variacao,
)


def test_margem_ebitda_calculada_das_tres_empresas():
    # Brasal: EBIT 192.840 (p. 8) + depreciação da DFC 29.014 (p. 11)
    assert margem(ebitda_calculado(192_840, 29_014), 1_325_059) == pytest.approx(0.167, abs=0.0005)
    # Millet: EBIT 25.298 (p. 7) + depreciação 18.248 (p. 10)
    assert margem(ebitda_calculado(25_298, 18_248), 462_127) == pytest.approx(0.094, abs=0.0005)
    # Light: EBIT (1.910.411) (p. 20) + depreciação 730.767 (p. 23)
    assert margem(ebitda_calculado(-1_910_411, 730_767), 13_253_286) == pytest.approx(-0.089, abs=0.0005)


def test_margem_sem_receita():
    assert margem(100, 0) is None


@pytest.mark.parametrize(
    ("atual", "anterior", "esperado"),
    [
        (1_325_059, 1_061_410, 0.248),     # Brasal, receita
        (462_127, 199_259, 1.319),         # Millet, receita (não orgânica: armadilha M6)
        (13_253_286, 14_897_920, -0.110),  # Light, receita
        (174_602, 275_560, -0.366),        # Brasal, lucro
        (14_743, 5_371, 1.745),            # Millet, lucro dos controladores
    ],
)
def test_variacao(atual, anterior, esperado):
    assert variacao(atual, anterior) == pytest.approx(esperado, abs=0.0005)


def test_variacao_sem_sentido_vira_none():
    assert variacao(-5_672_203, 397_945) is None  # Light: de lucro para prejuízo
    assert variacao(24_799, -14_293) is None      # Millet: caixa da operação trocou de sinal
    assert variacao(10, 0) is None


def test_variacao_entre_dois_negativos_mostra_piora():
    assert variacao(-150, -100) == pytest.approx(-0.5)


def test_divida_liquida_da_light_bate_com_a_nota():
    # empréstimos e debêntures + swaps − caixa − títulos (p. 105) = 9.032.236
    assert divida_liquida_calculada(10_688_690, 43_886, aplicacoes=2_039_665, derivativos=427_097) == 9_032_236


def test_brasal_tem_caixa_liquido():
    assert divida_liquida_calculada(3_417, 96_453, aplicacoes=78_569) == -171_605


def test_alavancagem():
    assert alavancagem(13_520, 43_546) == pytest.approx(0.31, abs=0.005)  # Millet
    assert alavancagem(9_032_236, -1_179_644) is None                     # Light: EBITDA negativo
