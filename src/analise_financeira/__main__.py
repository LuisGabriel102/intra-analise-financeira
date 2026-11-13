"""Linha de comando.

    python -m analise_financeira extrair            # chama a IA (precisa da chave no .env)
    python -m analise_financeira extrair --replay   # usa só as respostas gravadas: sem chave e sem custo
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from dotenv import load_dotenv

from analise_financeira.llm import ClienteLLM, SemGravacao
from analise_financeira.orquestrador import processar_extracao


def _resumo(nome, extracao) -> str:
    status = [c.status for c in extracao.campos.values()]
    uso = extracao.uso
    origem = "resposta gravada" if uso.gravada else "chamada nova"
    return (f"{nome}: {status.count('encontrado')} campos encontrados, {status.count('nao_encontrado')} não encontrados, "
            f"{status.count('sem_evidencia')} sem evidência | {len(extracao.paginas_enviadas)} páginas | "
            f"{uso.tokens_entrada} + {uso.tokens_saida} tokens | US$ {uso.custo_usd:.4f} | {uso.segundos:.1f} s ({origem})")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    load_dotenv()
    parser = argparse.ArgumentParser(prog="analise_financeira", description="Análise de demonstrações financeiras em PDF.")
    comandos = parser.add_subparsers(dest="comando", required=True)
    ext = comandos.add_parser("extrair", help="lê os PDFs e extrai os indicadores, com página e trecho")
    ext.add_argument("pasta", nargs="?", default="dados/pdfs")
    ext.add_argument("--replay", action="store_true", help="usa só as respostas gravadas, sem chave e sem custo")
    ext.add_argument("--modelo", default=os.getenv("MODELO_EXTRACAO", "claude-opus-5-5"))
    comandos.add_parser("avaliar", help="compara a extração gravada em saidas/ com o gabarito")
    args = parser.parse_args()

    if args.comando == "avaliar":
        from analise_financeira.avaliacao import avaliar

        try:
            print(avaliar())
        except FileNotFoundError as erro:
            print(f"Erro: falta rodar a extração antes ({erro.filename}).")
            return 1
        return 0

    cliente = ClienteLLM(modelo=args.modelo, replay=args.replay, chave=os.getenv("ANTHROPIC_API_KEY"))
    inicio = time.perf_counter()
    try:
        resultados = processar_extracao(args.pasta, cliente)
    except (SemGravacao, RuntimeError, FileNotFoundError) as erro:
        print(f"Erro: {erro}")
        return 1
    for nome, extracao in resultados.items():
        print(_resumo(nome, extracao))
    print(f"Total: {time.perf_counter() - inicio:.1f} s. Resultados em saidas/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
