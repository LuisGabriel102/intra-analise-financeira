"""O servidor MCP, usado como um agente o usaria: pelo protocolo, sem chamar a IA.

Os dados são os do repositório (saidas/ e dados/pdfs/). Os testes usam fatos da extração e da
conferência em código, que não mudam quando a análise qualitativa roda de novo; da análise
qualitativa, só conferem o formato.
"""

import sys
from pathlib import Path

import anyio
import pytest

pytest.importorskip("mcp")

from mcp import Client, StdioServerParameters  # noqa: E402

from analise_financeira.orquestrador import carregar_base  # noqa: E402
from analise_financeira.servidor_mcp import AVISO_PDF, criar_servidor  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
FERRAMENTAS = ["listar_empresas", "obter_indicadores", "listar_alertas", "obter_analise_qualitativa",
               "buscar_paginas", "ler_pagina"]


@pytest.fixture(scope="module")
def servidor():
    base = carregar_base(RAIZ / "dados" / "pdfs", RAIZ / "saidas")
    return criar_servidor(base, RAIZ / "saidas" / "relatorio.md")


def chamar(servidor, ferramenta: str, argumentos: dict | None = None):
    async def conversa():
        async with Client(servidor) as cliente:
            return await cliente.call_tool(ferramenta, argumentos or {})

    return anyio.run(conversa)


def resultado(servidor, ferramenta: str, argumentos: dict | None = None):
    r = chamar(servidor, ferramenta, argumentos)
    assert not r.is_error, r.content[0].text
    dados = r.structured_content
    return dados["result"] if set(dados) == {"result"} else dados


def test_ferramentas_so_leem_e_as_empresas_sao_uma_lista_fechada(servidor):
    async def listar():
        async with Client(servidor) as cliente:
            return (await cliente.list_tools()).tools, cliente.instructions

    ferramentas, instrucoes = anyio.run(listar)
    assert [f.name for f in ferramentas] == FERRAMENTAS
    assert all(f.annotations.read_only_hint and not f.annotations.open_world_hint for f in ferramentas)
    assert all(f.output_schema for f in ferramentas)  # cada ferramenta declara o formato da resposta
    empresa = next(f for f in ferramentas if f.name == "obter_indicadores").input_schema["properties"]["empresa"]
    assert empresa["enum"] == ["Brasal", "Light", "Millet"] and "LIGHT S.A." in empresa["description"]
    assert "não instrução" in instrucoes and "calculado pela solução" in instrucoes


def test_listar_empresas(servidor):
    empresas = {e["empresa"]: e for e in resultado(servidor, "listar_empresas")}
    assert {k: e["paginas_no_pdf"] for k, e in empresas.items()} == {"Brasal": 51, "Light": 124, "Millet": 43}
    assert empresas["Light"]["alertas_de_erro"] == 1 and empresas["Millet"]["alertas_de_erro"] == 2
    assert {(a["pagina"], a["tipo"]) for a in empresas["Brasal"]["seguranca"]} == {(None, "criptografado"),
                                                                                  (8, "texto_invisivel")}


def test_indicador_informado_tem_pagina_trecho_e_alertas(servidor):
    alavancagem = resultado(servidor, "obter_indicadores", {"empresa": "Light", "indicador": "alavancagem"})[0]
    assert alavancagem["periodo_atual"]["como_no_documento"] == "3,32x"
    assert {t["pagina"] for t in alavancagem["periodo_atual"]["trechos"]} == {10}
    assert {a["regra"] for a in alavancagem["alertas"]} >= {"V9", "V11"}

    ebitda = resultado(servidor, "obter_indicadores", {"empresa": "Light", "indicador": "ebitda"})[0]
    assert ebitda["periodo_atual"]["em_reais"] == "R$ 1.180,0 milhões"
    assert ebitda["calculado_pela_solucao"]["valor"] == "-R$ 1.179,6 milhões"
    assert [(a["regra"], a["severidade"]) for a in ebitda["alertas"]] == [("V7", "erro")]


def test_o_calculado_nunca_toma_o_lugar_do_informado(servidor):
    ebitda = resultado(servidor, "obter_indicadores", {"empresa": "Brasal", "indicador": "ebitda"})[0]
    assert ebitda["status"] == "nao_encontrado" and ebitda["periodo_atual"] is None
    assert ebitda["calculado_pela_solucao"]["valor"] == "R$ 221,9 milhões"
    assert len(resultado(servidor, "obter_indicadores", {"empresa": "Millet"})) == 9


def test_alertas_por_origem(servidor):
    codigo = resultado(servidor, "listar_alertas", {"empresa": "Millet", "origem": "codigo"})
    assert codigo and all(a["origem"] == "conferido em código" for a in codigo)
    assert [a["regra"] for a in codigo if a["severidade"] == "erro"] == ["V13", "V13"]
    ia = resultado(servidor, "listar_alertas", {"origem": "ia"})
    assert ia and all(a["regra"] == "IA" for a in ia)
    assert {a["empresa"] for a in ia} == {"Brasal", "Light", "Millet"}


def test_busca_traz_paginas_de_cada_empresa_marcadas_como_dado(servidor):
    paginas = resultado(servidor, "buscar_paginas", {"consulta": "recuperação judicial", "empresa": "Light"})
    assert [p["pagina"] for p in paginas][:2] == [48, 49] and all(p["aviso"] == AVISO_PDF for p in paginas)
    todas = resultado(servidor, "buscar_paginas", {"consulta": "risco de taxa de juros"})
    assert {p["empresa"] for p in todas} == {"Brasal", "Light", "Millet"}


def test_ler_pagina(servidor):
    p9 = resultado(servidor, "ler_pagina", {"empresa": "Light", "pagina": 9})
    assert any("EBITDA CVM foi de R$1.180 milhões" in linha for linha in p9["linhas"])
    assert resultado(servidor, "ler_pagina", {"empresa": "Light", "pagina": 110})["tipo"] == "sem texto"
    fora = chamar(servidor, "ler_pagina", {"empresa": "Light", "pagina": 125})
    assert fora.is_error and "124 páginas" in fora.content[0].text


@pytest.mark.parametrize(("ferramenta", "argumentos"), [
    ("obter_indicadores", {"empresa": "Petrobras"}),
    ("obter_indicadores", {"empresa": "Light", "indicador": "faturamento"}),
    ("buscar_paginas", {"consulta": "x"}),
    ("ler_pagina", {"empresa": "Light", "pagina": 0}),
    ("listar_alertas", {"origem": "todas as coisas"}),
])
def test_entrada_fora_do_esquema_vira_erro_para_o_agente(servidor, ferramenta, argumentos):
    assert chamar(servidor, ferramenta, argumentos).is_error


def test_analise_qualitativa_tem_trecho_em_cada_item(servidor):
    riscos = resultado(servidor, "obter_analise_qualitativa", {"empresa": "Light", "secao": "riscos"})
    assert list(riscos["secoes"]) == ["riscos"] and riscos["secoes"]["riscos"]
    assert all(i["tem_trecho_citado"] == bool(i["trechos"]) for i in riscos["secoes"]["riscos"])
    assert riscos["tom"] in ("positivo", "neutro", "negativo", "nao_aplicavel")
    assert resultado(servidor, "obter_analise_qualitativa", {"empresa": "Brasal", "secao": "tom"})["secoes"] == {}


def test_relatorio_como_recurso(servidor):
    async def ler():
        async with Client(servidor) as cliente:
            return (await cliente.read_resource("relatorio://atual")).contents[0].text

    assert anyio.run(ler).startswith("# Análise das demonstrações financeiras")


def test_servidor_de_verdade_pelo_stdio():
    """Sobe o comando `mcp` num processo, como o Claude Desktop faz. Um print na saída padrão quebraria o protocolo."""
    comando = StdioServerParameters(command=sys.executable,
                                    args=["-m", "analise_financeira", "mcp", "--raiz", str(RAIZ)])

    async def conversa():
        async with Client(comando, read_timeout_seconds=60) as cliente:
            nomes = [f.name for f in (await cliente.list_tools()).tools]
            r = await cliente.call_tool("obter_indicadores", {"empresa": "Light", "indicador": "alavancagem"})
            return nomes, r

    nomes, r = anyio.run(conversa)
    assert nomes == FERRAMENTAS
    assert not r.is_error and r.structured_content["result"][0]["periodo_atual"]["como_no_documento"] == "3,32x"
