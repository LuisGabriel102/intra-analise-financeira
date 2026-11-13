"""Orquestrador: encadeia as etapas e grava cada resultado em saidas/.

    ler PDF -> rotear páginas -> extrair (IA) -> indicadores e alertas (código)
            -> análise qualitativa (IA)  -> perguntas (agente com ferramentas) -> relatório (código)

A leitura dos PDFs é rápida e roda em sequência (o PyMuPDF não foi feito para
várias linhas de execução ao mesmo tempo). As etapas que demoram são as chamadas
à IA: essas rodam em paralelo, uma linha por documento e depois uma por pergunta.
O fluxo é fixo, em código: a IA não decide a ordem das etapas.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from analise_financeira.analista import analisar
from analise_financeira.busca import indexar
from analise_financeira.esquemas import AnaliseQualitativa, Extracao, RespostaPergunta
from analise_financeira.extrator import extrair
from analise_financeira.indicadores import DocumentoAnalisado, analisar_numeros
from analise_financeira.llm import ClienteLLM
from analise_financeira.pdf import Documento, ler_pdf
from analise_financeira.perguntas import Base, responder_obrigatorias
from analise_financeira.relatorio import ResultadoDocumento, montar_relatorio
from analise_financeira.roteamento import Rotas, rotear


@dataclass
class Execucao:
    resultados: list[ResultadoDocumento]
    respostas: list[RespostaPergunta]
    relatorio: Path | None
    segundos: float


def _ler(pasta_pdfs: str | Path) -> list[tuple[Path, Documento, Rotas]]:
    pdfs = sorted(Path(pasta_pdfs).glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"Nenhum PDF em {pasta_pdfs}")
    lidos = [(pdf, ler_pdf(pdf)) for pdf in pdfs]
    return [(pdf, documento, rotear(documento)) for pdf, documento in lidos]


def _gravar(destino: Path, nome: str, conteudo: str) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    (destino / nome).write_text(conteudo, encoding="utf-8")


def _extrair_um(pdf: Path, documento: Documento, rotas: Rotas, cliente: ClienteLLM,
                pasta_saidas: Path) -> tuple[Extracao, DocumentoAnalisado]:
    extracao = extrair(documento, rotas, cliente)
    numeros = analisar_numeros(extracao, documento, rotas)
    destino = pasta_saidas / pdf.stem
    _gravar(destino, "rotas.json", json.dumps(
        {"tipos": rotas.tipos, "extracao": rotas.extracao, "analise": rotas.analise}, ensure_ascii=False, indent=1))
    _gravar(destino, "extracao.json", extracao.model_dump_json(indent=1))
    _gravar(destino, "indicadores.json", numeros.model_dump_json(indent=1))
    return extracao, numeros


def processar_extracao(pasta_pdfs: str | Path, cliente: ClienteLLM,
                       pasta_saidas: str | Path = "saidas") -> dict[str, tuple[Extracao, DocumentoAnalisado]]:
    """Só a extração e os indicadores (comando `extrair`)."""
    preparados = _ler(pasta_pdfs)
    with ThreadPoolExecutor(max_workers=3) as execucao:
        feitos = execucao.map(lambda item: _extrair_um(*item, cliente, Path(pasta_saidas)), preparados)
        return dict(zip([pdf.name for pdf, _, _ in preparados], feitos, strict=True))


def processar(pasta_pdfs: str | Path, cliente: ClienteLLM, pasta_saidas: str | Path = "saidas",
              com_perguntas: bool = True) -> Execucao:
    """Tudo: extração, indicadores, análise qualitativa, as 5 perguntas e o relatório (comando `analisar`)."""
    inicio = time.perf_counter()
    saidas = Path(pasta_saidas)
    preparados = _ler(pasta_pdfs)

    def um(item: tuple[Path, Documento, Rotas]) -> ResultadoDocumento:
        pdf, documento, rotas = item
        extracao, numeros = _extrair_um(pdf, documento, rotas, cliente, saidas)
        qualitativa = analisar(documento, rotas, numeros, cliente)
        _gravar(saidas / pdf.stem, "analise.json", qualitativa.model_dump_json(indent=1))
        return ResultadoDocumento(arquivo=pdf.name, extracao=extracao, numeros=numeros, qualitativa=qualitativa)

    with ThreadPoolExecutor(max_workers=3) as execucao:
        resultados = list(execucao.map(um, preparados))

    respostas: list[RespostaPergunta] = []
    if com_perguntas:
        base = montar_base(preparados, resultados)
        respostas = responder_obrigatorias(base, cliente)
        _gravar(saidas, "perguntas.json", json.dumps([r.model_dump(mode="json") for r in respostas],
                                                     ensure_ascii=False, indent=1))
    segundos = time.perf_counter() - inicio
    texto = montar_relatorio(resultados, respostas, gerado_em=datetime.now(), duracao_s=segundos)
    _gravar(saidas, "relatorio.md", texto)
    return Execucao(resultados=resultados, respostas=respostas, relatorio=saidas / "relatorio.md", segundos=segundos)


def montar_base(preparados: list[tuple[Path, Documento, Rotas]], resultados: list[ResultadoDocumento]) -> Base:
    return Base(
        documentos={r.chave: r.arquivo for r in resultados},
        numeros={r.chave: r.numeros for r in resultados},
        qualitativa={r.chave: r.qualitativa for r in resultados if r.qualitativa},
        indice=indexar([(documento, rotas) for _, documento, rotas in preparados]),
    )


def carregar_base(pasta_pdfs: str | Path, pasta_saidas: str | Path = "saidas") -> Base:
    """Para perguntas livres: relê os PDFs e carrega o que o comando `analisar` gravou em saidas/."""
    preparados = _ler(pasta_pdfs)
    resultados = []
    for pdf, _, _ in preparados:
        pasta = Path(pasta_saidas) / pdf.stem
        if not (pasta / "analise.json").exists():
            raise FileNotFoundError(f"Falta {pasta / 'analise.json'}. Rode `python -m analise_financeira analisar` antes.")
        resultados.append(ResultadoDocumento(
            arquivo=pdf.name,
            extracao=Extracao.model_validate_json((pasta / "extracao.json").read_text(encoding="utf-8")),
            numeros=DocumentoAnalisado.model_validate_json((pasta / "indicadores.json").read_text(encoding="utf-8")),
            qualitativa=AnaliseQualitativa.model_validate_json((pasta / "analise.json").read_text(encoding="utf-8")),
        ))
    return montar_base(preparados, resultados)
