"""As contas da solução. A IA nunca faz conta: toda conta é feita aqui, em Python.

Os resultados aparecem no relatório com o selo "calculado pela solução", sempre
separados do que o documento informa.
"""

from __future__ import annotations


def margem(ebitda: float, receita: float) -> float | None:
    """EBITDA ÷ receita, em fração (0,167 = 16,7%)."""
    if not receita:
        return None
    return ebitda / receita


def variacao(atual: float, anterior: float) -> float | None:
    """(atual − anterior) ÷ |anterior|, em fração.

    Devolve None quando a conta não tem sentido: base zero ou troca de sinal
    (por exemplo, de lucro para prejuízo). O relatório mostra "n/a" nesses casos.
    """
    if anterior == 0:
        return None
    if atual != 0 and (atual < 0) != (anterior < 0):
        return None
    return (atual - anterior) / abs(anterior)


def ebitda_calculado(ebit: float, depreciacao: float) -> float:
    """Método da CVM: lucro antes do resultado financeiro e dos impostos + depreciação e amortização.

    Use a depreciação da demonstração dos fluxos de caixa: a da DRE pode ser só uma
    parte, porque outra parte fica dentro do custo.
    """
    return ebit + depreciacao


def divida_liquida_calculada(
    divida_bruta: float, caixa: float, aplicacoes: float = 0.0, derivativos: float = 0.0
) -> float:
    """Empréstimos + debêntures (+ derivativos da dívida) − caixa − aplicações.

    Negativo quer dizer caixa líquido: a empresa tem mais caixa do que dívida.
    """
    return divida_bruta + derivativos - caixa - aplicacoes


def alavancagem(divida_liquida: float, ebitda: float) -> float | None:
    """Dívida líquida ÷ EBITDA. Com EBITDA zero ou negativo, o múltiplo não tem sentido."""
    if ebitda <= 0:
        return None
    return divida_liquida / ebitda
