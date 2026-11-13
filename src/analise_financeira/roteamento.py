"""Roteamento: acha em que página está cada coisa, antes de chamar a IA.

Mandar o PDF inteiro custa mais e dilui a atenção do modelo (a Light tem 124
páginas). Aqui, regras simples por palavra-chave escolhem as páginas:

- o tipo da página vem do título, nas primeiras linhas (DRE, balanço, fluxo de caixa...);
- os assuntos vêm do texto todo (dívida líquida, riscos, continuidade...).

Nenhuma regra é feita para uma empresa específica.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from analise_financeira.numeros import achar_numeros
from analise_financeira.pdf import Documento, Pagina

# Tipo da página, pelo título. A ordem importa: a primeira que bater vence.
TITULOS = [
    ("auditor", r"relat[óo]rio d[oa]s? auditor"),
    ("dmpl", r"muta[çc]\w+ d[oe]s? patrim[ôo]nio"),
    ("abrangente", r"resultados? abrangentes?"),
    ("dfc", r"fluxos? de caixa"),
    ("dva", r"valor adicionado"),
    ("balanco", r"balan[çc]os? patrimonia"),
    ("dre", r"demonstra[çc]\w+ d[oe]s? resultados?"),
    ("relatorio_adm", r"relat[óo]rio da administra|mensagem da administra"),
    ("notas", r"notas explicativas"),
]

# Assuntos, procurados no texto inteiro da página.
ASSUNTOS = {
    "divida_liquida": r"d[íi]vida l[íi]quida",
    "gestao_capital": r"gest[ãa]o d[oe] capital",
    "ebitda": r"\bebitda\b",
    "segmento": r"por segmento|informa[çc]\w+ por segmentos?",
    "continuidade": r"continuidade operacional",
    "eventos_subsequentes": r"eventos? subsequentes?",
    "riscos": r"gest[ãa]o de riscos?|riscos? de (?:cr[ée]dito|liquidez|mercado)|fatores de risco",
    "contingencias": r"conting[êe]ncias|processos judiciais",
    "aquisicao": r"combina[çc][ãa]o de neg[óo]cios|aquisi[çc][ãa]o d[aoe] (?:controlad|empresa|participa)",
    "contexto": r"contexto operacional",
    "nao_auditado": r"n[ãa]o (?:foram |foi )?auditad",
    "perspectivas": r"perspectivas?|guidance|pr[óo]ximos? (?:anos?|exerc[íi]cios?)",
}

DEMONSTRACOES = {"dre", "balanco", "dfc", "dmpl"}


@dataclass
class Rotas:
    tipos: dict[int, str] = field(default_factory=dict)        # página -> tipo
    assuntos: dict[int, set[str]] = field(default_factory=dict)  # página -> assuntos
    extracao: list[int] = field(default_factory=list)           # páginas para o extrator
    analise: list[int] = field(default_factory=list)            # páginas para o analista

    def paginas_do_tipo(self, tipo: str) -> list[int]:
        return [p for p, t in self.tipos.items() if t == tipo]


def _linhas_com_numeros(pagina: Pagina) -> int:
    return sum(1 for linha in pagina.linhas if len(achar_numeros(linha)) >= 2)


def tipo_da_pagina(pagina: Pagina) -> str:
    """O tipo da página pelo título. Título é linha curta, no topo."""
    titulos = [linha for linha in pagina.linhas[:10] if len(linha) <= 90]
    cabecalho = "\n".join(titulos).lower()
    for tipo, padrao in TITULOS:
        if re.search(padrao, cabecalho):
            # Uma demonstração de verdade abre com a escala ("Em milhares de reais")
            # e é uma tabela, com várias linhas de números. Isso separa a DRE da
            # empresa de uma tabelinha com o mesmo título dentro de uma nota.
            if tipo in DEMONSTRACOES and (not pagina.escala or _linhas_com_numeros(pagina) < 5):
                continue
            return tipo
    return "outros"


def assuntos_da_pagina(pagina: Pagina) -> set[str]:
    texto = pagina.texto.lower()
    return {nome for nome, padrao in ASSUNTOS.items() if re.search(padrao, texto)}


def rotear(documento: Documento) -> Rotas:
    rotas = Rotas()
    for pagina in documento.paginas:
        if pagina.vazia:
            continue
        n = pagina.numero
        rotas.tipos[n] = tipo_da_pagina(pagina)
        rotas.assuntos[n] = assuntos_da_pagina(pagina)

    for n, tipo in rotas.tipos.items():
        assuntos = rotas.assuntos[n]
        # Extrator: as demonstrações, o texto da administração com números,
        # e as notas que trazem dívida líquida, EBITDA ou segmentos.
        if tipo in DEMONSTRACOES:
            rotas.extracao.append(n)
        elif tipo == "relatorio_adm" and assuntos & {"ebitda", "divida_liquida"}:
            rotas.extracao.append(n)
        elif tipo in {"notas", "outros"} and assuntos & {"divida_liquida", "gestao_capital", "ebitda"}:
            rotas.extracao.append(n)  # páginas de nota sem cabeçalho caem em "outros"
        # Analista: o texto da administração, o auditor e as notas de contexto e risco.
        if tipo in {"relatorio_adm", "auditor"}:
            rotas.analise.append(n)
        elif assuntos & {"continuidade", "eventos_subsequentes", "riscos", "contingencias",
                         "aquisicao", "contexto", "segmento", "perspectivas"}:
            rotas.analise.append(n)
    return rotas
