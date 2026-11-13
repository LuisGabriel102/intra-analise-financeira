"""Ponta a ponta com as respostas reais da IA, gravadas em gravacoes/: nada é chamado.

O comando `analisar --replay` tem que refazer, igualzinho, o relatório que está em saidas/.
Isso prova duas coisas para quem avalia: o resultado do repositório saiu deste código,
e qualquer um roda a solução inteira sem chave e sem custo.

Se o código mudar o pedido de alguma etapa, a gravação daquele pedido deixa de existir.
Aí o teste pula, avisando que é preciso rodar `analisar` com a chave para gravar de novo.
"""

from pathlib import Path

import pytest

from analise_financeira.llm import ClienteLLM, SemGravacao
from analise_financeira.orquestrador import processar

RAIZ = Path(__file__).resolve().parents[1]


def _corpo(relatorio: str) -> str:
    """Do resumo executivo em diante: o cabeçalho tem data, hora, tempo e custo desta execução."""
    return relatorio[relatorio.index("## 1. Resumo executivo"):]


def test_replay_das_gravacoes_reais_refaz_o_relatorio_do_repositorio(tmp_path):
    commitado = RAIZ / "saidas" / "relatorio.md"
    if not commitado.exists():
        pytest.skip("Ainda não há saidas/relatorio.md. Rode `analisar` uma vez.")
    cliente = ClienteLLM(replay=True, pasta_gravacoes=RAIZ / "gravacoes", arquivo_traces=tmp_path / "traces.jsonl")
    try:
        execucao = processar(RAIZ / "dados" / "pdfs", cliente, pasta_saidas=tmp_path / "saidas")
    except SemGravacao as erro:
        pytest.skip(f"As gravações não valem para os pedidos atuais ({erro}). Rode `analisar` com a chave.")

    gerado = (tmp_path / "saidas" / "relatorio.md").read_text(encoding="utf-8")
    assert _corpo(gerado) == _corpo(commitado.read_text(encoding="utf-8"))

    # O que tem que valer em qualquer rodada real, e não só nesta:
    assert len(execucao.resultados) == 3 and len(execucao.respostas) == 5
    assert all(r.qualitativa is not None and r.qualitativa.completa for r in execucao.resultados)
    for resposta in execucao.respostas:
        assert resposta.completa and resposta.fontes, f"pergunta {resposta.numero} sem fonte ou incompleta"
        assert not resposta.texto.startswith("Erro ao responder")
        assert resposta.uso.gravada
