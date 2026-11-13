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
    "ressalva": r"incerteza significativa|par[áa]grafo de [êe]nfase|base para opini[ãa]o com ressalva|opini[ãa]o adversa",
    "covenants": r"covenants?|vencimento antecipado|\brating|rebaixamento|descumprimento",
    "venda_de_ativos": r"mantidos? para venda|aliena[çc][ãa]o d[aoe] (?:participa|ativo|investimento|controlad)|desinvestimento",
    "reestruturacao": r"reestrutura[çc]",
    "mudanca_contabil": r"mudan[çc]as? (?:de|na|nas) (?:pol[íi]ticas?|pr[áa]ticas?|estimativas?) cont[áa]be?is|reapresenta[çc]",
}

# Análise qualitativa: prioridade de cada assunto (menor = mais importante).
PRIORIDADE = {
    # 1: o que muda a leitura do resultado
    "ressalva": 1, "eventos_subsequentes": 1, "contexto": 1, "aquisicao": 1, "venda_de_ativos": 1,
    "reestruturacao": 1, "segmento": 1,
    # 2: riscos e dívida
    "riscos": 2, "covenants": 2, "mudanca_contabil": 2,
    # 3: aparecem demais para pesar sozinhos: texto padrão do parecer, rótulo "(não auditado)" nas tabelas
    "contingencias": 3, "perspectivas": 3, "continuidade": 3, "nao_auditado": 3,
}
# Orçamento do analista, em caracteres por documento (uns 50 a 70 mil tokens).
# Documento pequeno vai quase inteiro; documento grande vai pelas prioridades.
LIMITE_ANALISE = 90_000

DEMONSTRACOES = {"dre", "balanco", "dfc", "dmpl"}
TABELAS = DEMONSTRACOES | {"abrangente", "dva"}  # o analista não lê tabelas: os números vêm da extração


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
    rotas.analise = _paginas_da_analise(documento, rotas)
    return rotas


def prioridade_na_analise(tipo: str, assuntos: set[str]) -> int | None:
    """0 = relatório da administração; 1 a 3 = pelos assuntos; 4 = outras notas; None = fica de fora."""
    if tipo in TABELAS:
        return None
    if tipo == "relatorio_adm":
        return 0
    niveis = [PRIORIDADE[a] for a in assuntos if a in PRIORIDADE]
    if tipo == "auditor":
        niveis.append(1)  # o parecer: opinião, ênfase, ressalva
    if niveis:
        return min(niveis)
    return 4 if tipo in {"notas", "outros"} else None


def _paginas_da_analise(documento: Documento, rotas: Rotas) -> list[int]:
    """Analista: o texto da administração e, por prioridade, as notas que mudam a leitura do resultado.

    As demonstrações (tabelas) ficam de fora: os números já vêm da extração.
    Na mesma prioridade, vem antes a página que fala mais dos assuntos importantes
    (uma menção de passagem pesa menos que a nota inteira sobre o assunto).
    Para no orçamento de caracteres, para o custo não crescer com o tamanho do PDF.
    """
    candidatas = []
    for n, tipo in rotas.tipos.items():
        nivel = prioridade_na_analise(tipo, rotas.assuntos[n])
        if nivel is not None and documento.pagina(n).linhas:  # página escaneada, sem texto, não vai
            texto = documento.pagina(n).texto.lower()
            peso = sum(min(len(re.findall(ASSUNTOS[a], texto)), 5)
                       for a in rotas.assuntos[n] if PRIORIDADE.get(a, 9) <= 2)
            candidatas.append((nivel, -peso, n))
    escolhidas, total = [], 0
    for _, _, n in sorted(candidatas):
        tamanho = len(documento.pagina(n).texto)
        if total + tamanho > LIMITE_ANALISE:
            continue
        escolhidas.append(n)
        total += tamanho
    return sorted(escolhidas)
