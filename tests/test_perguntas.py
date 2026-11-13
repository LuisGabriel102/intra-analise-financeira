"""O agente de perguntas: ferramentas, várias rodadas, citações, replay e limites.

O SDK é falso (SdkRoteiro): a primeira resposta pede ferramentas, a segunda responde
citando os resultados, no formato real da API (search_result_location).
"""

import pytest
from falsos import SdkRoteiro

from analise_financeira.busca import IndiceBM25, Trecho
from analise_financeira.esquemas import AnaliseQualitativa, Evidencia, Item, Uso
from analise_financeira.indicadores import AlertaSaida, Dado, DocumentoAnalisado, Indicador
from analise_financeira.llm import ClienteLLM, SemGravacao
from analise_financeira.perguntas import (
    Base,
    executor,
    ferramentas,
    ler_final,
    ler_fonte,
    responder,
    resultados_indicadores,
    resultados_qualitativos,
)


def vazio() -> Indicador:
    return Indicador(status="nao_encontrado")


@pytest.fixture
def base():
    ebitda = Indicador(status="encontrado", definicao="EBITDA CVM",
                       atual=Dado(texto="R$1.180 milhões", valor_reais=1.18e9, unidade="R$ milhões",
                                  fontes=[Evidencia(pagina=9, trecho="o EBITDA CVM foi de R$1.180 milhões")]),
                       calculado=Dado(texto="-R$ 1.179,6 milhões (calculado pela solução)", valor_reais=-1.1796e9,
                                      unidade="R$", fontes=[Evidencia(pagina=20, trecho="EBIT | (1.910.411)")]),
                       formula="EBIT + depreciação")
    numeros = DocumentoAnalisado(
        documento="Light.pdf", empresa="LIGHT S.A.", periodo_atual="2022", periodo_anterior="2021",
        receita_liquida=vazio(), ebitda=ebitda, margem_ebitda=vazio(), lucro_liquido=vazio(),
        lucro_controladores=vazio(), divida_liquida=vazio(), alavancagem=vazio(), fluxo_caixa_operacional=vazio(),
        capex=vazio(), alertas=[
            AlertaSaida(regra="V7", severidade="erro", origem="codigo", mensagem="sinal trocado", paginas=[9, 20],
                        campo="ebitda"),
            AlertaSaida(regra="V16", severidade="aviso", origem="codigo", mensagem="ano repetido", paginas=[21]),
            AlertaSaida(regra="V10", severidade="info", origem="codigo", mensagem="arredondamento", paginas=[10]),
        ])
    risco = Item(texto="Incerteza sobre a continuidade operacional.", conferido=True, fontes=["notas"],
                 evidencias=[Evidencia(pagina=25, trecho="Existe incerteza significativa")])
    qualitativa = AnaliseQualitativa(documento="Light.pdf", paginas_enviadas=[3, 25], tem_relatorio_administracao=True,
                                     riscos=[risco, Item(texto="Risco sem trecho.")], guidance_status="nao_encontrado",
                                     tom="negativo", uso=Uso(modelo="claude-opus-5-5"))
    indice = IndiceBM25([Trecho("Light.pdf", 26, "outros", ("Risco de liquidez", "A Companhia não possui linhas de crédito.")),
                         Trecho("Light.pdf", 9, "relatorio_adm", ("Desempenho", "O EBITDA CVM foi de R$1.180 milhões"))])
    return Base(documentos={"Light": "Light.pdf"}, numeros={"Light": numeros}, qualitativa={"Light": qualitativa},
                indice=indice)


def todos_os_resultados(conteudo: list[dict]) -> list[dict]:
    return [b for b in conteudo if b["type"] == "search_result"]


def test_ferramentas_tem_esquema_e_empresas(base):
    nomes = [f["name"] for f in ferramentas(base)]
    assert nomes == ["indicadores", "analise_qualitativa", "buscar_paginas"]
    empresa = ferramentas(base)[0]["input_schema"]["properties"]["empresa"]
    assert empresa["enum"] == ["Light", "todas"] and "LIGHT S.A." in empresa["description"]


def test_indicadores_viram_resultados_citaveis_com_alerta_e_pagina(base):
    resultados = resultados_indicadores(base, "Light")
    ebitda = next(r for r in resultados if r["title"] == "Light: EBITDA")
    textos = [b["text"] for b in ebitda["content"]]
    assert ler_fonte(ebitda["source"]) == ("Light.pdf", [9, 20])
    assert any("R$1.180 milhões (R$ milhões), ou R$ 1.180,0 milhões" in t for t in textos)
    assert any(t.startswith("Valor calculado pela solução para EBITDA") for t in textos)
    assert any("Alerta de validação V7 (erro)" in t for t in textos)
    outros = next(r for r in resultados if r["title"] == "Light: outros alertas de validação")
    assert [b["text"] for b in outros["content"]] == ["V16 (aviso, conferido em código): ano repetido"]  # info fica de fora
    # Regra da API: citações ligadas em todos os resultados, e nenhum bloco de texto vazio.
    assert all(r["citations"] == {"enabled": True} and all(b["text"].strip() for b in r["content"]) for r in resultados)


def test_qualitativa_marca_item_sem_trecho_e_guidance_nao_encontrado(base):
    riscos = resultados_qualitativos(base, "Light", "riscos")
    assert riscos[0]["source"] == "Light.pdf#p25"
    assert riscos[1]["source"] == "Light.pdf" and "não tem trecho citado" in riscos[1]["content"][-1]["text"]
    guidance = resultados_qualitativos(base, "Light", "guidance")
    assert guidance[0]["content"][0]["text"].startswith("Guidance: não encontrado")


def test_executor_valida_a_entrada(base):
    executar = executor(base)
    with pytest.raises(ValueError, match="empresa desconhecida"):
        executar("indicadores", {"empresa": "Petrobras"})
    with pytest.raises(ValueError, match="ferramenta desconhecida"):
        executar("apagar_tudo", {})
    achados = executar("buscar_paginas", {"consulta": "risco de liquidez", "empresa": "Light"})
    assert achados[0]["source"] == "Light.pdf#p26"
    assert executar("buscar_paginas", {"consulta": "dividendos"}) == [{"type": "text", "text": "Nada encontrado."}]


def cita(fonte: str, titulo: str, texto: str, indice: int, inicio: int = 0) -> dict:
    return {"type": "search_result_location", "source": fonte, "title": titulo, "cited_text": texto,
            "search_result_index": indice, "start_block_index": inicio, "end_block_index": inicio + 1}


PEDE = ([{"type": "text", "text": "Vou consultar os indicadores."},
         {"type": "tool_use", "id": "t1", "name": "indicadores", "input": {"empresa": "todas"}},
         {"type": "tool_use", "id": "t2", "name": "indicadores", "input": {"empresa": "Petrobras"}}], "tool_use")
RESPONDE = ([{"type": "text", "text": "Nenhuma empresa informa margem EBITDA. "},
             {"type": "text", "text": "A Light informa EBITDA de R$1.180 milhões",
              "citations": [cita("Light.pdf#p9,20", "Light: EBITDA", "Trecho do PDF, página 9: o EBITDA CVM foi de R$1.180 milhões", 1, 4)]},
             {"type": "text", "text": ", mas com o sinal trocado.\n",
              "citations": [cita("Light.pdf#p9,20", "Light: EBITDA", "Alerta de validação V7 (erro): sinal trocado", 1, 5)]}],
            "end_turn")


def test_agente_usa_ferramenta_cita_e_o_replay_refaz_a_conversa(tmp_path, base):
    sdk = SdkRoteiro([PEDE, RESPONDE])
    cliente = ClienteLLM(sdk=sdk, pasta_gravacoes=tmp_path / "g", arquivo_traces=tmp_path / "t.jsonl")
    r = responder("Qual empresa teve a maior margem EBITDA?", base, cliente, numero=1)

    assert sdk.chamadas == 2 and r.rodadas == 2 and r.completa
    assert r.texto == ("Nenhuma empresa informa margem EBITDA. A Light informa EBITDA de R$1.180 milhões[1], "
                       "mas com o sinal trocado.[2]")
    assert [(f.documento, f.paginas) for f in r.fontes] == [("Light.pdf", [9, 20]), ("Light.pdf", [9, 20])]
    assert r.ferramentas == ["indicadores(todas)", "indicadores(Petrobras)"]

    segundo = sdk.pedidos[1]
    assert "temperature" not in segundo and segundo["extra_body"] == {"cache_control": {"type": "ephemeral"}}
    assistente, resultados = segundo["messages"][1], segundo["messages"][2]
    assert assistente["content"][0] == {"type": "thinking", "thinking": "pensando", "signature": "assinatura-1"}
    assert [b["type"] for b in assistente["content"]] == ["thinking", "text", "tool_use", "tool_use"]
    ok, erro = resultados["content"]
    assert ok["tool_use_id"] == "t1" and todos_os_resultados(ok["content"])
    assert erro["is_error"] is True and "empresa desconhecida" in erro["content"]

    replay = ClienteLLM(replay=True, pasta_gravacoes=tmp_path / "g", arquivo_traces=tmp_path / "t.jsonl")
    de_novo = responder("Qual empresa teve a maior margem EBITDA?", base, replay, numero=1)
    assert de_novo.texto == r.texto and de_novo.uso.gravada and sdk.chamadas == 2
    with pytest.raises(SemGravacao):
        responder("Outra pergunta?", base, replay)


def test_agente_para_no_limite_de_rodadas(tmp_path, base):
    sdk = SdkRoteiro([PEDE] * 3)
    cliente = ClienteLLM(sdk=sdk, pasta_gravacoes=tmp_path / "g", arquivo_traces=tmp_path / "t.jsonl")
    conversa = cliente.conversar("?", sistema="s", ferramentas=ferramentas(base), executar=executor(base),
                                 etapa="pergunta", documento="teste", max_rodadas=3)
    assert sdk.chamadas == 3 and conversa.completa is False


def test_ler_final_junta_fontes_repetidas():
    c = cita("Millet.pdf#p42", "Millet: Dívida líquida", "Dívida líquida, valor informado: 13.520", 0)
    texto, fontes = ler_final([{"type": "text", "text": "A dívida é de 13.520", "citations": [c]},
                               {"type": "text", "text": " e foi citada de novo", "citations": [c]},
                               {"type": "tool_use", "id": "x", "name": "y", "input": {}}])
    assert texto == "A dívida é de 13.520[1] e foi citada de novo[1]" and len(fontes) == 1
    assert fontes[0].paginas == [42] and not fontes[0].calculado


class SdkSemCacheAutomatico(SdkRoteiro):
    """Simula uma plataforma que recusa o cache_control no topo do pedido."""

    def stream(self, **pedido):
        if "extra_body" in pedido:
            raise RuntimeError("400 invalid_request_error: cache_control: Extra inputs are not permitted")
        return super().stream(**pedido)


def test_sem_cache_automatico_a_conversa_segue(tmp_path, base):
    sdk = SdkSemCacheAutomatico([RESPONDE])
    cliente = ClienteLLM(sdk=sdk, pasta_gravacoes=tmp_path / "g", arquivo_traces=tmp_path / "t.jsonl")
    r = responder("Pergunta?", base, cliente)
    assert r.completa and r.fontes and "extra_body" not in sdk.pedidos[0]


def test_erro_numa_pergunta_nao_derruba_as_outras(tmp_path, base):
    from analise_financeira.perguntas import responder_obrigatorias

    class SdkQueFalha(SdkRoteiro):
        def stream(self, **pedido):
            if "maior margem" in pedido["messages"][0]["content"][0]["text"]:
                raise ConnectionError("rede caiu")
            return super().stream(**pedido)

    sdk = SdkQueFalha([RESPONDE] * 4)
    cliente = ClienteLLM(sdk=sdk, pasta_gravacoes=tmp_path / "g", arquivo_traces=tmp_path / "t.jsonl")
    respostas = responder_obrigatorias(base, cliente, paralelo=1)
    assert len(respostas) == 5 and respostas[0].texto.startswith("Erro ao responder: ConnectionError")
    assert not respostas[0].completa and all(r.completa for r in respostas[1:])
