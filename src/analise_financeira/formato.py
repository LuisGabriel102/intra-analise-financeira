"""Números no formato brasileiro, para o texto que a IA lê e para o relatório."""

from __future__ import annotations


def numero_br(valor: float, casas: int = 1) -> str:
    """13253286.0 -> '13.253.286,0'. O sinal de menos fica na frente."""
    texto = f"{abs(valor):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-{texto}" if valor < 0 and texto.strip("0,.") else texto


def milhoes(valor_reais: float) -> str:
    """Em reais -> 'R$ 13.253,3 milhões' ou '-R$ 5.672,2 milhões'."""
    texto = numero_br(valor_reais / 1e6)
    return f"-R$ {texto[1:]} milhões" if texto.startswith("-") else f"R$ {texto} milhões"


def percentual(fracao: float, casas: int = 1, sinal: bool = True) -> str:
    """-0.11 -> '-11,0%'; com sinal=True, 0.248 -> '+24,8%'."""
    texto = numero_br(fracao * 100, casas)
    return f"+{texto}%" if sinal and fracao > 0 and not texto.startswith("-") else f"{texto}%"


def multiplo(valor: float) -> str:
    """3.32 -> '3,32x'."""
    return f"{numero_br(valor, 2)}x"
