"""Cada armadilha dos PDFs do desafio virou um teste.

O código de cada caso (L1, M4, B6...) é o da seção 3.5 do plano.
Valores das tabelas em R$ mil; valores do relatório da Light em R$ milhões.
As regras recebem dinheiro em reais, por isso os "* MIL" e "* MI".
"""

from datetime import date

import pytest

from analise_financeira.validacao import (
    conferir_alavancagem,
    conferir_ano_no_texto,
    conferir_anos_do_cabecalho,
    conferir_auditoria,
    conferir_datas,
    conferir_direcao,
    conferir_divida_liquida,
    conferir_ebitda,
    conferir_escala,
    conferir_margem,
    conferir_ocorrencias,
    conferir_soma,
    conferir_variacao_absoluta,
    conferir_variacao_percentual,
    direcao_da_frase,
    ler_data,
)

MIL = 1_000
MI = 1_000_000


# ------------------------------------------------------------ Light: o sinal perdido


def test_L1_ebitda_da_light_com_o_sinal_trocado():
    # Relatório (p. 9): "o EBITDA CVM foi de R$1.180 milhões".
    # DRE (p. 20): EBIT (1.910.411). DFC (p. 23): depreciação 730.767.
    alerta = conferir_ebitda(1_180 * MI, -1_910_411 * MIL, 730_767 * MIL)
    assert alerta is not None
    assert alerta.severidade == "erro"
    assert "sinal trocado" in alerta.mensagem


def test_L1_a_reducao_de_3001_so_fecha_com_o_ebitda_negativo():
    # "redução R$3.001 milhões se comparado a 2021". EBITDA de 2021 = 1.143.301 + 678.110.
    ebitda_2021 = (1_143_301 + 678_110) * MIL
    alerta = conferir_variacao_absoluta(-3_001 * MI, 1_180 * MI, ebitda_2021)
    assert alerta is not None and "sinal de menos perdido" in alerta.mensagem


def test_L2_ebitda_da_distribuidora():
    # p. 8: "R$1.817 milhões, uma redução de R$2.996 milhões em relação aos R$1.179 milhões".
    alerta = conferir_variacao_absoluta(-2_996 * MI, 1_817 * MI, 1_179 * MI)
    assert alerta is not None and "sinal de menos perdido" in alerta.mensagem


def test_L3_covenant_com_o_ano_errado():
    frase = "encerrou 2021 em 3,32x, menor do que no 2021 (3,48x)."  # p. 10
    alerta = conferir_ano_no_texto(frase, "3,32x", periodo="2022")
    assert alerta is not None and "2021" in alerta.mensagem


def test_L5_lucro_do_relatorio_nao_e_arredondamento():
    # Relatório (p. 10): -R$5.673 milhões. DRE (p. 20): (5.672.203) mil, que arredonda para -5.672.
    alerta = conferir_escala(-5_673, "milhões", -5_672_203 * MIL)
    assert alerta is not None and alerta.severidade == "info"


def test_arredondamento_de_verdade_nao_gera_alerta():
    # Dívida líquida: R$9.032 milhões no relatório (p. 10) e 9.032.236 mil na nota (p. 105).
    assert conferir_escala(9_032, "milhões", 9_032_236 * MIL) is None


def test_erro_de_escala_mil_contra_milhoes():
    alerta = conferir_escala(9_032_236, "milhões", 9_032_236 * MIL)
    assert alerta is not None and "escala" in alerta.mensagem


def test_L6_cabecalho_com_2021_repetido():
    assert conferir_anos_do_cabecalho("2022 | 2021 | 2021 | 2021", "2022", "2021") is not None  # p. 21


def test_L9_ano_malformado_no_cabecalho():
    assert conferir_anos_do_cabecalho("31.12.20212 | 31.12.2021", "2022", "2021") is not None  # p. 65


def test_cabecalho_normal_nao_gera_alerta():
    assert conferir_anos_do_cabecalho("2022 | 2021 | 2022 | 2021", "2022", "2021") is None


def test_L10_lucro_da_lightcom_caiu_mas_o_texto_diz_acima():
    frase = "o Resultado líquido foi de R$87 milhões, 15,5% acima do apurado em 2021."  # p. 9
    assert direcao_da_frase(frase) == 1
    alerta = conferir_direcao(frase, atual=87_073, anterior=102_822)  # nota 4, p. 45
    assert alerta is not None and "caiu" in alerta.mensagem
    assert conferir_variacao_percentual(0.155, 87_073, 102_822) is not None


def test_L3_menor_bate_com_a_queda_de_348_para_332():
    assert conferir_direcao("menor do que no 2021 (3,48x)", atual=3.32, anterior=3.48) is None


def test_alavancagem_com_ebitda_negativo():
    # Light: 3,32x informado (p. 10), mas o EBITDA CVM é negativo.
    alerta = conferir_alavancagem(3.32, 9_032_236 * MIL, -1_179_644 * MIL)
    assert alerta is not None and "outra definição" in alerta.mensagem


def test_divida_liquida_da_light_fecha():
    assert conferir_divida_liquida(9_032_236, 10_688_690, 43_886, aplicacoes=2_039_665, derivativos=427_097) is None


def test_divida_liquida_da_millet_fecha():
    assert conferir_divida_liquida(13_520, 24_176, 10_656) is None  # p. 42


# ------------------------------------------------------------ Millet


def test_M1_patrimonio_liquido_da_nota_nao_bate_com_o_balanco():
    alerta = conferir_ocorrencias("Patrimônio líquido", [(167_233, "nota 22, p. 42"), (185_321, "balanço, p. 6")])
    assert alerta is not None and alerta.severidade == "erro"


def test_M2_lucro_consolidado_dre_contra_dmpl():
    alerta = conferir_ocorrencias("Lucro líquido consolidado", [(18_891, "DRE, p. 7"), (19_021, "DMPL, p. 9")])
    assert alerta is not None and alerta.severidade == "erro"


def test_M3_equivalencia_dre_contra_fluxo_de_caixa():
    alerta = conferir_ocorrencias("Equivalência patrimonial", [(28_355, "DRE, p. 7"), (27_247, "DFC, p. 10")])
    assert alerta is not None


def test_M4_total_com_um_digito_faltando():
    # p. 42: caixa 10.656 + clientes 98.663 + outros 1.033 = 110.352, mas o total diz 10.352.
    alerta = conferir_soma([10_656, 98_663, 1_033], 10_352)
    assert alerta is not None and "dígito" in alerta.mensagem


def test_M4_cabecalho_com_2021_repetido():
    alerta = conferir_anos_do_cabecalho("31/12/2021 | 31/12/2021 | 31/12/2022 | 31/12/2021", "2022", "2021")
    assert alerta is not None


def test_M5_aprovacao_antes_do_fim_do_exercicio():
    aprovacao = ler_data("foi aprovada e pela administração em 14 de março de 2022.")  # p. 12
    parecer = ler_data("Rio de Janeiro, 15 de maio de 2023.")                          # p. 5
    assert aprovacao == date(2022, 3, 14) and parecer == date(2023, 5, 15)
    assert conferir_datas(aprovacao, date(2022, 12, 31), parecer) is not None


def test_M7_diferenca_pequena_vira_info():
    alerta = conferir_ocorrencias("Empréstimos 2021", [(25_072, "gestão de capital, p. 42"),
                                                       (25_075, "instrumentos financeiros, p. 42")])
    assert alerta is not None and alerta.severidade == "info"


def test_caixa_com_diferenca_de_1_e_arredondamento():
    assert conferir_ocorrencias("Caixa final", [(10_655, "DFC, p. 10"), (10_656, "balanço, p. 6")]) is None


def test_M8_lucro_antes_dos_impostos_da_alibra():
    # p. 29: 98.338 − 63.419 − 2.331 = 32.588, mas o resumo mostra (65.750).
    assert conferir_soma([98_338, -63_419, -2_331], -65_750) is not None


# ------------------------------------------------------------ Brasal


def test_B1_ano_anterior_nao_auditado():
    texto = ("As demonstrações financeiras individuais e consolidadas da Companhia para o exercício findo em 31 "
             "de dezembro de 2021, apresentadas para fins de comparação, não foram auditadas por nós")  # p. 3
    assert conferir_auditoria(texto, pagina=3) is not None


def test_texto_normal_nao_gera_alerta_de_auditoria():
    assert conferir_auditoria("Examinamos as demonstrações financeiras da Companhia.", pagina=3) is None


def test_B6_equivalencia_da_nota_contra_a_dre():
    alerta = conferir_ocorrencias("Equivalência patrimonial 2022", [(157_810, "nota 12, p. 32"), (177_244, "DRE, p. 8")])
    assert alerta is not None


def test_B7_credito_de_pis_cofins_em_tres_lugares():
    alerta = conferir_ocorrencias("Crédito de PIS/COFINS 2021", [(100_875, "nota 8, p. 28"), (105_633, "DFC, p. 11"),
                                                                 (105_633, "nota 23, p. 46")])
    assert alerta is not None


# ------------------------------------------------------------ margem e variação


def test_margem_que_bate_nao_gera_alerta():
    assert conferir_margem(0.167, 221_854, 1_325_059) is None


def test_margem_errada():
    alerta = conferir_margem(0.20, 221_854, 1_325_059)
    assert alerta is not None and "16,7%" in alerta.mensagem


def test_margem_com_receita_zero_nao_quebra():
    alerta = conferir_margem(0.10, 5_000, 0)
    assert alerta is not None and alerta.severidade == "aviso"


def test_uma_ocorrencia_so_nao_tem_o_que_comparar():
    assert conferir_ocorrencias("Lucro", [(174_602, "DRE, p. 8")]) is None


def test_variacao_percentual_da_receita_da_light_sem_construcao():
    # Relatório (p. 9): receita de R$ 12.107 milhões, −13%. Sem o valor de 2021 no texto, só a DRE confere.
    assert conferir_variacao_percentual(-0.110, 13_253_286, 14_897_920) is None


@pytest.mark.parametrize("frase", ["houve um aumento de 10%", "alta de 5%", "ficou acima do previsto"])
def test_direcao_sobe(frase):
    assert direcao_da_frase(frase) == 1


@pytest.mark.parametrize("frase", ["uma redução de R$2.996 milhões", "queda de 3%", "11,8% abaixo da registrada"])
def test_direcao_desce(frase):
    assert direcao_da_frase(frase) == -1
