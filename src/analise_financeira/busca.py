"""Busca por palavras (BM25) nas páginas dos PDFs, para o agente de perguntas.

Com 3 documentos, um banco de vetores seria complexidade sem ganho: a busca por
palavra acha "covenant", "liquidez" e "continuidade operacional" muito bem, e é
explicável (dá para ver por que uma página ganhou). Em produção, com milhares de
documentos, o lugar disto é o Azure AI Search híbrido: palavra + vetor + reranqueamento.

BM25 em poucas linhas, sem biblioteca: cada página é um trecho; a nota de uma página
sobe com as palavras raras da consulta que ela repete, e cai um pouco se a página
for muito longa. Pares de palavras vizinhas também contam ("recuperação judicial"
vale mais junto do que "recuperação" e "judicial" soltas na página).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from analise_financeira.pdf import Documento
from analise_financeira.roteamento import Rotas

PALAVRAS_VAZIAS = set("""
a ao aos as com como da das de do dos e em entre esta este foi for ha isso mais mas na nas no nos o os ou para
pela pelas pelo pelos por qual quais que se sem ser seu sua suas seus sobre sao tem um uma umas uns ja nao
cada qual quando onde empresa empresas companhia
""".split())


def termos(texto: str) -> list[str]:
    """Palavras sem acento, sem as vazias, com um radical curto: 'inadimplência' e 'inadimplente' viram 'inadimp'."""
    sem_acento = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    saida = []
    for palavra in re.findall(r"[a-z0-9]+", sem_acento):
        if palavra in PALAVRAS_VAZIAS or len(palavra) < 2:
            continue
        if len(palavra) > 4 and palavra.endswith("s"):
            palavra = palavra[:-1]  # plural simples: riscos -> risco
        saida.append(palavra[:7])
    return saida


def termos_e_pares(texto: str) -> list[str]:
    palavras = termos(texto)
    return palavras + [f"{a}_{b}" for a, b in zip(palavras, palavras[1:], strict=False)]


@dataclass(frozen=True)
class Trecho:
    documento: str      # "Light.pdf"
    pagina: int
    tipo: str           # tipo da página, do roteamento
    linhas: tuple[str, ...]


@dataclass(frozen=True)
class Achado:
    trecho: Trecho
    nota: float


class IndiceBM25:
    def __init__(self, trechos: list[Trecho], k1: float = 1.5, b: float = 0.75):
        self.trechos = trechos
        self.k1, self.b = k1, b
        self._contagens = [Counter(termos_e_pares(" ".join(t.linhas))) for t in trechos]
        self._tamanhos = [sum(c.values()) for c in self._contagens]
        self._media = (sum(self._tamanhos) / len(trechos)) if trechos else 1.0
        n = len(trechos)
        frequencia = Counter(termo for c in self._contagens for termo in c)
        self._idf = {termo: math.log(1 + (n - f + 0.5) / (f + 0.5)) for termo, f in frequencia.items()}

    def buscar(self, consulta: str, *, documento: str | None = None, k: int = 3) -> list[Achado]:
        consulta_termos = set(termos_e_pares(consulta))
        notas = []
        for i, contagem in enumerate(self._contagens):
            if documento and self.trechos[i].documento != documento:
                continue
            nota = 0.0
            for termo in consulta_termos:
                f = contagem.get(termo, 0)
                if f:
                    normal = 1 - self.b + self.b * self._tamanhos[i] / self._media
                    nota += self._idf[termo] * f * (self.k1 + 1) / (f + self.k1 * normal)
            if nota > 0:
                notas.append((nota, i))
        # Empate: a ordem do documento decide, para o resultado ser o mesmo em qualquer máquina.
        notas.sort(key=lambda x: (-x[0], self.trechos[x[1]].documento, self.trechos[x[1]].pagina))
        return [Achado(self.trechos[i], nota) for nota, i in notas[:k]]


def indexar(documentos: list[tuple[Documento, Rotas]]) -> IndiceBM25:
    """Um trecho por página com texto, de todos os documentos."""
    trechos = [Trecho(documento=doc.nome, pagina=p.numero, tipo=rotas.tipos.get(p.numero, "outros"), linhas=tuple(p.linhas))
               for doc, rotas in documentos for p in doc.paginas if p.linhas]
    return IndiceBM25(trechos)
