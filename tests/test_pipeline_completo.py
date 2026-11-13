"""O comando `analisar` inteiro: extração gravada + analista e agente com um SDK falso.

A extração vem das respostas reais gravadas. A análise e as perguntas vêm de um SDK
falso que responde no formato da API, citando linhas e resultados que o próprio
pedido trouxe. Confere o encadeamento, os arquivos gravados, o relatório e o replay.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from falsos import fluxo

from analise_financeira.llm import ClienteLLM
from analise_financeira.orquestrador import carregar_base, processar
from analise_financeira.perguntas import PERGUNTAS, responder
from analise_financeira.relatorio import montar_relatorio
from analise_financeira.roteamento import LIMITE_ANALISE

pytestmark = pytest.mark.skipif(not any(Path("gravacoes").glob("extracao_*.json")), reason="sem respostas gravadas")


class SdkEsperto:
    """Analista: cita a primeira e a última página enviadas. Agente: pede 3 ferramentas e cita o primeiro resultado."""

    def __init__(self):
        self.pedidos: list[dict] = []
        self.messages = self

    def stream(self, **pedido):
        self.pedidos.append(pedido)
        return self._agente(pedido) if "tools" in pedido else self._analista(pedido)

    @staticmethod
    def _cita(documentos, i):
        linha = documentos[i]["source"]["content"][0]["text"]
        return {"type": "content_block_location", "document_index": i, "start_block_index": 0, "end_block_index": 1,
                "cited_text": linha}

    def _analista(self, pedido):
        docs = [c for c in pedido["messages"][0]["content"] if c["type"] == "document"]
        ultimo = len(docs) - 1
        return fluxo([
            {"type": "text", "text": "motivo: "},
            {"type": "text", "text": "A receita mudou pelo motivo descrito.", "citations": [self._cita(docs, 0)]},
            {"type": "text", "text": "\nrisco: "},
            {"type": "text", "text": "Um risco <script>alert(1)</script> citado | com barra.", "citations": [self._cita(docs, ultimo)]},
            {"type": "text", "text": "\nguidance: não encontrado\ntom: neutro\njustificativa_tom: "},
            {"type": "text", "text": "O texto é técnico.", "citations": [self._cita(docs, 0)]},
        ])

    def _agente(self, pedido):
        mensagens = pedido["messages"]
        if len(mensagens) == 1:
            return fluxo([
                {"type": "tool_use", "id": "a", "name": "indicadores", "input": {"empresa": "todas"}},
                {"type": "tool_use", "id": "b", "name": "analise_qualitativa", "input": {"empresa": "todas", "secao": "tudo"}},
                {"type": "tool_use", "id": "c", "name": "buscar_paginas", "input": {"consulta": "risco de liquidez"}},
            ], "tool_use")
        primeiro = mensagens[-1]["content"][0]["content"][1]   # o resultado da EBITDA... da primeira empresa
        cita = {"type": "search_result_location", "source": primeiro["source"], "title": primeiro["title"],
                "cited_text": primeiro["content"][0]["text"], "search_result_index": 1,
                "start_block_index": 0, "end_block_index": 1}
        return fluxo([{"type": "text", "text": "Resposta curta."},
                      {"type": "text", "text": " Fato citado.", "citations": [cita]}])


@pytest.fixture(scope="module")
def rodada(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("completo")
    gravacoes = pasta / "gravacoes"
    gravacoes.mkdir()
    for arquivo in Path("gravacoes").glob("extracao_*.json"):
        shutil.copy(arquivo, gravacoes)
    sdk = SdkEsperto()
    cliente = ClienteLLM(sdk=sdk, pasta_gravacoes=gravacoes, arquivo_traces=pasta / "traces.jsonl")
    execucao = processar("dados/pdfs", cliente, pasta_saidas=pasta / "saidas")
    return pasta, sdk, execucao


def test_encadeia_tudo_e_grava_os_arquivos(rodada):
    pasta, sdk, execucao = rodada
    analises = [p for p in sdk.pedidos if "tools" not in p]
    assert len(analises) == 3                                  # a extração veio das gravações
    assert len(sdk.pedidos) == 3 + 2 * len(PERGUNTAS)          # 2 rodadas por pergunta
    for nome in ("Brasal", "Light", "Millet"):
        for arquivo in ("rotas.json", "extracao.json", "indicadores.json", "analise.json"):
            assert (pasta / "saidas" / nome / arquivo).exists()
    assert len(json.loads((pasta / "saidas/perguntas.json").read_text(encoding="utf-8"))) == 5
    assert all(r.qualitativa.tom == "neutro" and r.qualitativa.guidance_status == "nao_encontrado"
               for r in execucao.resultados)


def test_analista_recebe_so_paginas_de_texto_dentro_do_orcamento(rodada):
    _, sdk, execucao = rodada
    for pedido in (p for p in sdk.pedidos if "tools" not in p):
        docs = [c for c in pedido["messages"][0]["content"] if c["type"] == "document"]
        caracteres = sum(len(b["text"]) for d in docs for b in d["source"]["content"])
        assert caracteres <= LIMITE_ANALISE
        assert all(b["text"].strip() for d in docs for b in d["source"]["content"])  # a API recusa bloco vazio
        assert not any("Tipo da página: dre" in d["context"] for d in docs)


def test_ferramentas_devolvem_resultados_validos_para_a_api(rodada):
    _, sdk, _ = rodada
    segunda = next(p for p in sdk.pedidos if "tools" in p and len(p["messages"]) == 3)
    resultados = segunda["messages"][2]["content"]
    assert [r["tool_use_id"] for r in resultados] == ["a", "b", "c"]
    blocos = [b for r in resultados for b in r["content"] if b["type"] == "search_result"]
    assert len(blocos) > 30
    assert all(b["citations"] == {"enabled": True} for b in blocos)            # tudo ou nada, regra da API
    assert all(c["text"].strip() for b in blocos for c in b["content"])        # nenhum texto vazio
    json.dumps(segunda)                                                        # tudo serializável


def test_respostas_tem_fonte_e_o_relatorio_tem_tudo(rodada):
    pasta, _, execucao = rodada
    assert all(r.completa and r.rodadas == 2 and r.fontes for r in execucao.respostas)
    md = (pasta / "saidas/relatorio.md").read_text(encoding="utf-8")
    for secao in ("## 1. Resumo executivo", "## 2. Tabela comparativa", "## 3. Análise qualitativa", "## 4. Perguntas",
                  "## 5. Alertas", "## 6. Glossário"):
        assert secao in md
    assert all(p in md for p in PERGUNTAS)
    assert "<script>" not in md and "&lt;script&gt;" in md                     # texto do PDF/IA não vira HTML
    linha_ebitda = next(linha for linha in md.splitlines() if linha.startswith("| EBITDA informado"))
    assert "⚠️" in linha_ebitda and "⛔" in linha_ebitda                       # Light com alerta; Brasal não informa
    assert all(linha.count("|") == 5 for linha in md.splitlines() if linha.startswith("| Receita líquida"))


def test_replay_refaz_tudo_sem_chamar_a_api(rodada):
    pasta, sdk, execucao = rodada
    chamadas = len(sdk.pedidos)
    replay = ClienteLLM(replay=True, pasta_gravacoes=pasta / "gravacoes", arquivo_traces=pasta / "traces.jsonl")
    de_novo = processar("dados/pdfs", replay, pasta_saidas=pasta / "saidas_replay")
    assert len(sdk.pedidos) == chamadas
    assert [r.texto for r in de_novo.respostas] == [r.texto for r in execucao.respostas]
    agora = datetime(2026, 11, 13, 12, 0)
    assert montar_relatorio(de_novo.resultados, de_novo.respostas, gerado_em=agora).split("Custo")[1] \
        .split("\n", 1)[1] == montar_relatorio(execucao.resultados, execucao.respostas, gerado_em=agora) \
        .split("Custo")[1].split("\n", 1)[1]


def test_pergunta_livre_usa_o_que_foi_gravado(rodada):
    pasta, _, _ = rodada
    sdk = SdkEsperto()
    cliente = ClienteLLM(sdk=sdk, pasta_gravacoes=pasta / "gravacoes", arquivo_traces=pasta / "traces.jsonl")
    resposta = responder("Qual empresa tem mais caixa?", carregar_base("dados/pdfs", pasta / "saidas"), cliente)
    assert resposta.fontes and len(sdk.pedidos) == 2
