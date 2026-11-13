"""A avaliação conta acerto de valor, de página, de "não encontrado" e número inventado."""

from analise_financeira.avaliacao import avaliar_documento
from analise_financeira.esquemas import Campo, Evidencia, Extracao, Ocorrencia, Uso


def _campo(texto, numero, reais, pagina, unidade="R$ mil", conferido=True):
    o = Ocorrencia(texto=texto, numero=numero, unidade=unidade, valor_reais=reais, conferido=conferido,
                   evidencias=[Evidencia(pagina=pagina, trecho=texto)])
    return Campo(status="encontrado" if conferido else "sem_evidencia", principal=o, ocorrencias=[o])


ESPERADO = {"campos": {
    "receita_liquida_atual": {"valor": "13.253.286", "paginas": [20]},
    "divida_liquida_atual": {"valor": "9.032.236", "paginas": [105], "tambem": {"valor": "R$9.032 milhões", "paginas": [10]}},
    "alavancagem_atual": {"valor": "3,32x", "paginas": [10]},
    "margem_ebitda_atual": {"status": "nao_encontrado"},
    "ebitda_atual": {"status": "nao_encontrado"},
}}


def _extracao(campos):
    return Extracao(documento="X.pdf", paginas_enviadas=[10, 20], campos=campos, uso=Uso(modelo="m"))


def test_tudo_certo():
    ext = _extracao({
        "receita_liquida_atual": _campo("13.253.286", 13_253_286, 13_253_286_000, 20),
        # O relatório diz R$ 9.032 milhões; o gabarito aceita a nota (mil) ou o relatório (milhões).
        "divida_liquida_atual": _campo("R$9.032 milhões", 9_032, 9_032_000_000, 10, "R$ milhões"),
        "alavancagem_atual": _campo("3,32x", 3.32, None, 10, "x"),
        "margem_ebitda_atual": Campo(status="nao_encontrado"),
        "ebitda_atual": Campo(status="nao_encontrado"),
    })
    c = avaliar_documento(ext, ESPERADO)["contagem"]
    assert (c["valor_ok"], c["pagina_ok"], c["nao_enc_ok"], c["inventou"]) == (3, 3, 2, 0)


def test_valor_errado_pagina_errada_e_numero_inventado():
    ext = _extracao({
        "receita_liquida_atual": _campo("14.897.920", 14_897_920, 14_897_920_000, 20),  # pegou o ano anterior
        "alavancagem_atual": _campo("3,32x", 3.32, None, 9, "x"),                       # página errada
        "ebitda_atual": _campo("221.854", 221_854, 221_854_000, 8),                     # inventou um EBITDA
    })
    r = avaliar_documento(ext, ESPERADO)
    c = r["contagem"]
    assert c["valor_ok"] == 1 and c["pagina_ok"] == 1
    assert c["inventou"] == 1 and c["nao_enc_ok"] == 0
    assert r["evidencia_conferida"] == (3, 3)
