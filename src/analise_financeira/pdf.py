"""Leitura dos PDFs: as linhas de cada página, com as colunas das tabelas separadas.

Uma tabela num PDF é só um monte de palavras soltas, cada uma numa posição.
Este módulo junta as palavras que estão na mesma altura numa linha só e põe
" | " onde há um vão grande entre elas, que é a separação de colunas:

    RECEITA LÍQUIDA | 31 | - | - | 13.253.286 | 14.897.920

Cada linha vira um bloco que a IA pode citar. Assim, a citação aponta a linha
exata da tabela, e não a página inteira.

Antes de juntar as palavras, a varredura de segurança (seguranca.py) tira o texto escondido
que tenta manipular a IA, e anota o que achou em `Documento.seguranca`.

Ferramenta: PyMuPDF. É rápido, local e abre o PDF criptografado da Brasal.
Em produção, o lugar dele é do Azure Document Intelligence (veja o README).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from analise_financeira.esquemas import AchadoSeguranca
from analise_financeira.numeros import detectar_escala
from analise_financeira.seguranca import comandos_visiveis, varrer_documento, varrer_pagina

LIMITE_MB = 50
LIMITE_PAGINAS = 500


@dataclass
class Pagina:
    numero: int                     # página do PDF, contando a capa como 1
    linhas: list[str]               # linhas da página; colunas separadas por " | "
    escala: str = ""                # "mil", "milhões" ou "" (do cabeçalho da página)
    pagina_impressa: int | None = None  # o número no rodapé, quando existe
    vazia: bool = False             # sem texto e sem imagem
    precisa_ocr: bool = False       # sem texto, mas com imagem (página escaneada)

    @property
    def texto(self) -> str:
        return "\n".join(self.linhas)


@dataclass
class Documento:
    nome: str                       # "Light.pdf"
    paginas: list[Pagina] = field(default_factory=list)
    escala_padrao: str = ""         # a escala mais comum entre as páginas que avisam a escala
    seguranca: list[AchadoSeguranca] = field(default_factory=list)  # o que a varredura achou

    def pagina(self, numero: int) -> Pagina:
        return self.paginas[numero - 1]

    def escala_de(self, numero: int) -> str:
        """A escala da página. Página de nota sem o aviso "(Em milhares de reais)" usa a do documento."""
        return self.pagina(numero).escala or self.escala_padrao


def _juntar_em_linhas(palavras: list[tuple]) -> list[str]:
    """Agrupa as palavras pela altura e devolve as linhas, de cima para baixo."""
    grupos: list[dict] = []
    for p in sorted(palavras, key=lambda p: ((p[1] + p[3]) / 2, p[0])):
        centro, altura = (p[1] + p[3]) / 2, p[3] - p[1]
        if grupos and abs(centro - grupos[-1]["centro"]) <= max(2.0, 0.4 * altura):
            grupos[-1]["palavras"].append(p)
        else:
            grupos.append({"centro": centro, "palavras": [p]})

    linhas = []
    for grupo in grupos:
        ps = sorted(grupo["palavras"], key=lambda p: p[0])
        texto = ps[0][4]
        for anterior, atual in zip(ps, ps[1:], strict=False):
            vao = atual[0] - anterior[2]
            altura = anterior[3] - anterior[1]
            texto += (" | " if vao > max(6.0, 0.9 * altura) else " ") + atual[4]
        linhas.append(texto.strip())
    return [linha for linha in linhas if linha]


def _pagina_impressa(linhas: list[str]) -> int | None:
    """O número de página impresso costuma ser a última linha, sozinho."""
    if linhas and linhas[-1].isdigit() and len(linhas[-1]) <= 4:
        return int(linhas[-1])
    return None


def _fora_das_areas(palavras: list[tuple], areas: list[pymupdf.Rect]) -> list[tuple]:
    """As palavras cujo centro não está em nenhuma das áreas tiradas pela varredura."""
    if not areas:
        return palavras
    return [p for p in palavras if not any(a.contains(pymupdf.Point((p[0] + p[2]) / 2, (p[1] + p[3]) / 2))
                                           for a in areas)]


def ler_pdf(caminho: str | Path, *, varrer: bool = True) -> Documento:
    """Lê o PDF inteiro. Recusa arquivo grande demais, com página demais ou com senha.

    varrer=False lê sem a varredura de segurança: só serve para os testes compararem as duas leituras.
    """
    caminho = Path(caminho)
    if caminho.stat().st_size > LIMITE_MB * 1_000_000:
        raise ValueError(f"{caminho.name}: maior que {LIMITE_MB} MB")
    documento = Documento(nome=caminho.name)
    with pymupdf.open(caminho) as pdf:
        if pdf.needs_pass and not pdf.authenticate(""):
            raise ValueError(f"{caminho.name}: o PDF pede senha")
        if pdf.page_count > LIMITE_PAGINAS:
            raise ValueError(f"{caminho.name}: mais de {LIMITE_PAGINAS} páginas")
        if varrer:
            documento.seguranca += varrer_documento(pdf, caminho.name)
        for indice, pagina in enumerate(pdf, start=1):
            palavras = pagina.get_text("words")
            if varrer:
                varredura = varrer_pagina(pagina, caminho.name)
                palavras = _fora_das_areas(palavras, varredura.remover)
            linhas = _juntar_em_linhas(palavras)
            if varrer:
                documento.seguranca += varredura.achados + comandos_visiveis(linhas, caminho.name, indice)
            tem_imagem = bool(pagina.get_images())
            documento.paginas.append(Pagina(
                numero=indice,
                linhas=linhas,
                escala=detectar_escala("\n".join(linhas[:12])),
                pagina_impressa=_pagina_impressa(linhas),
                vazia=not linhas and not tem_imagem,
                precisa_ocr=not linhas and tem_imagem,
            ))
    # Nas notas explicativas, o aviso de escala costuma vir só na primeira página.
    # A escala mais comum do documento vale para as páginas que não avisam.
    # (Usar "a última página com aviso" seria pior: uma tabela em milhões no meio
    # das notas contaminaria todas as páginas seguintes.)
    escalas = Counter(p.escala for p in documento.paginas if p.escala)
    documento.escala_padrao = escalas.most_common(1)[0][0] if escalas else ""
    return documento
