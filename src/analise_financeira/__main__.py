"""Linha de comando.

    python -m analise_financeira analisar            # tudo: extração, análise, 5 perguntas e relatório (chama a IA)
    python -m analise_financeira analisar --replay   # o mesmo, só com as respostas gravadas: sem chave e sem custo
    python -m analise_financeira perguntar "Qual empresa tem mais caixa?"   # pergunta livre
    python -m analise_financeira extrair [--replay]  # só a extração dos indicadores
    python -m analise_financeira avaliar             # compara as saídas com o gabarito
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from analise_financeira.esquemas import Uso
from analise_financeira.llm import ClienteLLM, SemGravacao


def _custo(uso: Uso) -> str:
    if uso.gravada:
        return f"US$ 0 agora (resposta gravada; a chamada original custou US$ {uso.custo_usd:.4f} e levou {uso.segundos:.1f} s)"
    return f"US$ {uso.custo_usd:.4f} | {uso.segundos:.1f} s"


def _resumo_extracao(nome, extracao) -> str:
    status = [c.status for c in extracao.campos.values()]
    uso = extracao.uso
    return (f"{nome}: {status.count('encontrado')} campos encontrados, {status.count('nao_encontrado')} não encontrados, "
            f"{status.count('sem_evidencia')} sem evidência | {len(extracao.paginas_enviadas)} páginas | "
            f"{uso.tokens_entrada} + {uso.tokens_saida} tokens | {_custo(uso)}")


def _resumo_alertas(analise) -> str:
    codigo = [a for a in analise.alertas if a.origem == "codigo"]
    erros = sum(1 for a in codigo if a.severidade == "erro")
    return f"    alertas: {len(codigo)} conferidos em código ({erros} de erro) e {len(analise.alertas) - len(codigo)} observações da IA"


def _resumo_qualitativa(q) -> str:
    itens = [*q.motivos, *q.riscos, *q.guidance, *q.perspectivas, *q.eventos, *q.comparabilidade, *q.observacoes]
    sem_trecho = sum(1 for i in itens if not i.conferido)
    sem_fonte = sum(1 for i in itens if i.numeros_sem_fonte)
    return (f"    análise qualitativa: {len(q.motivos)} motivos, {len(q.riscos)} riscos, {len(q.eventos)} eventos, "
            f"tom {q.tom or '?'}, guidance {q.guidance_status}{'' if q.completa else ' (RESPOSTA CORTADA)'} | "
            f"{len(itens)} itens, {sem_trecho} sem trecho, "
            f"{sem_fonte} com número sem fonte | {len(q.paginas_enviadas)} páginas | "
            f"{q.uso.tokens_entrada} + {q.uso.tokens_saida} tokens | {_custo(q.uso)}")


def _cliente(args) -> ClienteLLM:
    return ClienteLLM(modelo=args.modelo, replay=args.replay, chave=os.getenv("ANTHROPIC_API_KEY"))


def _erro_da_api(erro: Exception) -> str | None:
    try:
        import anthropic
    except ImportError:  # pragma: no cover
        return None
    if isinstance(erro, anthropic.APIError):
        return (f"A API recusou o pedido ({type(erro).__name__}): {erro}. As chamadas que deram certo ficaram gravadas "
                f"em gravacoes/; rode o mesmo comando de novo para continuar de onde parou.")
    return None


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    load_dotenv()
    parser = argparse.ArgumentParser(prog="analise_financeira", description="Análise de demonstrações financeiras em PDF.")
    comandos = parser.add_subparsers(dest="comando", required=True)
    modelo = os.getenv("MODELO_EXTRACAO", "claude-opus-5-5")

    an = comandos.add_parser("analisar", help="faz tudo: extração, análise qualitativa, as 5 perguntas e o relatório")
    an.add_argument("pasta", nargs="?", default="dados/pdfs")
    an.add_argument("--replay", action="store_true", help="usa só as respostas gravadas, sem chave e sem custo")
    an.add_argument("--modelo", default=modelo)
    an.add_argument("--sem-perguntas", action="store_true", help="pula as 5 perguntas")

    pg = comandos.add_parser("perguntar", help="responde uma pergunta livre (rode `analisar` antes)")
    pg.add_argument("pergunta")
    pg.add_argument("--pasta", default="dados/pdfs")
    pg.add_argument("--replay", action="store_true", help="usa só as respostas gravadas")
    pg.add_argument("--modelo", default=modelo)

    ext = comandos.add_parser("extrair", help="só lê os PDFs e extrai os indicadores, com página e trecho")
    ext.add_argument("pasta", nargs="?", default="dados/pdfs")
    ext.add_argument("--replay", action="store_true", help="usa só as respostas gravadas, sem chave e sem custo")
    ext.add_argument("--modelo", default=modelo)

    comandos.add_parser("avaliar", help="compara as saídas gravadas em saidas/ com o gabarito")

    mc = comandos.add_parser("mcp", help="servidor MCP (stdio) com os dados de saidas/, para o Claude Desktop ou "
                                         "outro agente; só leitura, sem chamar a IA")
    mc.add_argument("--raiz", type=Path, default=None,
                    help="pasta do repositório, com saidas/ e dados/pdfs/ (padrão: a deste pacote)")
    args = parser.parse_args()

    if args.comando == "mcp":  # antes de qualquer print: no stdio, a saída padrão é do protocolo
        try:
            from analise_financeira.servidor_mcp import raiz_padrao, rodar
        except ImportError:
            print('Erro: falta o pacote mcp. Instale com: python -m pip install -e ".[mcp]"', file=sys.stderr)
            return 1
        try:
            rodar(args.raiz or raiz_padrao())
        except FileNotFoundError as erro:
            print(f"Erro: {erro}", file=sys.stderr)
            return 1
        return 0

    if args.comando == "avaliar":
        from analise_financeira.avaliacao import avaliar

        try:
            print(avaliar())
        except FileNotFoundError as erro:
            print(f"Erro: falta rodar a extração antes ({erro.filename}).")
            return 1
        return 0

    inicio = time.perf_counter()
    try:
        if args.comando == "extrair":
            from analise_financeira.orquestrador import processar_extracao

            for nome, (extracao, analise) in processar_extracao(args.pasta, _cliente(args)).items():
                print(_resumo_extracao(nome, extracao))
                print(_resumo_alertas(analise))
        elif args.comando == "analisar":
            from analise_financeira.orquestrador import processar

            execucao = processar(args.pasta, _cliente(args), com_perguntas=not args.sem_perguntas)
            for r in execucao.resultados:
                print(_resumo_extracao(r.arquivo, r.extracao))
                print(_resumo_alertas(r.numeros))
                print(_resumo_qualitativa(r.qualitativa))
            for p in execucao.respostas:
                print(f"Pergunta {p.numero}: {len(p.fontes)} fontes, {p.rodadas} rodadas"
                      f"{'' if p.completa else ' (INCOMPLETA)'} | {p.uso.tokens_entrada} + {p.uso.tokens_saida} tokens "
                      f"({p.uso.tokens_cache_lidos} do cache) | {_custo(p.uso)}")
            print(f"Relatório: {execucao.relatorio}")
        else:
            from analise_financeira.orquestrador import carregar_base
            from analise_financeira.perguntas import responder

            resposta = responder(args.pergunta, carregar_base(args.pasta), _cliente(args))
            print(resposta.texto, "", "Fontes:", sep="\n")
            for i, f in enumerate(resposta.fontes, start=1):
                print(f"  [{i}] {f.documento}, p. {', '.join(map(str, f.paginas))}: {f.trecho[:160]}")
            print(f"({resposta.rodadas} rodadas | {_custo(resposta.uso)})")
    except (SemGravacao, RuntimeError, FileNotFoundError) as erro:
        print(f"Erro: {erro}")
        return 1
    except Exception as erro:
        mensagem = _erro_da_api(erro)
        if mensagem is None:
            raise
        print(f"Erro: {mensagem}")
        return 1
    print(f"Total: {time.perf_counter() - inicio:.1f} s. Resultados em saidas/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
