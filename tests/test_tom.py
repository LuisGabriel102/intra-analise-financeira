"""Tom frase a frase: o léxico, o modelo clássico e a leitura dos rótulos da IA. Nenhum teste chama a IA."""

import json
from pathlib import Path

import pytest

from analise_financeira.llm import ClienteLLM, SemGravacao
from analise_financeira.pdf import Documento, Pagina, ler_pdf
from analise_financeira.roteamento import Rotas, rotear
from analise_financeira.tom import (
    contar_lexico,
    dividir_frases,
    frases_da_administracao,
    ler_rotulos,
    rotulo_lexico,
    tom_do_documento,
)
from falsos import SdkFalso

CABECALHO = "RELATÓRIO DA ADMINISTRAÇÃO – EMPRESA X S.A. - 2022"


def _documento(paginas: list[tuple[int, list[str]]]) -> Documento:
    return Documento(nome="X.pdf", paginas=[Pagina(numero=n, linhas=linhas) for n, linhas in paginas], escala_padrao="mil")


def test_frases_da_administracao_tira_tabela_titulo_e_cabecalho():
    doc = _documento([
        (1, [CABECALHO, "Mensagem da Administração",
             "A receita da companhia cresceu no ano e a margem ficou estável no período.",
             "Receita líquida | 13.253 | 14.897",
             "Desempenho Financeiro",
             "O resultado foi afetado por provisões relevantes e pela"]),
        (2, [CABECALHO, "inadimplência maior dos clientes do grupo ao longo do ano.",
             "A Companhia segue em busca de alternativas para a sua estrutura de capital."]),
        (3, [CABECALHO, "As perdas continuam altas e preocupam a administração da companhia neste ano.",
             "Índice das demonstrações e notas explicativas da companhia"]),
        (4, ["Balanço patrimonial", "Ativo | 1 | 2"]),
    ])
    rotas = Rotas(tipos={1: "relatorio_adm", 2: "relatorio_adm", 3: "relatorio_adm", 4: "balanco"})
    frases = frases_da_administracao(doc, rotas)
    assert [f.texto for f in frases] == [
        "A receita da companhia cresceu no ano e a margem ficou estável no período.",
        # a frase que vira a página volta inteira, com a página em que começa
        "O resultado foi afetado por provisões relevantes e pela inadimplência maior dos clientes do grupo ao longo do ano.",
        "A Companhia segue em busca de alternativas para a sua estrutura de capital.",
        "As perdas continuam altas e preocupam a administração da companhia neste ano.",
    ]  # sem cabeçalho, título, linha de tabela nem o pedaço de índice sem ponto final
    assert [f.pagina for f in frases] == [1, 1, 2, 3]
    assert [f.id for f in frases] == [1, 2, 3, 4]


def test_documento_sem_texto_da_administracao_nao_tem_frases():
    doc = _documento([(1, ["Notas explicativas", "A companhia tem sede em São Paulo e atua no setor de alimentos."])])
    assert frases_da_administracao(doc, Rotas(tipos={1: "notas"})) == []


def test_frases_reais_da_light():
    documento = ler_pdf(Path("dados/pdfs/Light.pdf"))
    frases = frases_da_administracao(documento, rotear(documento))
    assert 120 <= len(frases) <= 260
    assert all(" | " not in f.texto and f.texto.rstrip("”\"') ").endswith((".", "!", "?")) for f in frases)
    assert frases[0].pagina == 2 and frases[0].texto.startswith("Assumi, em agosto de 2022")


def test_dividir_frases_nao_corta_abreviacao():
    assert dividir_frases("A Light S.A. teve perdas no ano. O resultado caiu 10%. Em 2023 a meta é outra.") == [
        "A Light S.A. teve perdas no ano.", "O resultado caiu 10%.", "Em 2023 a meta é outra."]


def test_lexico():
    assert rotulo_lexico("As perdas aumentaram e a incerteza sobre a continuidade cresceu.") == "negativo"
    assert rotulo_lexico("A qualidade melhorou e houve ganhos de eficiência na operação.") == "positivo"
    assert rotulo_lexico("A empresa tem sede no Rio de Janeiro desde 1905.") == "neutro"
    positivas, negativas = contar_lexico("A SuperVia pediu recuperação judicial; a Companhia superou a meta.")
    assert positivas == ["superou"] and negativas == []  # SuperVia não é "superou", e recuperação fica de fora


def test_ler_rotulos():
    texto = "1: negativo\n2 - Positivo\n**3**: neutro\n4: talvez\nObservação: nada\n5. negativo"
    assert ler_rotulos(texto) == {1: "negativo", 2: "positivo", 3: "neutro", 5: "negativo"}


def test_tom_do_documento():
    assert tom_do_documento(["negativo"] * 3 + ["neutro"] * 7) == "negativo"   # saldo de 30%
    assert tom_do_documento(["negativo", "positivo"] + ["neutro"] * 8) == "neutro"
    assert tom_do_documento(["positivo"] * 2 + ["neutro"] * 8) == "positivo"   # saldo de -20%
    assert tom_do_documento(["negativo"] + ["neutro"] * 19) == "neutro"        # 5% não basta
    assert tom_do_documento([]) == ""


# ---- daqui em diante, precisa do scikit-learn (extra "ml", que o "dev" também instala)

def _corpus() -> tuple[list[str], list[str]]:
    textos, rotulos = [], []
    for i in range(20):
        textos += [f"Prejuízo e perdas pesaram no resultado da unidade {i}.",
                   f"Ganho de eficiência e recorde de vendas na unidade {i}.",
                   f"A unidade {i} fica na região sudeste e atende clientes."]
        rotulos += ["negativo", "positivo", "neutro"]
    return textos, rotulos


def test_modelo_classico_aprende_e_mostra_os_termos():
    pytest.importorskip("sklearn")
    from analise_financeira.tom import metricas, treinar_e_validar

    textos, rotulos = _corpus()
    v = treinar_e_validar(textos, rotulos)
    assert v["partes"] == 5 and len(v["previsto"]) == 60
    m = metricas(rotulos, v["previsto"])
    assert m["acerto"] >= 0.9 and m["kappa"] >= 0.85
    assert metricas(rotulos, v["piso"])["kappa"] == 0.0  # sempre a mesma classe: concordância de acaso
    assert any("perdas" in t or "prejuizo" in t for t in v["palavras"]["negativo"])


def test_poucas_frases_por_rotulo_nao_valida():
    pytest.importorskip("sklearn")
    from analise_financeira.tom import treinar_e_validar

    v = treinar_e_validar(["a b c", "d e f", "g h i"], ["negativo", "neutro", "neutro"])
    assert "previsto" not in v and "poucas frases" in v["motivo"]


def _documento_rotulavel() -> tuple[Documento, Rotas, str]:
    textos, rotulos = _corpus()
    doc = _documento([(1, textos[:30]), (2, textos[30:])])
    resposta = "\n".join(f"{i}: {r}" for i, r in enumerate(rotulos, start=1))
    return doc, Rotas(tipos={1: "relatorio_adm", 2: "relatorio_adm"}), resposta


def test_analisar_tom_com_ia_falsa_e_replay(tmp_path):
    pytest.importorskip("sklearn")
    from analise_financeira.tom import analisar_tom

    doc, rotas, resposta = _documento_rotulavel()
    sdk = SdkFalso([{"type": "text", "text": resposta}])
    cliente = ClienteLLM(sdk=sdk, pasta_gravacoes=tmp_path / "g", arquivo_traces=tmp_path / "t.jsonl")
    r = analisar_tom("X.pdf", doc, rotas, cliente, tom_analise="negativo")
    assert len(r.frases) == 60 and len(r.ia) == 60 and r.sem_rotulo == 0
    assert set(r.metricas) == {"lexico", "classico", "piso"}
    assert r.metricas["classico"]["acerto"] >= 0.9
    assert r.tom["ia"] == "neutro" and r.tom_analise == "negativo"
    assert "SISTEMA" not in sdk.ultimo_pedido["system"] and "ordem" in sdk.ultimo_pedido["system"]
    assert "temperature" not in sdk.ultimo_pedido
    # o mesmo pedido de novo vem da gravação: sem chave e sem custo
    replay = ClienteLLM(replay=True, pasta_gravacoes=tmp_path / "g", arquivo_traces=tmp_path / "t.jsonl")
    de_novo = analisar_tom("X.pdf", doc, rotas, replay, tom_analise="negativo")
    assert de_novo.uso.gravada and de_novo.metricas == r.metricas


def test_comparar_grava_o_relatorio(tmp_path):
    pytest.importorskip("sklearn")
    from analise_financeira.tom import comparar

    documento = ler_pdf(Path("dados/pdfs/Light.pdf"))
    frases = frases_da_administracao(documento, rotear(documento))
    resposta = "\n".join(f"{f.id}: {rotulo_lexico(f.texto)}" for f in frases)  # uma "IA" que pensa como o léxico
    cliente = ClienteLLM(sdk=SdkFalso([{"type": "text", "text": resposta}]),
                         pasta_gravacoes=tmp_path / "g", arquivo_traces=tmp_path / "t.jsonl")
    resultados, sem_texto, destino = comparar("dados/pdfs", cliente, tmp_path / "saidas")
    assert [r.documento for r in resultados] == ["Light.pdf"]
    assert sem_texto == ["Brasal.pdf", "Millet.pdf"]
    assert resultados[0].metricas["lexico"]["acerto"] == 1.0
    md = destino.read_text(encoding="utf-8")
    assert "## Light.pdf" in md and "Concorda com a IA" in md and "não se aplica" in md
    dados = json.loads((tmp_path / "saidas" / "tom.json").read_text(encoding="utf-8"))
    assert dados["documentos"][0]["uso"]["modelo"] == "claude-opus-5-5"
    assert dados["sem_texto_da_administracao"] == ["Brasal.pdf", "Millet.pdf"]


def test_replay_da_gravacao_real(tmp_path):
    """Com a gravação real da IA no repositório, o replay refaz a comparação sem chave."""
    pytest.importorskip("sklearn")
    from analise_financeira.tom import comparar

    cliente = ClienteLLM(replay=True, pasta_gravacoes=Path("gravacoes"), arquivo_traces=tmp_path / "t.jsonl")
    try:
        resultados, _, _ = comparar("dados/pdfs", cliente, tmp_path / "saidas")
    except SemGravacao:
        pytest.skip("ainda sem a gravação real do tom")
    light = resultados[0]
    assert light.uso.gravada and len(light.ia) >= 0.9 * len(light.frases)
    assert 0.0 <= light.metricas["lexico"]["acerto"] <= 1.0 and "classico" in light.metricas
