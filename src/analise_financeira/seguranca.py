"""Varredura de segurança do PDF, antes de qualquer texto chegar à IA.

Um PDF é conteúdo de terceiros. O ataque mais simples é esconder uma ordem para a IA no texto:
letra branca sobre fundo branco, fonte de 1 ponto, texto fora da página ou embaixo de um
retângulo. O leitor humano não vê; a extração de texto vê, e a IA leria.

O que a varredura faz, página por página:
1. acha o texto que um leitor não veria: cor sem contraste com o fundo que está atrás dele
   (o fundo é o último retângulo preenchido desenhado antes do texto, ou a página branca),
   coberto por um retângulo desenhado depois, transparente, invisível, fora da página ou
   com fonte menor que 1,5 ponto;
2. decide o que fazer com ele. Texto invisível com frase de comando, número de valor ou mais
   de 20 letras sai do que vai para a IA (gravidade alta). Texto invisível curto, sem número,
   como um "#" branco esquecido na diagramação, fica, com aviso baixo: tirar mudaria a
   leitura de documentos legítimos sem proteger nada;
3. procura frases de comando visíveis ("ignore as instruções anteriores"). Essas ficam no texto,
   porque o leitor também as vê, mas saem com aviso alto no relatório.

E no documento: JavaScript, ações que abrem programa, arquivos anexados e criptografia.

Os cabeçalhos da Light são texto branco sobre faixa escura: o fundo atrás deles é escuro,
então são visíveis, e a varredura não os toca. Nos 3 PDFs do desafio, ela não tira nada.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import pymupdf

from analise_financeira.esquemas import AchadoSeguranca

FONTE_MINIMA = 1.5          # pontos
CONTRASTE_MINIMO = 0.15     # diferença de luminância entre o texto e o fundo, de 0 a 1
LETRAS_SUSPEITAS = 20       # texto invisível com mais letras que isto não é resto de diagramação

# Frases de comando para uma IA, em português e em inglês. Comparadas sem acento e em minúsculas.
_COMANDOS = re.compile(
    r"ignor[ea]\w*\s+(?:as\s+|todas\s+as\s+|os\s+|todos\s+os\s+)?(?:instruc|orientac|regras|comandos)"
    r"|desconsider[ea]\w*\s+(?:as\s+|todas\s+as\s+)?(?:instruc|orientac|regras)"
    r"|esquec[ae]\w*\s+(?:as\s+|todas\s+as\s+)?(?:instruc|orientac|regras)"
    r"|novas\s+instrucoes\s*:|instrucoes\s+do\s+sistema|voce\s+agora\s+e\b|aja\s+como\s+(?:um|uma)\b"
    r"|ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)\s+(?:instructions|prompts?|rules)"
    r"|disregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above)\s+(?:instructions|prompts?|rules)"
    r"|\bsystem\s+prompt\b|\byou\s+are\s+now\b|\bnew\s+instructions\s*:"
)
_VALOR = re.compile(r"\d[\d.,]{3,}\d|\d+(?:[.,]\d+)?\s*%|R\$|US\$")


@dataclass
class Varredura:
    """O resultado de uma página: as áreas de texto a tirar antes da IA e o que foi achado."""

    remover: list[pymupdf.Rect]
    achados: list[AchadoSeguranca]


def _texto(span: dict) -> str:
    """O texto de um trecho do texttrace. Glifo sem código Unicode vira vazio, em vez de derrubar a leitura."""
    return "".join(chr(c[0]) for c in span["chars"] if 0 < c[0] < 0x110000)


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()


def tem_comando(texto: str) -> bool:
    return bool(_COMANDOS.search(_sem_acento(texto)))


def _luminancia(cor) -> float:
    """De 0 (preto) a 1 (branco). Aceita cinza, RGB e CMYK, como o PyMuPDF devolve."""
    if cor is None:
        return 0.0
    if isinstance(cor, int):
        cor = ((cor >> 16 & 255) / 255, (cor >> 8 & 255) / 255, (cor & 255) / 255)
    cor = tuple(cor)
    if len(cor) == 1:
        return float(cor[0])
    if len(cor) == 4:
        c, m, y, k = cor
        cor = ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    r, g, b = cor[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


FAIXA = 20.0  # altura das faixas do índice de retângulos, em pontos


class _Areas:
    """Os retângulos preenchidos e opacos da página, num índice por faixa de altura.

    Comparar cada texto com cada retângulo seria lento (uma página de tabela tem centenas de cada).
    Cada retângulo entra nas faixas de altura que ocupa; cada texto só olha a faixa do seu centro.
    """

    def __init__(self, pagina: pymupdf.Page):
        self.faixas: dict[int, list[tuple[int, float, float, float, float, float]]] = {}
        for d in pagina.get_cdrawings():
            if d.get("fill") is None or (d.get("fill_opacity") or 1.0) < 0.5:
                continue
            caixas = [tuple(i[1]) for i in d["items"] if i[0] == "re" and len(i[1]) == 4]
            for i in d["items"]:
                if i[0] == "qu":
                    try:
                        caixas.append(tuple(pymupdf.Quad(i[1]).rect))
                    except (TypeError, ValueError):
                        continue
            lum = _luminancia(d["fill"])
            # Um caminho com vários retângulos vem com o contorno de todos: vale cada retângulo, e não o contorno.
            for x0, y0, x1, y1 in caixas or [tuple(d["rect"])]:
                area = (d["seqno"], min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), lum)
                for f in range(int(area[2] // FAIXA), int(area[4] // FAIXA) + 1):
                    self.faixas.setdefault(f, []).append(area)

    def perto(self, y: float):
        return self.faixas.get(int(y // FAIXA), [])


def _por_que_invisivel(span: dict, pagina: pymupdf.Page, areas: _Areas, imagens) -> str | None:
    x0, y0, x1, y1 = span["bbox"]
    largura, altura = pagina.rect.width, pagina.rect.height
    if x1 <= 0 or y1 <= 0 or x0 >= largura or y0 >= altura:
        return "fora da página"
    if span.get("type") == 3:  # modo de pintura "invisível": comum na camada de OCR, que fica sobre a imagem
        return None if imagens().intersects_any(span["bbox"]) else "modo invisível"
    if (span.get("opacity") if span.get("opacity") is not None else 1.0) < 0.1:
        return "transparente"
    if span["size"] < FONTE_MINIMA:
        return f"fonte de {span['size']:.1f} ponto"
    cx, cy, seq = (x0 + x1) / 2, (y0 + y1) / 2, span["seqno"]
    motivo, fundo, ordem_do_fundo = None, 1.0, -1  # sem retângulo atrás: a página, branca
    for s, a0, b0, a1, b1, lum in areas.perto(cy):
        if s > seq and a0 <= x0 and b0 <= y0 and a1 >= x1 and b1 >= y1:
            motivo = "coberto por um retângulo"
            break
        if s < seq and s > ordem_do_fundo and a0 <= cx <= a1 and b0 <= cy <= b1:
            fundo, ordem_do_fundo = lum, s
    if motivo is None and abs(_luminancia(span["color"]) - fundo) < CONTRASTE_MINIMO:
        motivo = "da cor do fundo"
    if motivo and imagens().contains_point(cx, cy):
        return None  # sobre imagem: não dá para saber o fundo; fica como visível
    return motivo


class _Imagens:
    """As caixas das imagens da página, lidas só se alguma conferência precisar delas."""

    def __init__(self, pagina: pymupdf.Page):
        self._pagina, self._caixas = pagina, None

    def __call__(self) -> _Imagens:
        if self._caixas is None:
            self._caixas = [tuple(i["bbox"]) for i in self._pagina.get_image_info()]
        return self

    def contains_point(self, x: float, y: float) -> bool:
        return any(a0 <= x <= a1 and b0 <= y <= b1 for a0, b0, a1, b1 in self._caixas)

    def intersects_any(self, caixa) -> bool:
        x0, y0, x1, y1 = caixa
        return any(a0 < x1 and x0 < a1 and b0 < y1 and y0 < b1 for a0, b0, a1, b1 in self._caixas)


def varrer_pagina(pagina: pymupdf.Page, documento: str) -> Varredura:
    numero = pagina.number + 1
    spans = [s for s in pagina.get_texttrace() if _texto(s).strip()]
    areas = _Areas(pagina) if spans else None
    imagens = _Imagens(pagina)

    escondidos = []
    for s in spans:
        motivo = _por_que_invisivel(s, pagina, areas, imagens)
        if motivo:
            escondidos.append((s, motivo))
    achados: list[AchadoSeguranca] = []
    remover: list[pymupdf.Rect] = []
    if escondidos:
        texto = " ".join(_texto(s).strip() for s, _ in escondidos)
        motivos = ", ".join(dict.fromkeys(m for _, m in escondidos))
        letras = sum(ch.isalnum() for ch in texto)
        suspeito = tem_comando(texto) or bool(_VALOR.search(texto)) or letras > LETRAS_SUSPEITAS
        amostra = texto if len(texto) <= 120 else texto[:117] + "..."
        if suspeito:
            remover = [pymupdf.Rect(s["bbox"]) for s, _ in escondidos]
            achados.append(AchadoSeguranca(
                documento=documento, pagina=numero, tipo="texto_invisivel", gravidade="alta", removido=True,
                detalhe=f"Texto que o leitor não vê ({motivos}), tirado antes da IA: \"{amostra}\""))
        else:
            achados.append(AchadoSeguranca(
                documento=documento, pagina=numero, tipo="texto_invisivel", gravidade="baixa", removido=False,
                detalhe=f"Texto invisível curto e sem número ({motivos}), provável resto de diagramação. "
                        f"Ficou no texto: \"{amostra}\""))
    return Varredura(remover=remover, achados=achados)


def comandos_visiveis(linhas: list[str], documento: str, numero: int) -> list[AchadoSeguranca]:
    """Frases de comando para a IA no texto que o leitor vê. Ficam, mas com aviso alto."""
    return [AchadoSeguranca(documento=documento, pagina=numero, tipo="frase_de_comando", gravidade="alta",
                            removido=False, detalhe=f"Frase de comando para a IA no texto da página: \"{linha[:120]}\"")
            for linha in linhas if tem_comando(linha)]


def varrer_documento(pdf: pymupdf.Document, documento: str) -> list[AchadoSeguranca]:
    """O que vale para o arquivo inteiro: JavaScript, ações que abrem programa, anexos e criptografia."""
    achados = []
    objetos = []
    for x in range(1, pdf.xref_length()):
        try:
            objetos.append(pdf.xref_object(x, compressed=True))
        except (RuntimeError, ValueError):  # entrada livre ou quebrada na tabela de objetos
            continue
    metadados = pdf.metadata or {}
    if any(re.search(r"/JavaScript\b|/JS\s*[(<\[\d]", o) for o in objetos):
        achados.append(AchadoSeguranca(documento=documento, tipo="javascript", gravidade="alta", removido=False,
                                       detalhe="O PDF tem JavaScript. A solução só lê o texto e não executa nada."))
    if any(re.search(r"/S\s*/Launch\b", o) for o in objetos):
        achados.append(AchadoSeguranca(documento=documento, tipo="abre_programa", gravidade="alta", removido=False,
                                       detalhe="O PDF tem uma ação que abre um programa ou arquivo externo."))
    anexos = pdf.embfile_count() + sum(1 for p in pdf for a in (p.annots() or []) if a.type[1] == "FileAttachment")
    if anexos:
        achados.append(AchadoSeguranca(documento=documento, tipo="anexo", gravidade="alta", removido=False,
                                       detalhe=f"O PDF traz {anexos} arquivo(s) anexado(s). A solução não os abre."))
    if pdf.is_encrypted or metadados.get("encryption"):
        achados.append(AchadoSeguranca(documento=documento, tipo="criptografado", gravidade="info", removido=False,
                                       detalhe=f"PDF criptografado ({metadados.get('encryption') or 'sem detalhe'}), "
                                               "mas abre sem senha. A leitura é normal."))
    return achados
