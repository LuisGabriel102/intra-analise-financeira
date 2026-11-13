"""Ponta a ponta com as respostas reais da IA, gravadas em gravacoes/ (rodada de 13/11/2026).

Roda o pipeline inteiro em modo replay, sem chamar a API, e confere o resultado:
a extração contra o gabarito e os alertas que precisam aparecer.
"""

import shutil
from pathlib import Path

import pytest

from analise_financeira.avaliacao import avaliar
from analise_financeira.llm import ClienteLLM
from analise_financeira.orquestrador import processar_extracao

pytestmark = pytest.mark.skipif(not any(Path("gravacoes").glob("extracao_*.json")), reason="sem respostas gravadas")


@pytest.fixture(scope="module")
def rodada(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("rodada")
    shutil.copytree("gravacoes", pasta / "gravacoes")
    cliente = ClienteLLM(replay=True, pasta_gravacoes=pasta / "gravacoes", arquivo_traces=pasta / "saidas/traces.jsonl")
    resultados = processar_extracao("dados/pdfs", cliente, pasta_saidas=pasta / "saidas")
    return pasta, resultados


def _regras(resultados, doc):
    _, analise = resultados[doc]
    return {(a.regra, a.severidade) for a in analise.alertas if a.origem == "codigo"}


def test_replay_nao_gasta_nada(rodada):
    _, resultados = rodada
    assert all(extracao.uso.gravada for extracao, _ in resultados.values())


def test_extracao_bate_com_o_gabarito(rodada):
    pasta, _ = rodada
    md = avaliar(pasta / "saidas", pasta_resultados=pasta / "resultados")
    assert "**50/50 (100%)**" in md and "Nenhum." in md


def test_light_ebitda_com_sinal_trocado_e_ano_errado(rodada):
    _, resultados = rodada
    regras = _regras(resultados, "Light.pdf")
    assert ("V7", "erro") in regras    # L1
    assert ("V11", "aviso") in regras  # L3
    assert ("V10", "info") in regras   # L5
    assert ("V16", "aviso") in regras  # L6 e L9


def test_light_ebitda_calculado_e_margem_negativa(rodada):
    _, analise = rodada[1]["Light.pdf"]
    assert analise.ebitda.atual.valor_reais == 1_180_000_000          # o que o relatório diz, sem corrigir
    assert analise.ebitda.calculado.valor_reais == -1_179_644_000     # o que as demonstrações dizem
    assert analise.margem_ebitda.calculado.numero == pytest.approx(-0.089, abs=0.0005)
    assert analise.alavancagem.atual.numero == 3.32 and analise.alavancagem.calculado is None


def test_millet_lucro_e_patrimonio_que_nao_batem(rodada):
    _, resultados = rodada
    regras = _regras(resultados, "Millet.pdf")
    assert ("V13", "erro") in regras    # M1 e M2
    assert ("V15", "aviso") in regras   # M5


def test_brasal_sem_ebitda_e_com_2021_nao_auditado(rodada):
    _, analise = rodada[1]["Brasal.pdf"]
    assert analise.ebitda.status == "nao_encontrado"
    assert analise.margem_ebitda.calculado.numero == pytest.approx(0.167, abs=0.0005)
    assert analise.divida_liquida.status == "nao_encontrado"
    assert analise.divida_liquida.calculado.valor_reais == -171_605_000  # caixa líquido
    assert ("V14", "aviso") in _regras(rodada[1], "Brasal.pdf")          # B1
