"""O relatório: escape do texto que vem do PDF, faixas de página e o resumo executivo."""

from analise_financeira.esquemas import AnaliseQualitativa, Evidencia, Extracao, Fonte, Item, RespostaPergunta, Uso
from analise_financeira.indicadores import AlertaSaida, Dado, DocumentoAnalisado, Indicador
from analise_financeira.relatorio import (
    ResultadoDocumento,
    _item,
    _paginas,
    _primeira_frase,
    alertas,
    celula,
    pergunta,
    qualitativa,
    repete_achado,
    resumo_executivo,
    tabela,
    texto,
    valores_com_erro,
)


def test_texto_do_pdf_nao_vira_html_nem_quebra_tabela():
    assert texto("<img src=x onerror=alert(1)>") == "&lt;img src=x onerror=alert(1)&gt;"
    assert celula("2022 | 2021\nlinha") == "2022 \\| 2021 linha"


def test_faixas_de_pagina():
    assert _paginas([11, 3, 6, 7, 8, 3]) == "p. 3, 6–8, 11"
    assert _paginas([9, 10]) == "p. 9, 10"
    assert _paginas([]) == ""


def _light():
    vazio = Indicador(status="nao_encontrado")
    receita = Indicador(status="encontrado", variacao=-0.11,
                        atual=Dado(texto="13.253.286", valor_reais=13_253_286_000.0, unidade="R$ mil",
                                   fontes=[Evidencia(pagina=20, trecho="RECEITA")]),
                        anterior=Dado(texto="14.897.920", valor_reais=14_897_920_000.0, unidade="R$ mil"))
    lucro = Indicador(status="encontrado",
                      atual=Dado(texto="(5.672.203)", valor_reais=-5_672_203_000.0, unidade="R$ mil",
                                 fontes=[Evidencia(pagina=20, trecho="LUCRO")]),
                      anterior=Dado(texto="397.945", valor_reais=397_945_000.0, unidade="R$ mil"))
    ebitda = Indicador(status="encontrado", definicao="EBITDA CVM",
                       atual=Dado(texto="R$1.180 milhões", valor_reais=1.18e9, unidade="R$ milhões",
                                  fontes=[Evidencia(pagina=9, trecho="EBITDA")]),
                       calculado=Dado(texto="x", valor_reais=-1_179_644_000.0, unidade="R$"))
    alavancagem = Indicador(status="encontrado", atual=Dado(texto="3,32x", numero=3.32, unidade="x",
                                                             fontes=[Evidencia(pagina=10, trecho="3,32x")]),
                            observacao="Com EBITDA calculado zero ou negativo, a alavancagem calculada não é significativa.")
    numeros = DocumentoAnalisado(
        documento="Light.pdf", empresa="LIGHT S.A.", periodo_atual="2022", periodo_anterior="2021",
        receita_liquida=receita, ebitda=ebitda, margem_ebitda=vazio, lucro_liquido=lucro, lucro_controladores=vazio,
        divida_liquida=Indicador(status="encontrado", atual=Dado(texto="R$9.032 milhões", valor_reais=9.032e9,
                                                                   unidade="R$ milhões")),
        alavancagem=alavancagem, fluxo_caixa_operacional=vazio, capex=vazio,
        alertas=[AlertaSaida(regra="V7", severidade="erro", origem="codigo", mensagem="sinal", campo="ebitda"),
                 AlertaSaida(regra="V11", severidade="aviso", origem="codigo", mensagem="ano", campo="alavancagem")])
    q = AnaliseQualitativa(documento="Light.pdf", paginas_enviadas=[3, 25], tem_relatorio_administracao=True,
                           tom="negativo", uso=Uso(modelo="m"),
                           riscos=[Item(texto="Incerteza sobre a continuidade.", conferido=True,
                                        evidencias=[Evidencia(pagina=25, trecho="incerteza")])])
    ext = Extracao(documento="Light.pdf", paginas_enviadas=[9], campos={}, uso=Uso(modelo="m"))
    return ResultadoDocumento(arquivo="Light.pdf", extracao=ext, numeros=numeros, qualitativa=q)


def test_resumo_executivo_tem_ate_5_linhas_e_mostra_o_erro_do_ebitda():
    linhas = resumo_executivo(_light())
    assert len(linhas) == 5
    assert linhas[0] == "Receita líquida de R$ 13.253,3 milhões, -11,0% contra o período anterior (p. 20)."
    assert linhas[1] == ("Prejuízo líquido de R$ 5.672,2 milhões, contra lucro de R$ 397,9 milhões no período "
                         "anterior (p. 20).")
    assert "⚠️ A conferência (V7) aponta erro" in linhas[2] and "-R$ 1.179,6 milhões" in linhas[2]
    assert "3,32x (⚠️ ver alertas)" in linhas[3]
    assert linhas[4] == "Tom da administração: negativo. Atenção: incerteza sobre a continuidade (p. 25)."


def test_tabela_marca_alerta_nao_encontrado_e_n_a():
    md = "\n".join(tabela([_light()]))
    assert "| EBITDA informado | ⚠️ 1.180,0 (p. 9) |" in md
    assert "| Margem EBITDA informada | ⛔ não encontrado |" in md
    assert "| Alavancagem informada | ⚠️ 3,32x (p. 10) |" in md
    assert "| Alavancagem calculada | n/a (EBITDA negativo) |" in md
    assert "| Variação do lucro líquido | n/a (troca de sinal) |" in md


def test_atencao_do_resumo_prefere_o_que_o_auditor_sustenta_e_fica_curta():
    r = _light()
    r.qualitativa.comparabilidade = [Item(texto="Provisões distorcem a comparação. São R$2.513 milhões.", conferido=True,
                                          fontes=["relatorio_adm"], evidencias=[Evidencia(pagina=9, trecho="p")])]
    r.qualitativa.riscos.insert(0, Item(texto="Há incerteza sobre a continuidade: Existe incerteza significativa.",
                                        conferido=True, fontes=["notas", "auditor"],
                                        evidencias=[Evidencia(pagina=28, trecho="i"), Evidencia(pagina=111, trecho="i")]))
    assert resumo_executivo(r)[4] == ("Tom da administração: negativo. Atenção: há incerteza sobre a continuidade "
                                      "(p. 28, 111).")
    assert _primeira_frase("O ano anterior não foi auditado: As demonstrações de 2021 (p. 3).") == \
        "O ano anterior não foi auditado"
    assert _primeira_frase("Receita de R$ 1.325,1 milhões. Alta forte.") == "Receita de R$ 1.325,1 milhões"


def test_item_que_cita_valor_com_erro_ganha_aviso():
    r = _light()
    suspeitos = valores_com_erro(r.numeros)
    assert suspeitos == [(1.18e9, 1180.0, "V7")]
    citou = Item(texto="O EBITDA CVM foi de R$1.180 milhões, com queda.", conferido=True)
    assert "marcou com erro (V7" in _item(citou, suspeitos)
    assert "marcou com erro" not in _item(Item(texto="A receita foi de R$ 13.253 milhões.", conferido=True), suspeitos)
    r.qualitativa.motivos = [citou]
    assert "marcou com erro (V7" in "\n".join(qualitativa(r))


def test_observacao_da_analise_que_repete_um_alerta_nao_aparece_duas_vezes():
    conhecido = [("O EBITDA da distribuidora: R$1.817 milhões, redução de R$2.996 milhões sobre R$1.179 milhões.", [8])]
    assert repete_achado("Erro de sinal: 1.817, redução de 2.996 em relação a 1.179 em 2021.", [8], conhecido)
    assert not repete_achado("Erro de sinal: 1.817, redução de 2.996 em relação a 1.179.", [9], conhecido)  # outra página
    assert not repete_achado("Na p. 8, a venda foi de 459 MWh, e não 1.817.", [8], conhecido)  # número novo
    assert not repete_achado("A tabela da página 8 tem a unidade errada.", [8], conhecido)  # sem número: fica

    r = _light()
    r.numeros.alertas.append(AlertaSaida(regra="IA", severidade="aviso", origem="ia", paginas=[10],
                                         mensagem="O covenant encerrou 2021 em 3,32x, menor que 3,48x."))
    r.qualitativa.observacoes = [
        Item(texto="O ano do covenant está errado: 3,32x e 3,48x em 2021.", evidencias=[Evidencia(pagina=10, trecho="c")]),
        Item(texto="A unidade é MWh e não MWm: 459 MWh.", evidencias=[Evidencia(pagina=8, trecho="m")])]
    md = "\n".join(alertas([r]))
    assert md.count("3,32x") == 1 and "459 MWh" in md


def test_resposta_com_numero_sem_trecho_ganha_aviso():
    r = RespostaPergunta(numero=5, pergunta="Guidance?", texto="O restante de 38,9% sai até julho.[1]",
                         fontes=[Fonte(documento="Brasal.pdf", paginas=[28], titulo="t", trecho="31,4%")],
                         numeros_sem_fonte=["38,9%"], uso=Uso(modelo="m"))
    md = "\n".join(pergunta(r))
    assert "⚠️ Números que não estão em nenhum dado consultado pelo agente: 38,9%." in md
    assert "sem citação" not in md

    nos_dados = r.model_copy(update={"numeros_sem_fonte": [], "numeros_sem_citacao": ["38,9% (Brasal.pdf, p. 28)"]})
    md = "\n".join(pergunta(nos_dados))
    assert "⚠️ Números sem citação nesta resposta: 38,9% (Brasal.pdf, p. 28)." in md
    assert "não estão em nenhum dado" not in md


def test_item_com_trecho_achado_pelo_codigo_fica_marcado():
    achado = Item(texto="A companhia não tem linhas de crédito.", conferido=True, fontes=["notas"],
                  evidencias=[Evidencia(pagina=26, trecho="não possui linhas de crédito", origem="codigo")])
    linha = _item(achado)
    assert "trecho achado pelo código" in linha and "⚠️" not in linha
    assert "achado pelo código" not in _item(achado.model_copy(update={"evidencias": [Evidencia(pagina=26, trecho="t")]}))


def test_observacao_da_ia_que_bate_com_regra_do_codigo_ganha_a_marca():
    from analise_financeira.relatorio import conferida_em_codigo

    v13 = AlertaSaida(regra="V13", severidade="erro", origem="codigo", paginas=[7, 9],
                      mensagem="Lucro líquido (DRE × DMPL), em R$ mil: valores diferentes: 18.891 (p. [7]); 19.021 (p. [9]).")
    v14 = AlertaSaida(regra="V14", severidade="aviso", origem="codigo", paginas=[7, 11],
                      mensagem="O período comparativo (2021) não foi auditado (p. 7, 11).")
    obs = "A DMPL mostra 14.743 | 4.278 | 19.021, e a DRE mostra 18.891."
    assert conferida_em_codigo(obs, [7, 9], [v14, v13]) == "V13"
    assert conferida_em_codigo(obs, [20], [v13]) is None            # outra página
    assert conferida_em_codigo("A DRE mostra 18.891.", [7], [v13]) is None  # falta um número do alerta
    assert conferida_em_codigo("O ano de 2021 não foi auditado.", [7], [v14]) is None  # alerta sem número: sem marca

    r = _light()
    r.numeros.alertas += [v13, AlertaSaida(regra="IA", severidade="aviso", origem="ia", paginas=[7], mensagem=obs)]
    md = "\n".join(alertas([r]))
    assert "19.021, e a DRE mostra 18.891. *(Mesmo achado da regra V13" in md


def test_pagina_acima_de_31_nao_conta_como_numero_do_achado():
    from analise_financeira.relatorio import conferida_em_codigo

    # Millet: a V13 cita "(p. [42])"; o 42 é página, e não número do achado.
    v13 = AlertaSaida(regra="V13", severidade="erro", origem="codigo", paginas=[6, 42],
                      mensagem="Patrimônio líquido (balanço × notas), em R$ mil: valores diferentes no mesmo documento: "
                               "185.321 (p. [6]); 167.233 (p. [42]).")
    obs = ("O patrimônio líquido da nota de gestão de capital não bate com o balanço. A nota traz Total do patrimônio "
           "líquido (b) | 167.233 | 152.689. O balanço traz Patrimônio líquido consolidado | 163.931 | 152.689 | 185.321 | 171.106.")
    assert conferida_em_codigo(obs, [6, 42], [v13]) == "V13"
    assert conferida_em_codigo("A nota traz 167.233 (p. 42).", [42], [v13]) is None  # falta o 185.321
