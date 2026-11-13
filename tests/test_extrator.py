"""O extrator monta o pedido com citações, lê a resposta e confere cada número no trecho citado.

A resposta da IA aqui é falsa, mas no formato real da API (o mesmo do teste de 13/11).
"""

import json

import pytest
from falsos import SdkFalso

from analise_financeira.extrator import CAMPOS, extrair, ler_resposta, montar_conteudo, montar_linhas
from analise_financeira.llm import ClienteLLM, Resposta, SemGravacao
from analise_financeira.pdf import Documento, Pagina
from analise_financeira.roteamento import Rotas

# Duas páginas de mentira: a 9 é texto da administração; a 20, a DRE.
P9 = ["Desempenho Financeiro", "Em 2022, o EBITDA CVM foi de R$1.180 milhões, apresentando uma redução R$3.001",
      "Em 2022, a Light S.A. apurou um resultado líquido de -R$5.673 milhões, R$6.070 milhões"]
P20 = ["DEMONSTRAÇÕES DE RESULTADOS", "(Em milhares de reais)",
       "RECEITA LÍQUIDA | 31 | - | - | 13.253.286 | 14.897.920",
       "LUCRO (PREJUÍZO) LÍQUIDO DO EXERCÍCIO | (5.672.203) | 397.945 | (5.672.203) | 397.945"]


@pytest.fixture
def documento():
    paginas = [Pagina(numero=n, linhas=[]) for n in range(1, 21)]
    paginas[8] = Pagina(numero=9, linhas=P9)
    paginas[19] = Pagina(numero=20, linhas=P20, escala="mil")
    return Documento(nome="Light.pdf", paginas=paginas)


@pytest.fixture
def rotas():
    return Rotas(tipos={9: "relatorio_adm", 20: "dre"}, extracao=[9, 20])


def cita(indice_doc: int, inicio: int, linhas: list[str]) -> dict:
    return {"type": "content_block_location", "document_index": indice_doc, "start_block_index": inicio,
            "end_block_index": inicio + 1, "cited_text": linhas[inicio]}


def resposta(blocos: list[dict]) -> Resposta:
    return Resposta(blocos=blocos, modelo="claude-opus-5-5", tokens_entrada=1000, tokens_saida=200)


BLOCOS = [
    {"type": "text", "text": "receita_liquida_atual: "},
    {"type": "text", "text": "13.253.286", "citations": [cita(1, 2, P20)]},
    {"type": "text", "text": "\nebitda_atual: "},
    {"type": "text", "text": "R$1.180 milhões", "citations": [cita(0, 1, P9)]},
    {"type": "text", "text": "\nlucro_liquido_atual: "},
    {"type": "text", "text": "-R$5.673 milhões", "citations": [cita(0, 2, P9)]},
    {"type": "text", "text": "\nlucro_liquido_atual: "},
    {"type": "text", "text": "(5.672.203)", "citations": [cita(1, 3, P20)]},
    {"type": "text", "text": "\nmargem_ebitda_atual: não encontrado\nobservacao: "},
    {"type": "text", "text": "o EBITDA não bate com o resultado", "citations": [cita(0, 1, P9)]},
]


def test_pedido_tem_uma_pagina_por_documento_e_uma_linha_por_bloco(documento, rotas):
    conteudo = montar_conteudo(documento, [9, 20], rotas)
    assert [c["title"] for c in conteudo[:2]] == ["Light.pdf, página 9", "Light.pdf, página 20"]
    assert [b["text"] for b in conteudo[1]["source"]["content"]] == P20
    assert all(c["citations"] == {"enabled": True} for c in conteudo[:2])
    assert all(nome in conteudo[-1]["text"] for nome in CAMPOS)


def test_montar_linhas_liga_a_citacao_a_linha_certa():
    linhas = montar_linhas(BLOCOS)
    assert linhas[0][0] == "receita_liquida_atual: 13.253.286"
    assert linhas[0][1][0]["start_block_index"] == 2


def test_le_valor_pagina_trecho_e_unidade(documento, rotas):
    ext = ler_resposta(resposta(BLOCOS), documento, [9, 20], rotas)
    receita = ext.campos["receita_liquida_atual"]
    assert receita.status == "encontrado"
    assert receita.principal.numero == 13_253_286 and receita.principal.unidade == "R$ mil"
    assert receita.principal.evidencias[0].pagina == 20
    assert receita.principal.evidencias[0].trecho == P20[2]
    assert receita.principal.valor_reais == 13_253_286_000


def test_ebitda_do_relatorio_fica_com_o_texto_e_o_sinal_do_documento(documento, rotas):
    ebitda = ler_resposta(resposta(BLOCOS), documento, [9, 20], rotas).campos["ebitda_atual"]
    assert ebitda.principal.numero == 1180 and ebitda.principal.unidade == "R$ milhões"
    assert ebitda.principal.fonte == "relatorio_adm"


def test_duas_ocorrencias_e_a_da_demonstracao_vai_para_a_tabela(documento, rotas):
    lucro = ler_resposta(resposta(BLOCOS), documento, [9, 20], rotas).campos["lucro_liquido_atual"]
    assert len(lucro.ocorrencias) == 2
    assert lucro.principal.fonte == "dre" and lucro.principal.numero == -5_672_203


def test_nao_encontrado_e_campo_sem_resposta(documento, rotas):
    campos = ler_resposta(resposta(BLOCOS), documento, [9, 20], rotas).campos
    assert campos["margem_ebitda_atual"].status == "nao_encontrado"
    assert campos["fco_atual"].status == "sem_resposta"


def test_observacao_da_ia_vem_com_citacao(documento, rotas):
    ext = ler_resposta(resposta(BLOCOS), documento, [9, 20], rotas)
    assert ext.observacoes[0].evidencias[0].pagina == 9


def test_numero_fora_do_trecho_nao_e_conferido(documento, rotas):
    # A IA "copiou" 13.235.286 (dígitos trocados), mas o trecho citado diz 13.253.286.
    blocos = [{"type": "text", "text": "receita_liquida_atual: "},
              {"type": "text", "text": "13.235.286", "citations": [cita(1, 2, P20)]}]
    campo = ler_resposta(resposta(blocos), documento, [9, 20], rotas).campos["receita_liquida_atual"]
    assert campo.status == "sem_evidencia" and not campo.principal.conferido


def test_numero_sem_o_sinal_nao_e_conferido(documento, rotas):
    blocos = [{"type": "text", "text": "lucro_liquido_atual: "},
              {"type": "text", "text": "5.672.203", "citations": [cita(1, 3, P20)]}]
    assert ler_resposta(resposta(blocos), documento, [9, 20], rotas).campos["lucro_liquido_atual"].status == "sem_evidencia"


def test_valor_sem_citacao_nao_e_conferido(documento, rotas):
    blocos = [{"type": "text", "text": "receita_liquida_atual: 13.253.286"}]
    assert ler_resposta(resposta(blocos), documento, [9, 20], rotas).campos["receita_liquida_atual"].status == "sem_evidencia"


def test_citacao_que_nao_bate_com_a_linha_e_descartada(documento, rotas):
    errada = cita(1, 2, P20) | {"cited_text": "outro texto qualquer"}
    blocos = [{"type": "text", "text": "receita_liquida_atual: "}, {"type": "text", "text": "13.253.286", "citations": [errada]}]
    campo = ler_resposta(resposta(blocos), documento, [9, 20], rotas).campos["receita_liquida_atual"]
    assert campo.principal.evidencias == [] and campo.status == "sem_evidencia"


# ------------------------------------------------------------ cliente: gravação, replay e custo


def test_grava_a_resposta_e_nao_paga_duas_vezes(tmp_path, documento, rotas):
    sdk = SdkFalso(BLOCOS)
    cliente = ClienteLLM(sdk=sdk, pasta_gravacoes=tmp_path / "g", arquivo_traces=tmp_path / "t.jsonl")
    primeira = extrair(documento, rotas, cliente)
    segunda = extrair(documento, rotas, cliente)
    assert sdk.chamadas == 1
    assert not primeira.uso.gravada and segunda.uso.gravada
    assert primeira.campos == segunda.campos
    assert len(list((tmp_path / "g").glob("extracao_Light_*.json"))) == 1


def test_pedido_vai_sem_temperature_e_com_effort(tmp_path, documento, rotas):
    sdk = SdkFalso(BLOCOS)
    extrair(documento, rotas, ClienteLLM(sdk=sdk, pasta_gravacoes=tmp_path, arquivo_traces=tmp_path / "t.jsonl"))
    assert "temperature" not in sdk.ultimo_pedido
    assert sdk.ultimo_pedido["output_config"] == {"effort": "high"}


def test_replay_sem_gravacao_avisa(tmp_path, documento, rotas):
    cliente = ClienteLLM(replay=True, pasta_gravacoes=tmp_path, arquivo_traces=tmp_path / "t.jsonl")
    with pytest.raises(SemGravacao):
        extrair(documento, rotas, cliente)


def test_trace_registra_modelo_tokens_e_custo(tmp_path, documento, rotas):
    traces = tmp_path / "t.jsonl"
    extrair(documento, rotas, ClienteLLM(sdk=SdkFalso(BLOCOS), pasta_gravacoes=tmp_path, arquivo_traces=traces))
    linha = json.loads(traces.read_text(encoding="utf-8").splitlines()[0])
    assert linha["gen_ai.request.model"] == "claude-opus-5-5"
    assert linha["gen_ai.usage.input_tokens"] == 1000
    assert linha["custo_usd"] == pytest.approx((1000 * 4 + 200 * 20) / 1e6)


def test_sem_chave_avisa_antes_de_chamar(tmp_path, documento, rotas):
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        extrair(documento, rotas, ClienteLLM(pasta_gravacoes=tmp_path, arquivo_traces=tmp_path / "t.jsonl"))


def test_pagina_sem_aviso_de_escala_usa_a_do_documento(rotas):
    # Erro achado na primeira rodada real: a p. 105 da Light não repete a escala no topo,
    # e a dívida líquida saía em reais, e não em milhares (R$ 9 milhões em vez de R$ 9 bilhões).
    p105 = ["Dívida líquida (A) | 9.032.236 | 7.352.919"]
    paginas = [Pagina(numero=n, linhas=[]) for n in range(1, 21)]
    paginas[19] = Pagina(numero=20, linhas=p105)  # sem escala na página
    documento = Documento(nome="Light.pdf", paginas=paginas, escala_padrao="mil")
    blocos = [{"type": "text", "text": "divida_liquida_atual: "},
              {"type": "text", "text": "9.032.236", "citations": [cita(1, 0, p105)]}]
    campo = ler_resposta(resposta(blocos), documento, [9, 20], rotas).campos["divida_liquida_atual"]
    assert campo.principal.unidade == "R$ mil"
    assert campo.principal.valor_reais == 9_032_236_000


def test_replay_registra_custo_zero_e_guarda_o_original(tmp_path, documento, rotas):
    traces = tmp_path / "t.jsonl"
    cliente = ClienteLLM(sdk=SdkFalso(BLOCOS), pasta_gravacoes=tmp_path / "g", arquivo_traces=traces)
    extrair(documento, rotas, cliente)
    extrair(documento, rotas, ClienteLLM(replay=True, pasta_gravacoes=tmp_path / "g", arquivo_traces=traces))
    nova, gravada = (json.loads(linha) for linha in traces.read_text(encoding="utf-8").splitlines())
    assert nova["custo_usd"] > 0 and not nova["gravada"]
    assert gravada["custo_usd"] == 0 and gravada["custo_original_usd"] == nova["custo_usd"]


# ------------------------------------------------------------------ citação vazia: o código acha o trecho literal


def _doc_com_paginas(*paginas: list[str]):
    from analise_financeira.pdf import Documento, Pagina

    return Documento(nome="X.pdf", paginas=[Pagina(numero=i, linhas=linhas) for i, linhas in enumerate(paginas, 1)])


def test_localizar_trecho_acha_a_frase_literal_sem_contar_espacos_nem_aspas():
    from analise_financeira.extrator import localizar_trecho

    doc = _doc_com_paginas(["Cabeçalho", "A administração reclassificou de", "“Investimentos” para “Ativo mantido",
                            "para venda”, com perda de R$94.453.", "Rodapé"])
    achado = localizar_trecho('reclassificou de "Investimentos" para "Ativo mantido para venda"', doc, [1])
    assert [(e.pagina, e.origem) for e in achado] == [(1, "codigo")]
    assert achado[0].trecho.splitlines() == doc.pagina(1).linhas[1:4]
    assert localizar_trecho("curto demais", doc, [1]) == []
    assert localizar_trecho("um texto que não está em página nenhuma do documento", doc, [1]) == []


def test_localizar_trecho_acha_a_frase_que_vira_a_pagina_pulando_rodape_e_cabecalho():
    from analise_financeira.extrator import localizar_trecho

    doc = _doc_com_paginas(["Essa retração foi devida a provisões de -", "R$2.513 milhões, em especial ao reconhecimento", "9"],
                           ["RELATÓRIO DA ADMINISTRAÇÃO – 2022", "de provisão para devolução de PIS/COFINS.", "Outra linha"])
    achado = localizar_trecho("Essa retração foi devida a provisões de -R$2.513 milhões, em especial ao reconhecimento "
                              "de provisão para devolução de PIS/COFINS", doc, [1, 2])
    assert [(e.pagina, e.trecho) for e in achado] == [
        (1, "Essa retração foi devida a provisões de -\nR$2.513 milhões, em especial ao reconhecimento"),
        (2, "de provisão para devolução de PIS/COFINS.")]


def test_bloco_com_citacao_vazia_vira_busca_literal_e_bloco_sem_citacao_nao():
    from analise_financeira.extrator import montar_linhas, recortar_evidencias

    doc = _doc_com_paginas(["A Companhia não possui linhas de crédito contratadas e disponíveis."])
    blocos = [{"type": "text", "text": "risco: A liquidez é limitada. ", "citations": None},
              {"type": "text", "text": "A Companhia não possui linhas de crédito contratadas", "citations": []},
              {"type": "text", "text": "\nrisco: Sem citação nenhuma, e um texto longo o bastante.", "citations": None}]
    (primeira, cits1), (segunda, cits2) = montar_linhas(blocos)
    assert [e.origem for e in recortar_evidencias(cits1, doc, [1])] == ["codigo"]
    assert cits2 == []  # o texto do próprio modelo, sem moldura de citação, não vira busca
