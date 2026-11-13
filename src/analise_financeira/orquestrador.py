"""Orquestrador: encadeia as etapas para cada PDF e grava cada resultado em saidas/.

Os documentos rodam em paralelo (um por vez em cada linha de execução): a etapa
que demora é a chamada à IA, e as três podem acontecer ao mesmo tempo.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from analise_financeira.esquemas import Extracao
from analise_financeira.extrator import extrair
from analise_financeira.llm import ClienteLLM
from analise_financeira.pdf import ler_pdf
from analise_financeira.roteamento import rotear


def processar_extracao(pasta_pdfs: str | Path, cliente: ClienteLLM, pasta_saidas: str | Path = "saidas") -> dict[str, Extracao]:
    pdfs = sorted(Path(pasta_pdfs).glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"Nenhum PDF em {pasta_pdfs}")

    def um(pdf: Path) -> Extracao:
        documento = ler_pdf(pdf)
        rotas = rotear(documento)
        extracao = extrair(documento, rotas, cliente)
        destino = Path(pasta_saidas) / pdf.stem
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "rotas.json").write_text(json.dumps(
            {"tipos": rotas.tipos, "extracao": rotas.extracao, "analise": rotas.analise}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        (destino / "extracao.json").write_text(extracao.model_dump_json(indent=1), encoding="utf-8")
        return extracao

    with ThreadPoolExecutor(max_workers=3) as execucao:
        return dict(zip([p.name for p in pdfs], execucao.map(um, pdfs), strict=True))
