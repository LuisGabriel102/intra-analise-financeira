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


# ------------------------------------------------------------------ armadilhas, qualitativa e perguntas

from analise_financeira.avaliacao import armadilhas_detectadas, avaliar_perguntas, avaliar_qualitativa  # noqa: E402
from analise_financeira.esquemas import AnaliseQualitativa, Item, RespostaPergunta  # noqa: E402
from analise_financeira.indicadores import AlertaSaida, DocumentoAnalisado, Indicador  # noqa: E402


def _numeros(alertas):
    vazio = Indicador(status="nao_encontrado")
    return DocumentoAnalisado(documento="Light.pdf", empresa="L", periodo_atual="2022", periodo_anterior="2021",
                              receita_liquida=vazio, ebitda=vazio, margem_ebitda=vazio, lucro_liquido=vazio,
                              lucro_controladores=vazio, divida_liquida=vazio, alavancagem=vazio,
                              fluxo_caixa_operacional=vazio, capex=vazio, alertas=alertas)


def _ia(mensagem, paginas):
    return AlertaSaida(regra="IA", severidade="aviso", origem="ia", mensagem=mensagem, paginas=paginas)


def test_armadilha_da_ia_precisa_falar_do_assunto_e_codigo_vale_pela_regra():
    esperadas = [{"id": "L10", "regra": "V6", "paginas": [9], "termos_ia": ["lightcom"]},
                 {"id": "L1", "regra": "V7", "paginas": [9]},
                 {"id": "L2", "regra": "IA", "paginas": [8], "termos_ia": ["distribuidora"]}]
    alertas = [_ia("O EBITDA do grupo está com sinal trocado", [9]),          # p. 9, mas não fala da Lightcom
               AlertaSaida(regra="V7", severidade="erro", origem="codigo", mensagem="sinal", paginas=[9, 20])]
    extras = [_ia("A Lightcom diz que subiu, mas a nota mostra queda", [9, 45])]
    sem = {a["id"]: a for a in armadilhas_detectadas(_numeros(alertas), esperadas)}
    com = {a["id"]: a for a in armadilhas_detectadas(_numeros(alertas), esperadas, extras)}
    assert not sem["L10"]["detectada"] and com["L10"]["por"] == "IA" and "Lightcom" in com["L10"]["mensagem"]
    assert com["L1"]["por"] == "código"
    assert not com["L2"]["detectada"]


def test_qualitativa_confere_tom_guidance_mencoes_e_erro_proibido():
    esperado = {"tom": ["negativo"], "tem_relatorio_administracao": True, "guidance": "nao_encontrado",
                "deve_mencionar": [{"o_que": "continuidade", "secoes": ["riscos"], "termos": ["continuidade"]}],
                "nao_deve": [{"o_que": "RJ da Light", "termos": ["recuperacao judicial"], "exceto": ["supervia"]}]}
    q = AnaliseQualitativa(documento="Light.pdf", paginas_enviadas=[3], tem_relatorio_administracao=True,
                           tom="negativo", guidance_status="nao_encontrado", uso=Uso(modelo="m"),
                           riscos=[Item(texto="Incerteza sobre a continuidade operacional.", conferido=True)],
                           eventos=[Item(texto="A Light entrou em recuperação judicial.")])
    r = avaliar_qualitativa(q, esperado)
    assert [c["ok"] for c in r["checagens"]] == [True, True, True, True, False]
    assert r["itens"] == 2 and r["com_trecho"] == 1


def test_perguntas_conferem_termos_alternativos_e_fonte():
    esperado = {"3": {"deve_conter": [["light"], ["3,32"]]}, "5": {"deve_conter": [["nenhuma", "nao divulg"]]}}
    uso = Uso(modelo="m")
    respostas = [RespostaPergunta(numero=3, pergunta="?", texto="Sim: a Light, com 3,32x.[1]", uso=uso,
                                  fontes=[{"documento": "Light.pdf", "paginas": [10], "titulo": "t", "trecho": "3,32x"}]),
                 RespostaPergunta(numero=5, pergunta="?", texto="A Brasal projeta crescer.", uso=uso)]
    r = {x["numero"]: x for x in avaliar_perguntas(respostas, esperado)}
    assert r[3]["ok"] and not r[5]["ok"] and r[5]["faltam"] == ["nenhuma ou nao divulg"]
