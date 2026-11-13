"""O relatório: escape do texto que vem do PDF, faixas de página e o resumo executivo."""

from analise_financeira.esquemas import AnaliseQualitativa, Evidencia, Extracao, Item, Uso
from analise_financeira.indicadores import AlertaSaida, Dado, DocumentoAnalisado, Indicador
from analise_financeira.relatorio import ResultadoDocumento, _paginas, celula, resumo_executivo, tabela, texto


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
