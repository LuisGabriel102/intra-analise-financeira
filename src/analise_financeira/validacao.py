"""Regras de conferência. O validador nunca corrige um número: ele só sinaliza.

Cada regra é uma função pura: recebe números e devolve um Alerta, ou None
quando está tudo certo. Não usa IA. Os valores em dinheiro chegam em reais
(veja numeros.em_reais), para não misturar mil com milhões.

Cada armadilha encontrada nos PDFs do desafio virou um teste em
tests/test_validacao.py. Nenhuma regra é específica de uma empresa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from analise_financeira.numeros import ESCALAS


@dataclass(frozen=True)
class Alerta:
    regra: str       # por exemplo "V7"
    severidade: str  # "erro" (a conta não fecha), "aviso" (atenção) ou "info" (diferença pequena)
    mensagem: str
    valores: dict = field(default_factory=dict)


# ----------------------------------------------------------------- formatação


def _num(v: float, casas: int = 0) -> str:
    """1234567.8 -> '1.234.568' (padrão brasileiro)."""
    s = f"{abs(v):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-{s}" if v < 0 else s


def _mi(reais: float) -> str:
    return f"R$ {_num(reais / 1e6, 1)} mi"


def _pct(fracao: float) -> str:
    return f"{_num(fracao * 100, 1)}%"


def _perto(a: float, b: float, tol_rel: float) -> bool:
    return abs(a - b) <= tol_rel * max(abs(a), abs(b))


# ----------------------------------------------------------------- regras


def conferir_margem(margem_informada: float, ebitda: float, receita: float, tol_pp: float = 0.2) -> Alerta | None:
    """V3. A margem informada bate com EBITDA ÷ receita? Margens em fração (0,167 = 16,7%)."""
    if not receita:
        return Alerta("V3", "aviso", "Receita zero: a margem informada não pode ser conferida.",
                      {"informada": margem_informada})
    calculada = ebitda / receita
    if abs(calculada - margem_informada) * 100 <= tol_pp:
        return None
    return Alerta("V3", "erro",
                  f"Margem informada de {_pct(margem_informada)} não bate com EBITDA ÷ receita = {_pct(calculada)}.",
                  {"informada": margem_informada, "calculada": calculada})


def conferir_variacao_percentual(variacao_informada: float, atual: float, anterior: float,
                                 tol_pp: float = 0.5) -> Alerta | None:
    """V4. A variação em % informada bate com os valores dos dois períodos?"""
    if anterior == 0 or (atual != 0 and (atual < 0) != (anterior < 0)):
        return Alerta("V4", "aviso", "Variação percentual sem sentido: base zero ou troca de sinal entre os períodos.",
                      {"informada": variacao_informada, "atual": atual, "anterior": anterior})
    calculada = (atual - anterior) / abs(anterior)
    if abs(calculada - variacao_informada) * 100 <= tol_pp:
        return None
    return Alerta("V4", "erro",
                  f"Variação informada de {_pct(variacao_informada)} não bate com a calculada, de {_pct(calculada)}.",
                  {"informada": variacao_informada, "calculada": calculada})


def conferir_variacao_absoluta(variacao_informada: float, atual: float, anterior: float,
                               tol: float = 0.01) -> Alerta | None:
    """V5. A variação em dinheiro ("redução de R$ 3.001 milhões") bate com atual − anterior?

    A variação chega com o sinal da frase: "redução de 3.001" vira -3.001.
    Quando não bate, testa uma hipótese: o valor atual perdeu o sinal de menos no texto.
    """
    real = atual - anterior
    if _perto(real, variacao_informada, tol):
        return None
    valores = {"informada": variacao_informada, "atual": atual, "anterior": anterior}
    if _perto(-atual - anterior, variacao_informada, tol):
        return Alerta("V5", "erro",
                      f"A variação informada ({_mi(variacao_informada)}) só fecha se o valor atual for "
                      f"{_mi(-atual)}, e não {_mi(atual)}. Provável sinal de menos perdido no texto.", valores)
    return Alerta("V5", "erro",
                  f"A variação informada ({_mi(variacao_informada)}) não bate com atual − anterior ({_mi(real)}).",
                  valores)


_SOBE = re.compile(r"\b(aumento|alta|cresc\w*|acima|maior|superior|avan[çc]o|expans[ãa]o)\b", re.I)
_DESCE = re.compile(r"\b(redu[çc][ãa]o|queda|diminui\w*|recuo|retra[çc][ãa]o|abaixo|menor|inferior)\b", re.I)


def direcao_da_frase(frase: str) -> int:
    """+1 se a frase diz que subiu, -1 se diz que caiu, 0 se não dá para saber."""
    sobe, desce = bool(_SOBE.search(frase)), bool(_DESCE.search(frase))
    if sobe == desce:
        return 0
    return 1 if sobe else -1


def conferir_direcao(frase: str, atual: float, anterior: float) -> Alerta | None:
    """V6. A frase da variação ("15,5% acima") aponta para o mesmo lado que os números?

    Recebe só a frase da variação, e não a página inteira: palavras como "alta"
    (de "alta tensão") confundiriam a regra num texto longo.
    """
    texto = direcao_da_frase(frase)
    real = (atual > anterior) - (atual < anterior)
    if texto == 0 or real == 0 or texto == real:
        return None
    lado = {1: "subiu", -1: "caiu"}
    return Alerta("V6", "erro",
                  f"O texto diz que {lado[texto]}, mas os números mostram que {lado[real]} "
                  f"(de {_num(anterior)} para {_num(atual)}).",
                  {"frase": frase, "atual": atual, "anterior": anterior})


def conferir_ebitda(informado: float, ebit: float, depreciacao: float, tol: float = 0.01) -> Alerta | None:
    """V7. O EBITDA informado bate com EBIT + depreciação (DRE + fluxo de caixa)?"""
    calculado = ebit + depreciacao
    valores = {"informado": informado, "calculado": calculado}
    if _perto(informado, calculado, tol):
        return None
    if _perto(-informado, calculado, tol):
        return Alerta("V7", "erro",
                      f"EBITDA informado de {_mi(informado)}, mas EBIT + depreciação dá {_mi(calculado)}: "
                      f"o mesmo valor com o sinal trocado. Provável sinal de menos perdido no texto.", valores)
    return Alerta("V7", "aviso",
                  f"EBITDA informado ({_mi(informado)}) diferente de EBIT + depreciação ({_mi(calculado)}). "
                  f"Pode ser outra definição, como o EBITDA ajustado.", valores)


def conferir_divida_liquida(informada: float, divida_bruta: float, caixa: float, aplicacoes: float = 0.0,
                            derivativos: float = 0.0, tol: float = 0.01) -> Alerta | None:
    """V8. A dívida líquida informada bate com dívida − caixa − aplicações (+ derivativos)?"""
    calculada = divida_bruta + derivativos - caixa - aplicacoes
    if _perto(informada, calculada, tol):
        return None
    return Alerta("V8", "aviso",
                  f"Dívida líquida informada ({_mi(informada)}) diferente da calculada ({_mi(calculada)}). "
                  f"Confira quais itens a empresa inclui.",
                  {"informada": informada, "calculada": calculada})


def conferir_alavancagem(informada: float, divida_liquida: float, ebitda: float, tol: float = 0.1) -> Alerta | None:
    """V9. A alavancagem informada bate com dívida líquida ÷ EBITDA?"""
    valores = {"informada": informada, "divida_liquida": divida_liquida, "ebitda": ebitda}
    multiplo = f"{_num(informada, 2)}x"
    if ebitda <= 0:
        return Alerta("V9", "aviso",
                      f"Com EBITDA de {_mi(ebitda)}, dívida líquida ÷ EBITDA não tem sentido. "
                      f"O múltiplo informado ({multiplo}) usa outra definição de EBITDA.", valores)
    calculada = divida_liquida / ebitda
    if abs(calculada - informada) <= tol:
        return None
    return Alerta("V9", "aviso",
                  f"Alavancagem informada ({multiplo}) diferente da calculada ({_num(calculada, 2)}x). "
                  f"Confira a definição de EBITDA usada.", valores | {"calculada": calculada})


def conferir_escala(valor_texto: float, unidade_texto: str, valor_tabela_reais: float,
                    tol: float = 0.001) -> Alerta | None:
    """V10. O mesmo valor escrito no texto (ex.: R$ milhões) e na tabela (ex.: R$ mil) bate?

    Uma diferença menor que meia unidade do texto é arredondamento e não gera alerta.
    """
    texto_reais = valor_texto * ESCALAS[unidade_texto]
    diferenca = abs(texto_reais - valor_tabela_reais)
    if diferenca <= ESCALAS[unidade_texto] / 2:
        return None
    valores = {"texto": texto_reais, "tabela": valor_tabela_reais}
    if diferenca <= tol * abs(valor_tabela_reais):
        return Alerta("V10", "info",
                      f"Diferença pequena: {_mi(texto_reais)} no texto e {_mi(valor_tabela_reais)} na tabela. "
                      f"É maior do que o arredondamento explica.", valores)
    razao = abs(texto_reais / valor_tabela_reais) if valor_tabela_reais else 0.0
    dica = " Parece erro de escala (mil × milhões)." if _perto(razao, 1000, 0.01) or _perto(razao, 0.001, 0.01) else ""
    return Alerta("V10", "erro",
                  f"O texto diz {_mi(texto_reais)}, mas a tabela diz {_mi(valor_tabela_reais)}.{dica}", valores)


_ANO = re.compile(r"\b(?:19|20)\d{2}\b")


def conferir_ano_no_texto(frase: str, texto_do_valor: str, periodo: str) -> Alerta | None:
    """V11. O ano escrito logo antes do valor é o ano do período?

    Exemplo: "encerrou 2021 em 3,32x" num valor de 2022.
    """
    pos = frase.find(texto_do_valor)
    if pos < 0:
        return None
    anos = _ANO.findall(frase[max(0, pos - 20):pos])
    if not anos or anos[-1] == periodo:
        return None
    return Alerta("V11", "aviso",
                  f"O texto liga o valor {texto_do_valor} ao ano {anos[-1]}, mas o período é {periodo}. "
                  f"Provável ano errado no texto.", {"frase": frase})


def _um_digito_e_zeros(diferenca: float) -> bool:
    s = str(int(round(abs(diferenca))))
    return len(s) >= 3 and s[0] != "0" and set(s[1:]) == {"0"}


def conferir_soma(partes: list[float], total: float, tol: float = 1.0) -> Alerta | None:
    """V12. A soma das linhas bate com o total informado?"""
    soma = sum(partes)
    diferenca = total - soma
    if abs(diferenca) <= tol:
        return None
    dica = " A diferença é um dígito seguido de zeros: provável dígito faltando ou sobrando." \
        if _um_digito_e_zeros(diferenca) else ""
    return Alerta("V12", "erro", f"A soma das linhas dá {_num(soma)}, mas o total informado é {_num(total)}.{dica}",
                  {"soma": soma, "total": total})


def conferir_ocorrencias(nome: str, ocorrencias: list[tuple[float, str]], tol: float = 1.0,
                         tol_info: float = 0.001) -> Alerta | None:
    """V13. O mesmo número aparece em lugares diferentes (DRE, DMPL, notas). Todos batem?

    Diferença de até 0,1% vira "info" (provável arredondamento); acima disso, "erro".
    """
    if len(ocorrencias) < 2:
        return None
    valores = [v for v, _ in ocorrencias]
    diferenca = max(valores) - min(valores)
    if diferenca <= tol:
        return None
    base = max(abs(v) for v in valores)
    severidade = "info" if diferenca <= tol_info * base else "erro"
    lista = "; ".join(f"{_num(v)} ({onde})" for v, onde in ocorrencias)
    return Alerta("V13", severidade, f"{nome}: valores diferentes no mesmo documento: {lista}.",
                  {"ocorrencias": ocorrencias})


_NAO_AUDITADO = re.compile(r"n[ãa]o\s+(?:foram\s+|foi\s+|ser[ãa]o\s+)?(?:auditad|revisad)", re.I)


def conferir_auditoria(texto: str, pagina: int) -> Alerta | None:
    """V14. O documento avisa que algum período não foi auditado?"""
    if not _NAO_AUDITADO.search(texto):
        return None
    return Alerta("V14", "aviso",
                  f"O documento avisa que parte dos números não foi auditada (p. {pagina}). "
                  f"Variações contra esse período usam números não auditados.", {"pagina": pagina})


_MESES = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
          "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}


def ler_data(texto: str) -> date | None:
    """'14 de março de 2022' ou '15/05/2023' -> date."""
    m = re.search(r"(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})", texto, re.I)
    if m and m[2].lower() in _MESES:
        return date(int(m[3]), _MESES[m[2].lower()], int(m[1]))
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", texto)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    return None


def conferir_datas(data_aprovacao: date, fim_do_exercicio: date, data_parecer: date | None = None) -> Alerta | None:
    """V15. A data de aprovação das demonstrações faz sentido?"""
    if data_aprovacao <= fim_do_exercicio:
        return Alerta("V15", "aviso",
                      f"Aprovação em {data_aprovacao:%d/%m/%Y}, antes do fim do exercício "
                      f"({fim_do_exercicio:%d/%m/%Y}). Provável ano errado.",
                      {"aprovacao": str(data_aprovacao), "parecer": str(data_parecer)})
    if data_parecer and abs((data_parecer - data_aprovacao).days) > 120:
        return Alerta("V15", "aviso",
                      f"Aprovação em {data_aprovacao:%d/%m/%Y} e parecer do auditor em {data_parecer:%d/%m/%Y}: "
                      f"datas muito distantes.", {"aprovacao": str(data_aprovacao), "parecer": str(data_parecer)})
    return None


def conferir_anos_do_cabecalho(cabecalho: str, periodo: str, anterior: str) -> Alerta | None:
    """V16. O cabeçalho da tabela traz os anos certos? Pega ano repetido e ano malformado."""
    malformados = re.findall(r"\b20\d{3,}\b", cabecalho)
    if malformados:
        return Alerta("V16", "aviso", f"Cabeçalho com ano malformado ({', '.join(malformados)}): '{cabecalho}'.",
                      {"cabecalho": cabecalho})
    anos = _ANO.findall(cabecalho)
    if anos and anos.count(periodo) < anos.count(anterior):
        return Alerta("V16", "aviso",
                      f"Cabeçalho com {anterior} repetido no lugar de {periodo}: '{cabecalho}'. "
                      f"Confira de qual ano é cada coluna.", {"cabecalho": cabecalho})
    return None
