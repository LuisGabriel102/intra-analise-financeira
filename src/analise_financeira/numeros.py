"""Leitor de números no padrão brasileiro.

As demonstrações financeiras escrevem números assim:

    1.325.059          o ponto separa os milhares
    (839.903)          parênteses numa tabela querem dizer "menos"
    -                  um traço sozinho na célula quer dizer zero
    19,30%             a vírgula separa os decimais
    R$1.817 milhões    a escala vem escrita do lado
    3,32x              um múltiplo, como a alavancagem

Cuidado: "2.693" é dois mil seiscentos e noventa e três, e não "dois vírgula seis".

Este módulo não usa IA. É ele que confere, em código, os números que a IA aponta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Quanto vale cada escala, em reais.
ESCALAS = {"": 1.0, "mil": 1e3, "milhões": 1e6, "bilhões": 1e9}

_TRACOS = {"-", "—", "–", "−"}

_NUMERO = re.compile(
    r"(?<![\w.,])"                       # não começa no meio de outra palavra ou número
    r"(?P<abre>\(\s*)?"                  # parêntese de abertura (negativo em tabela)
    r"(?P<menos>[-−–]\s*)?"              # sinal de menos
    r"(?P<rs>R\$\s*)?"                   # "R$" antes do número
    r"(?P<inteiro>\d{1,3}(?:\.\d{3})+|\d+)"  # 1.325.059 ou 2022
    r"(?:,(?P<decimal>\d+))?"            # ,30
    r"(?P<fecha>\s*\))?"                 # parêntese de fechamento
    r"(?:\s*(?P<sufixo>%|x(?![a-zà-ú])|bilh(?:ões|oes|ão|ao)|bi(?![a-zà-ú])"
    r"|milh(?:ões|oes|ão|ao)|mi(?![a-zà-ú])|mil(?![a-zà-ú])))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Numero:
    """Um número lido de um texto."""

    valor: float  # já com o sinal; percentual vira fração (19,30% -> 0,193)
    unidade: str  # "", "%", "x", "mil", "milhões" ou "bilhões"
    texto: str    # o pedaço exato que foi lido, por exemplo "(1.910.411)"


def _unidade(sufixo: str | None) -> str:
    if not sufixo:
        return ""
    s = sufixo.lower()
    if s == "%":
        return "%"
    if s == "x":
        return "x"
    if s.startswith("bi"):
        return "bilhões"
    if s.startswith("mi") and s != "mil":
        return "milhões"
    return "mil"


def _montar(m: re.Match) -> Numero:
    inteiro = m["inteiro"].replace(".", "")
    valor = float(f"{inteiro}.{m['decimal']}") if m["decimal"] else float(inteiro)
    unidade = _unidade(m["sufixo"])
    # Parênteses só são "menos" quando cercam um número puro, como numa tabela:
    # "(1.910.411)" é negativo, mas "(3,48x)" no meio de uma frase é só um aparte.
    entre_parenteses = bool(m["abre"]) and bool(m["fecha"]) and not unidade and not m["rs"]
    if m["menos"] or entre_parenteses:
        valor = -valor
    if unidade == "%":
        valor = valor / 100
    return Numero(valor=valor, unidade=unidade, texto=m.group(0).strip())


def achar_numeros(texto: str) -> list[Numero]:
    """Todos os números do texto, na ordem em que aparecem."""
    return [_montar(m) for m in _NUMERO.finditer(texto)]


def ler_numero(texto: str) -> Numero | None:
    """O primeiro número do texto. Um traço sozinho vale zero."""
    if texto.strip() in _TRACOS:
        return Numero(valor=0.0, unidade="", texto=texto.strip())
    m = _NUMERO.search(texto)
    return _montar(m) if m else None


def detectar_escala(texto_da_pagina: str) -> str:
    """A escala das tabelas da página: "mil", "milhões" ou "" se não achar.

    Procura o aviso do cabeçalho, como "(Em milhares de reais)".
    """
    t = texto_da_pagina.lower()
    if re.search(r"milhares de reais|em milhares|r\$\s*mil\b", t):
        return "mil"
    if re.search(r"milh(?:ões|oes) de reais|em milh(?:ões|oes)|r\$\s*milh", t):
        return "milhões"
    return ""


def em_reais(numero: Numero, escala_da_pagina: str = "") -> float:
    """Converte para reais.

    Usa a escala escrita junto do número ("R$1.817 milhões"). Se não houver,
    usa a escala da página ("Em milhares de reais").
    """
    if numero.unidade in ("%", "x"):
        raise ValueError(f"'{numero.texto}' não é um valor em dinheiro")
    escala = numero.unidade or escala_da_pagina
    return numero.valor * ESCALAS[escala]


def numero_aparece(valor: float, texto: str, tolerancia: float = 0.0) -> bool:
    """O número aparece no texto, com o mesmo sinal?

    É a conferência que impede a IA de "copiar" um número que não está no trecho.
    """
    return any(abs(n.valor - valor) <= tolerancia for n in achar_numeros(texto))
