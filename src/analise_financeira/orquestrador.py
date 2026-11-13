"""Orquestrador: encadeia as etapas para cada PDF e grava cada resultado em saidas/.

A leitura dos PDFs é rápida e roda em sequência (o PyMuPDF não foi feito para
várias linhas de execução ao mesmo tempo). A etapa que demora é a chamada à IA:
essas rodam em paralelo, uma por documento.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from analise_financeira.esquemas import Extracao
from analise_financeira.extrator import extrair
from analise_financeira.indicadores import DocumentoAnalisado, analisar_numeros
from analise_financeira.llm import ClienteLLM
from analise_financeira.pdf import ler_pdf
from analise_financeira.roteamento import rotear


def processar_extracao(pasta_pdfs: str | Path, cliente: ClienteLLM,
                       pasta_saidas: str | Path = "saidas") -> dict[str, tuple[Extracao, DocumentoAnalisado]]:
    pdfs = sorted(Path(pasta_pdfs).glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"Nenhum PDF em {pasta_pdfs}")

    lidos = [(pdf, ler_pdf(pdf)) for pdf in pdfs]
    preparados = [(pdf, documento, rotear(documento)) for pdf, documento in lidos]

    def um(item: tuple) -> tuple[Extracao, DocumentoAnalisado]:
        pdf, documento, rotas = item
        extracao = extrair(documento, rotas, cliente)
        analise = analisar_numeros(extracao, documento, rotas)
        destino = Path(pasta_saidas) / pdf.stem
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "rotas.json").write_text(json.dumps(
            {"tipos": rotas.tipos, "extracao": rotas.extracao, "analise": rotas.analise}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        (destino / "extracao.json").write_text(extracao.model_dump_json(indent=1), encoding="utf-8")
        (destino / "indicadores.json").write_text(analise.model_dump_json(indent=1), encoding="utf-8")
        return extracao, analise

    with ThreadPoolExecutor(max_workers=3) as execucao:
        return dict(zip([p.name for p in pdfs], execucao.map(um, preparados), strict=True))
