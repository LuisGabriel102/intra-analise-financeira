"""O analista monta o pedido com citações, lê "campo: texto" e confere trechos e números.

A resposta da IA aqui é falsa, mas no formato real da API (citações content_block_location).
"""

import pytest
from falsos import SdkFalso

from analise_financeira.analista import (
    CAMPOS,
    DEFINICAO_GUIDANCE,
    SISTEMA,
    achados_conhecidos,
    analisar,
    ler_resposta,
    ler_tom,
    montar_conteudo,
    numeros_sem_fonte,
)
from analise_financeira.indicadores import AlertaSaida, Dado, DocumentoAnalisado, Indicador
from analise_financeira.llm import ClienteLLM, Resposta
from analise_financeira.pdf import Documento, Pagina
from analise_financeira.roteamento import Rotas

P3 = ["Mensagem da Administração", "O ano de 2022 foi um momento especialmente desafiador.",
      "As provisões somaram R$2.513 milhões e pesaram no resultado."]
P25 = ["1.1 Continuidade operacional", "Existe incerteza significativa relacionada com a continuidade operacional.",
       "A Companhia pretende buscar a renovação antecipada da concessão."]


@pytest.fixture
def documento():
    paginas = [Pagina(numero=n, linhas=[f"linha {n}"]) for n in range(1, 26)]
    paginas[2] = Pagina(numero=3, linhas=P3)
    paginas[24] = Pagina(numero=25, linhas=P25, escala="mil")
    return Documento(nome="Light.pdf", paginas=paginas, escala_padrao="mil")


@pytest.fixture
def rotas():
    return Rotas(tipos={3: "relatorio_adm", 25: "notas"}, analise=[3, 25])


def vazio() -> Indicador:
    return Indicador(status="nao_encontrado")


@pytest.fixture
def numeros():
    receita = Indicador(status="encontrado", variacao=-0.11,
                        atual=Dado(texto="13.253.286", valor_reais=13_253_286_000.0, unidade="R$ mil"),
                        anterior=Dado(texto="14.897.920", valor_reais=14_897_920_000.0, unidade="R$ mil"))
    return DocumentoAnalisado(
        documento="Light.pdf", empresa="Light S.A.", periodo_atual="2022", periodo_anterior="2021",
        receita_liquida=receita, ebitda=vazio(), margem_ebitda=vazio(), lucro_liquido=vazio(),
        lucro_controladores=vazio(), divida_liquida=vazio(), alavancagem=vazio(), fluxo_caixa_operacional=vazio(),
        capex=vazio())


def cita(indice_doc: int, inicio: int, linhas: list[str]) -> dict:
    return {"type": "content_block_location", "document_index": indice_doc, "start_block_index": inicio,
            "end_block_index": inicio + 1, "cited_text": linhas[inicio]}


def resposta(blocos: list[dict]) -> Resposta:
    return Resposta(blocos=blocos, modelo="claude-opus-5-5", tokens_entrada=1000, tokens_saida=200)


BLOCOS = [
    {"type": "text", "text": "motivo: "},
    {"type": "text", "text": "Provisões de R$ 2.513 milhões pesaram no resultado (administração).",
     "citations": [cita(0, 2, P3)]},
    {"type": "text", "text": "\nmotivo: "},
    {"type": "text", "text": "A receita caiu 15%.", "citations": [cita(0, 2, P3)]},
    {"type": "text", "text": "\nrisco: "},
    {"type": "text", "text": "Incerteza sobre a continuidade operacional.", "citations": [cita(1, 1, P25)]},
    {"type": "text", "text": "\nguidance: não encontrado\nperspectiva: "},
    {"type": "text", "text": "Buscar a renovação antecipada da concessão.", "citations": [cita(1, 2, P25)]},
    {"type": "text", "text": "\nevento: Troca do presidente em 2022.\ncomparabilidade: não encontrado\ntom: Negativo."},
    {"type": "text", "text": "\njustificativa_tom: "},
    {"type": "text", "text": "A administração fala em momento desafiador.", "citations": [cita(0, 1, P3)]},
    {"type": "text", "text": "\n**Observação**: "},
    {"type": "text", "text": "O texto não explica a provisão.", "citations": [cita(0, 2, P3)]},
]


def test_pedido_tem_as_paginas_os_numeros_e_os_campos(documento, rotas, numeros):
    conteudo = montar_conteudo(documento, rotas, numeros)
    assert [c["title"] for c in conteudo[:2]] == ["Light.pdf, página 3", "Light.pdf, página 25"]
    pedido = conteudo[-1]["text"]
    assert all(f"- {nome}:" in pedido for nome in CAMPOS)
    assert "R$ 13.253,3 milhões" in pedido and "-11,0%" in pedido   # números conferidos, como contexto
    assert "administração (relatório ou mensagem da administração): 3." in pedido


def test_le_itens_trechos_e_fontes(documento, rotas, numeros):
    from analise_financeira.analista import resumo_numeros

    a = ler_resposta(resposta(BLOCOS), documento, rotas, contexto=resumo_numeros(numeros))
    assert [m.texto for m in a.motivos][0].startswith("Provisões de R$ 2.513 milhões")
    primeiro = a.motivos[0]
    assert primeiro.conferido and primeiro.evidencias[0].pagina == 3 and primeiro.fontes == ["relatorio_adm"]
    assert primeiro.numeros_sem_fonte == []
    assert a.motivos[1].numeros_sem_fonte == ["15%"]          # nem no trecho, nem nos números conferidos
    assert a.riscos[0].evidencias[0].trecho == P25[1] and a.riscos[0].fontes == ["notas"]
    assert a.guidance_status == "nao_encontrado" and a.guidance == []
    assert len(a.perspectivas) == 1
    assert a.eventos[0].conferido is False                  # sem citação: aparece marcado no relatório
    assert a.comparabilidade == [] and "comparabilidade" in a.nao_encontrados
    assert a.tom == "negativo" and a.justificativa_tom.conferido
    assert len(a.observacoes) == 1                          # "**Observação**" vira "observacao"
    assert a.tem_relatorio_administracao


def test_guidance_que_diz_que_nao_ha_meta_nao_conta_como_encontrado(documento, rotas):
    blocos = [{"type": "text", "text": "guidance: "},
              {"type": "text", "text": "Não há meta numérica; a empresa pretende renovar a concessão.",
               "citations": [cita(1, 2, P25)]}]
    a = ler_resposta(resposta(blocos), documento, rotas, contexto="")
    assert a.guidance_status == "nao_encontrado"
    assert a.tom is None                                    # a IA não respondeu o tom


@pytest.mark.parametrize(("texto", "tom"), [
    ("negativo, porque o prejuízo foi alto", "negativo"),
    ("Não aplicável: só há notas técnicas", "nao_aplicavel"),
    ("nao_aplicavel", "nao_aplicavel"),
    ("neutro a levemente negativo", "neutro"),
    ("cauteloso", None),
])
def test_le_o_tom(texto, tom):
    assert ler_tom(texto) == tom


@pytest.mark.parametrize(("texto", "fontes", "faltando"), [
    ("prejuízo de R$ 5,7 bilhões", [("LUCRO LÍQUIDO | (5.672.203) | 397.945", "mil")], []),   # 1% de folga
    ("prejuízo de R$ 6,7 bilhões", [("LUCRO LÍQUIDO | (5.672.203) | 397.945", "mil")], ["R$ 6,7 bilhões"]),
    ("a receita da Alibra foi de 462.127", [("Receita operacional líquida | 462.127 | 318.317", "mil")], []),
    ("margem de 16,7%", [("Margem EBITDA: calculado pela solução 16,7%", "milhões")], []),
    ("em 2022, por 2 trimestres seguidos", [("", "mil")], []),                                # ano e contagem
    ("nos próximos 36 meses", [("maximizar o caixa nos próximos 36 meses", "mil")], []),
    ("alavancagem de 3,32x", [("3,48x em 2021", "mil")], ["3,32x"]),
])
def test_numeros_sem_fonte(texto, fontes, faltando):
    assert numeros_sem_fonte(texto, fontes) == faltando


def test_analisar_grava_e_o_replay_nao_chama_a_api(tmp_path, documento, rotas, numeros):
    sdk = SdkFalso(BLOCOS)
    cliente = ClienteLLM(sdk=sdk, pasta_gravacoes=tmp_path / "g", arquivo_traces=tmp_path / "t.jsonl")
    primeira = analisar(documento, rotas, numeros, cliente)
    assert sdk.chamadas == 1 and not primeira.uso.gravada
    assert "temperature" not in sdk.ultimo_pedido
    assert sdk.ultimo_pedido["output_config"] == {"effort": "high"}

    replay = ClienteLLM(replay=True, pasta_gravacoes=tmp_path / "g", arquivo_traces=tmp_path / "t.jsonl")
    segunda = analisar(documento, rotas, numeros, replay)
    assert segunda.uso.gravada and segunda.tom == primeira.tom == "negativo"
    assert sdk.chamadas == 1


def test_resposta_cortada_fica_marcada(documento, rotas):
    r = resposta(BLOCOS)
    r.parada = "max_tokens"
    assert ler_resposta(r, documento, rotas, contexto="").completa is False


def test_aceita_titulo_com_lista_e_nome_no_plural(documento, rotas):
    blocos = [
        {"type": "text", "text": "Análise:\n**Riscos:**\n- "},
        {"type": "text", "text": "Incerteza sobre a continuidade.", "citations": [cita(1, 1, P25)]},
        {"type": "text", "text": "\n2. "},
        {"type": "text", "text": "Provisões altas: R$ 2.513 milhões.", "citations": [cita(0, 2, P3)]},
        {"type": "text", "text": "\nPerspectivas: "},
        {"type": "text", "text": "Renovar a concessão.", "citations": [cita(1, 2, P25)]},
        {"type": "text", "text": "\nTom da administração: negativo\nJustificativa: "},
        {"type": "text", "text": "Momento desafiador.", "citations": [cita(0, 1, P3)]},
    ]
    a = ler_resposta(resposta(blocos), documento, rotas, contexto="")
    assert [r.texto for r in a.riscos] == ["Incerteza sobre a continuidade.", "Provisões altas: R$ 2.513 milhões."]
    assert a.riscos[1].numeros_sem_fonte == [] and a.riscos[1].evidencias[0].pagina == 3
    assert len(a.perspectivas) == 1 and a.tom == "negativo" and a.justificativa_tom.conferido


def test_guidance_tem_uma_definicao_so_e_ela_esta_no_sistema():
    """Guidance é projeção financeira ou operacional. Meta social e prazo de compensação de crédito são perspectiva."""
    assert DEFINICAO_GUIDANCE in SISTEMA and "{" not in SISTEMA
    for palavra in ("meta social", "compensar um crédito tributário", "perspectiva"):
        assert palavra in DEFINICAO_GUIDANCE
    assert "regra 5" in CAMPOS["guidance"] and "meta social" in CAMPOS["perspectiva"]


def test_pedido_leva_os_achados_ja_conhecidos_para_o_analista_nao_repetir(documento, rotas, numeros):
    numeros.alertas = [
        AlertaSaida(regra="V7", severidade="erro", origem="codigo", mensagem="sinal trocado", paginas=[9, 20]),
        AlertaSaida(regra="V16", severidade="aviso", origem="codigo", mensagem="ano repetido", paginas=[21]),
        AlertaSaida(regra="IA", severidade="aviso", origem="ia", mensagem="MWh no lugar de MWm", paginas=[8]),
    ]
    achados = achados_conhecidos(numeros)
    assert achados.splitlines() == ["- V16 (p. 21): ano repetido", "- Observação da extração (p. 8): MWh no lugar de MWm"]
    pedido = montar_conteudo(documento, rotas, numeros)[-1]["text"]
    assert achados in pedido and "Não repita esses achados" in pedido
    assert "sinal trocado" in pedido  # o erro continua no resumo de números
    assert "No máximo 10 linhas para risco e para evento" in pedido
    vazio_de_achados = numeros.model_copy(update={"alertas": []})
    assert achados_conhecidos(vazio_de_achados) == "- nenhum"
