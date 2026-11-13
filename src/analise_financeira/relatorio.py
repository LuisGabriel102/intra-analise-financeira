"""Redator do relatório: monta o Markdown em código, a partir dos JSONs conferidos.

A IA não escreve o relatório. Tabelas, números, resumo executivo e alertas saem
direto dos dados; o texto da IA só entra onde ela já trabalhou com citação (análise
qualitativa e respostas às perguntas), sempre com a página ao lado.

Todo texto que veio do PDF ou da IA passa por um escape: "<" e ">" viram entidades
(nada de HTML injetado no relatório) e, dentro das tabelas, "|" não quebra a coluna.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from analise_financeira.esquemas import AnaliseQualitativa, Extracao, Item, RespostaPergunta
from analise_financeira.formato import milhoes, multiplo, numero_br, percentual
from analise_financeira.indicadores import AlertaSaida, Dado, DocumentoAnalisado, Indicador
from analise_financeira.numeros import ESCALAS, achar_numeros

INFORMADO, CALCULADO, ALERTA, NAO_ENCONTRADO = "✅", "🧮", "⚠️", "⛔"
TOM = {"positivo": "positivo", "neutro": "neutro", "negativo": "negativo", "nao_aplicavel": "não aplicável"}
FONTE = {"relatorio_adm": "relatório da administração", "notas": "notas explicativas", "outros": "notas explicativas",
         "auditor": "parecer do auditor"}


@dataclass
class ResultadoDocumento:
    arquivo: str                      # "Light.pdf"
    extracao: Extracao
    numeros: DocumentoAnalisado
    qualitativa: AnaliseQualitativa | None = None

    @property
    def chave(self) -> str:
        return self.arquivo.removesuffix(".pdf")

    @property
    def nome(self) -> str:
        return self.numeros.empresa or self.chave


# ------------------------------------------------------------------ escape e formato


def texto(t: str) -> str:
    """Texto do PDF ou da IA, seguro para Markdown: sem HTML."""
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def celula(t: str) -> str:
    """Texto seguro dentro de uma célula de tabela: sem HTML, sem quebra de linha e sem '|' solto."""
    return texto(t).replace("\n", " ").replace("|", "\\|")


def _paginas(numeros: list[int]) -> str:
    """[3, 6, 7, 8, 11] -> 'p. 3, 6–8, 11'."""
    numeros = sorted(set(numeros))
    if not numeros:
        return ""
    faixas, inicio, fim = [], numeros[0], numeros[0]
    for n in numeros[1:]:
        if n == fim + 1:
            fim = n
            continue
        faixas.append((inicio, fim))
        inicio = fim = n
    faixas.append((inicio, fim))
    return "p. " + ", ".join(str(a) if a == b else f"{a}–{b}" if b > a + 1 else f"{a}, {b}" for a, b in faixas)


def _minuscula(frase: str) -> str:
    """'Um risco' -> 'um risco'; 'PIS e COFINS' fica igual."""
    return frase[0].lower() + frase[1:] if len(frase) > 1 and frase[1].islower() else frase


def _paginas_do_dado(d: Dado | None) -> list[int]:
    return [e.pagina for e in d.fontes] if d else []


def _valor(d: Dado) -> str:
    """O valor na unidade da tabela: R$ milhões, % ou x."""
    if d.unidade == "%" and d.numero is not None:
        return percentual(d.numero, sinal=False)
    if d.unidade == "x" and d.numero is not None:
        return multiplo(d.numero)
    if d.valor_reais is not None:
        return numero_br(d.valor_reais / 1e6)
    return d.texto


def _alertas_do(n: DocumentoAnalisado, campo: str) -> list[AlertaSaida]:
    return [a for a in n.alertas if a.campo == campo and a.severidade in ("erro", "aviso")]


# ------------------------------------------------------------------ células da tabela


def _informado(n: DocumentoAnalisado, campo: str, quando: str = "atual") -> str:
    ind: Indicador = getattr(n, campo)
    d = ind.atual if quando == "atual" else ind.anterior
    if d is None:
        return f"{NAO_ENCONTRADO} não encontrado"
    marca = ALERTA if quando == "atual" and _alertas_do(n, campo) else INFORMADO
    pags = _paginas(_paginas_do_dado(d))
    return f"{marca} {_valor(d)}" + (f" ({pags})" if pags else "")


def _calculado(n: DocumentoAnalisado, campo: str, quando: str = "atual") -> str:
    ind: Indicador = getattr(n, campo)
    d = ind.calculado if quando == "atual" else ind.calculado_anterior
    if d is None:
        obs = (ind.observacao or "").lower() if quando == "atual" else ""
        if "caixa líquido" in obs:
            return "n/a (caixa líquido)"
        if "negativo" in obs:
            return "n/a (EBITDA negativo)"
        return "—"
    return f"{CALCULADO} {_valor(d)}"


def _variacao(n: DocumentoAnalisado, campo: str) -> str:
    ind: Indicador = getattr(n, campo)
    if ind.variacao is not None:
        return f"{CALCULADO} {percentual(ind.variacao)}"
    if ind.atual and ind.anterior:
        return "n/a (troca de sinal)"
    return "—"


LINHAS = [
    ("Receita líquida, período atual", lambda n: _informado(n, "receita_liquida")),
    ("Receita líquida, período anterior", lambda n: _informado(n, "receita_liquida", "anterior")),
    ("Variação da receita", lambda n: _variacao(n, "receita_liquida")),
    ("EBITDA informado", lambda n: _informado(n, "ebitda")),
    ("EBITDA calculado (EBIT + D&A)", lambda n: _calculado(n, "ebitda")),
    ("Margem EBITDA informada", lambda n: _informado(n, "margem_ebitda")),
    ("Margem EBITDA calculada", lambda n: _calculado(n, "margem_ebitda")),
    ("Lucro líquido, período atual", lambda n: _informado(n, "lucro_liquido")),
    ("Lucro líquido, período anterior", lambda n: _informado(n, "lucro_liquido", "anterior")),
    ("Variação do lucro líquido", lambda n: _variacao(n, "lucro_liquido")),
    ("Lucro dos controladores", lambda n: _informado(n, "lucro_controladores")),
    ("Dívida líquida informada", lambda n: _informado(n, "divida_liquida")),
    ("Dívida líquida calculada", lambda n: _calculado(n, "divida_liquida")),
    ("Alavancagem informada", lambda n: _informado(n, "alavancagem")),
    ("Alavancagem calculada", lambda n: _calculado(n, "alavancagem")),
    ("Fluxo de caixa operacional", lambda n: _informado(n, "fluxo_caixa_operacional")),
    ("Capex informado", lambda n: _informado(n, "capex")),
    ("Capex calculado (DFC)", lambda n: _calculado(n, "capex")),
]


def tabela(resultados: list[ResultadoDocumento]) -> list[str]:
    md = ["| Indicador | " + " | ".join(celula(r.chave) for r in resultados) + " |",
          "|---" * (len(resultados) + 1) + "|"]
    for rotulo, funcao in LINHAS:
        md.append(f"| {rotulo} | " + " | ".join(funcao(r.numeros) for r in resultados) + " |")
    return md


# ------------------------------------------------------------------ resumo executivo


def _frase_valor(rotulo: str, ind: Indicador) -> str | None:
    if not ind.atual or ind.atual.valor_reais is None:
        return None
    atual, pags = ind.atual.valor_reais, _paginas(_paginas_do_dado(ind.atual))
    frase = f"{rotulo} de {milhoes(atual)}"
    if ind.variacao is not None:
        frase += f", {percentual(ind.variacao)} contra o período anterior"
    elif ind.anterior and ind.anterior.valor_reais is not None:
        frase += f", contra {milhoes(ind.anterior.valor_reais)} no período anterior"
    return frase + (f" ({pags})." if pags else ".")


def _frase_lucro(n: DocumentoAnalisado) -> str:
    lucro = n.lucro_liquido
    if not lucro.atual or lucro.atual.valor_reais is None:
        return "Lucro líquido não encontrado."
    atual = lucro.atual.valor_reais
    pags = _paginas(_paginas_do_dado(lucro.atual))
    frase = f"{'Prejuízo' if atual < 0 else 'Lucro'} líquido de {milhoes(abs(atual))}"
    if lucro.variacao is not None:
        frase += f", {percentual(lucro.variacao)} contra o período anterior"
    elif lucro.anterior and lucro.anterior.valor_reais is not None:
        ant = lucro.anterior.valor_reais
        frase += f", contra {'prejuízo' if ant < 0 else 'lucro'} de {milhoes(abs(ant))} no período anterior"
    controladores = n.lucro_controladores.atual
    if controladores and controladores.valor_reais is not None and controladores.valor_reais != atual:
        frase += f"; dos controladores, {milhoes(controladores.valor_reais)}"
    return frase + (f" ({pags})." if pags else ".")


def resumo_executivo(r: ResultadoDocumento) -> list[str]:
    """Até 5 linhas, montadas em código a partir dos dados conferidos."""
    n, q = r.numeros, r.qualitativa
    linhas = [_frase_valor("Receita líquida", n.receita_liquida) or "Receita líquida não encontrada.",
              _frase_lucro(n)]

    e, m = n.ebitda, n.margem_ebitda
    if e.atual and e.atual.valor_reais is not None:
        frase = f"EBITDA informado de {milhoes(e.atual.valor_reais)}" + (f" ({e.definicao})" if e.definicao else "")
        erros = [a for a in _alertas_do(n, "ebitda") if a.severidade == "erro"]
        if erros and e.calculado and e.calculado.valor_reais is not None:
            frase += (f". {ALERTA} A conferência ({erros[0].regra}) aponta erro: pelas demonstrações, o EBITDA é "
                      f"{milhoes(e.calculado.valor_reais)}")
        linhas.append(frase + ".")
    elif e.calculado and e.calculado.valor_reais is not None:
        frase = f"EBITDA não informado. Calculado pela solução: {milhoes(e.calculado.valor_reais)}"
        if m.calculado and m.calculado.numero is not None:
            frase += f", margem de {percentual(m.calculado.numero, sinal=False)}"
        linhas.append(frase + ".")

    d, a = n.divida_liquida, n.alavancagem
    if d.atual and d.atual.valor_reais is not None:
        frase = f"Dívida líquida informada de {milhoes(d.atual.valor_reais)}"
        if a.atual and a.atual.numero is not None:
            frase += f"; alavancagem informada de {multiplo(a.atual.numero)}"
            if _alertas_do(n, "alavancagem"):
                frase += f" ({ALERTA} ver alertas)"
        elif a.calculado and a.calculado.numero is not None:
            frase += f"; alavancagem calculada pela solução de {multiplo(a.calculado.numero)}"
        linhas.append(frase + ".")
    elif d.calculado and d.calculado.valor_reais is not None:
        if d.calculado.valor_reais < 0:
            linhas.append(f"Caixa líquido: a dívida líquida calculada pela solução é {milhoes(d.calculado.valor_reais)}.")
        else:
            frase = f"Dívida líquida não informada. Calculada pela solução: {milhoes(d.calculado.valor_reais)}"
            if a.calculado and a.calculado.numero is not None:
                frase += f"; alavancagem calculada de {multiplo(a.calculado.numero)}"
            linhas.append(frase + ".")

    if q is not None:
        frase = f"Tom da administração: {TOM.get(q.tom, 'sem resposta')}"
        if not q.tem_relatorio_administracao:
            frase += " (o documento não tem relatório da administração)"
        # O ponto que o parecer do auditor também sustenta vem primeiro (incerteza, ano não auditado...).
        candidatos = [*q.comparabilidade, *q.riscos]
        destaque = next((i for i in candidatos if "auditor" in i.fontes), None) or next(iter(candidatos), None)
        if destaque is not None:
            onde = _paginas([e.pagina for e in destaque.evidencias]) or "sem trecho citado"
            frase += f". Atenção: {texto(_minuscula(_primeira_frase(destaque.texto)))} ({onde})"
        linhas.append(frase + ".")
    return linhas[:5]


def _primeira_frase(t: str) -> str:
    """Até o primeiro ':', ';' ou '.' seguido de maiúscula: 'O ano não foi auditado: As...' -> 'O ano não foi auditado'."""
    m = re.search(r"[:.;](?=\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ(])", t)
    return (t[:m.start()] if m else t).rstrip(" .")


# ------------------------------------------------------------------ análise qualitativa


Suspeito = tuple[float | None, float | None, str]  # (valor em reais, número como escrito, regra)


def valores_com_erro(n: DocumentoAnalisado) -> list[Suspeito]:
    """Os valores informados que a conferência em código marcou com erro (ex.: EBITDA da Light, V7)."""
    saida = []
    for a in n.alertas:
        if a.origem != "codigo" or a.severidade != "erro" or not a.campo or not hasattr(n, a.campo):
            continue
        ind: Indicador = getattr(n, a.campo)
        for d in (ind.atual, ind.anterior):
            if d is not None:
                lidos = achar_numeros(d.texto)
                saida.append((d.valor_reais, abs(lidos[0].valor) if lidos else None, a.regra))
    return saida


def _cita_valor_com_erro(i: Item, suspeitos: list[Suspeito]) -> str | None:
    for n in achar_numeros(i.texto):
        if n.unidade in ("%", "x"):
            continue
        reais = n.valor * ESCALAS[n.unidade] if n.unidade else None
        for valor_reais, escrito, regra in suspeitos:
            if reais is not None and valor_reais and abs(abs(reais) - abs(valor_reais)) <= 0.001 * abs(valor_reais):
                return regra
            if not n.unidade and escrito is not None and abs(n.valor) == escrito and escrito >= 1000:
                return regra
    return None


def _item(i: Item, suspeitos: list[Suspeito] | None = None) -> str:
    tipos = ", ".join(FONTE.get(f, f) for f in i.fontes)
    onde = f"{tipos}, {_paginas([e.pagina for e in i.evidencias])}" if i.evidencias else ""
    linha = f"- {texto(i.texto)}" + (f" ({onde})" if onde else "")
    if not i.conferido:
        linha += f" {ALERTA} sem trecho citado"
    if i.numeros_sem_fonte:
        linha += f" {ALERTA} número sem fonte conferida: {', '.join(texto(x) for x in i.numeros_sem_fonte)}"
    regra = _cita_valor_com_erro(i, suspeitos or [])
    if regra:
        linha += f" {ALERTA} cita um valor que a conferência marcou com erro ({regra}; ver a seção 5)"
    return linha


def qualitativa(r: ResultadoDocumento) -> list[str]:
    q = r.qualitativa
    if q is None:
        return ["Análise qualitativa não executada."]
    adm = f"sim ({_paginas(q.paginas_administracao)})" if q.paginas_administracao else (
        "sim" if q.tem_relatorio_administracao else "não; só demonstrações, notas e parecer")
    md = [f"{ALERTA} A resposta da IA foi cortada no limite de tamanho: a análise pode estar incompleta.", ""] \
        if not q.completa else []
    suspeitos = valores_com_erro(r.numeros)
    md += [f"**Relatório da administração:** {adm}.",
          f"**Tom:** {TOM.get(q.tom, 'sem resposta')}."
          + (f" {_item(q.justificativa_tom, suspeitos)[2:]}" if q.justificativa_tom else ""),
          ""]
    secoes = [("Motivos do resultado", q.motivos), ("Riscos e pontos de atenção", q.riscos),
              ("Perspectivas", q.perspectivas), ("Eventos relevantes", q.eventos), ("Comparabilidade", q.comparabilidade)]
    guidance = "não encontrado (nenhuma meta ou projeção explícita para o próximo período)"
    if q.guidance_status == "encontrado":
        md += ["**Guidance**", "", *[_item(i, suspeitos) for i in q.guidance], ""]
    else:
        md += [f"**Guidance:** {guidance}.", ""]
    for titulo, itens in secoes:
        md += [f"**{titulo}**", ""]
        md += [_item(i, suspeitos) for i in itens] if itens else ["- Não encontrado no documento."]
        md.append("")
    return md


# ------------------------------------------------------------------ perguntas


def pergunta(r: RespostaPergunta) -> list[str]:
    md = [f"### {r.numero}. {texto(r.pergunta)}" if r.numero else f"### {texto(r.pergunta)}", "", texto(r.texto), ""]
    if r.numeros_sem_fonte:
        md += [f"{ALERTA} Números sem trecho citado nesta resposta: {', '.join(texto(x) for x in r.numeros_sem_fonte)}. "
               "Confira no PDF antes de usar.", ""]
    if not r.completa:
        md += [f"{ALERTA} O agente não terminou a resposta (limite de rodadas ou de tamanho).", ""]
    if r.fontes:
        md += ["**Fontes**", ""]
        for i, f in enumerate(r.fontes, start=1):
            trecho = f.trecho if len(f.trecho) <= 220 else f.trecho[:217] + "..."
            calc = " · calculado pela solução" if f.calculado else ""
            md.append(f"{i}. {texto(f.documento)}, {_paginas(f.paginas) or 'sem página'}{calc}: “{texto(trecho)}”")
        md.append("")
    else:
        md += [f"{ALERTA} Resposta sem fonte citada.", ""]
    if r.ferramentas:
        md += [f"<sub>Ferramentas usadas pelo agente: {texto(', '.join(r.ferramentas))}.</sub>", ""]
    return md


# ------------------------------------------------------------------ alertas


def alertas(resultados: list[ResultadoDocumento]) -> list[str]:
    md = ["### Inconsistências conferidas em código", "",
          "| Empresa | Regra | Gravidade | Páginas | O que foi encontrado |", "|---|---|---|---|---|"]
    codigo = [(r, a) for r in resultados for a in r.numeros.alertas if a.origem == "codigo" and a.severidade != "info"]
    md += [f"| {celula(r.chave)} | {a.regra} | {a.severidade} | {_paginas(a.paginas)} | {celula(a.mensagem)} |"
           for r, a in codigo] or ["| — | — | — | — | Nenhuma. |"]
    info = [(r, a) for r in resultados for a in r.numeros.alertas if a.origem == "codigo" and a.severidade == "info"]
    if info:
        md += ["", "Diferenças pequenas entre texto e tabela (informativas):", ""]
        md += [f"- {texto(r.chave)} ({a.regra}, {_paginas(a.paginas)}): {texto(a.mensagem)}" for r, a in info]

    md += ["", "### Observações da IA, com citação", "",
           "Apontadas pela IA durante a leitura, com o trecho citado. Não foram conferidas em código: são pistas para o analista.", ""]
    ia = [(r, a.mensagem, a.paginas) for r in resultados for a in r.numeros.alertas if a.origem == "ia"]
    for r in resultados:
        conhecidos = [(a.mensagem, a.paginas) for a in r.numeros.alertas if a.severidade != "info"]
        ia += [(r, o.texto, paginas) for o in (r.qualitativa.observacoes if r.qualitativa else [])
               if not repete_achado(o.texto, paginas := [e.pagina for e in o.evidencias], conhecidos)]
    md += [f"- **{texto(r.chave)}** ({_paginas(p) or 'sem página'}): {texto(m)}" for r, m, p in ia] or ["- Nenhuma."]

    md += ["", "### Informações não encontradas", "",
           f"O que o documento não informa. Quando a solução consegue calcular, o valor aparece à parte na tabela, com {CALCULADO}.", ""]
    for r in resultados:
        faltam = [rotulo for rotulo, campo in (("receita líquida", "receita_liquida"), ("EBITDA", "ebitda"),
                  ("margem EBITDA", "margem_ebitda"), ("lucro líquido", "lucro_liquido"),
                  ("dívida líquida", "divida_liquida"), ("alavancagem", "alavancagem"),
                  ("fluxo de caixa operacional", "fluxo_caixa_operacional"), ("capex", "capex"))
                  if getattr(r.numeros, campo).status == "nao_encontrado"]
        q = r.qualitativa
        if q is not None and q.guidance_status != "encontrado":
            faltam.append("guidance")
        if q is not None and not q.tem_relatorio_administracao:
            faltam.append("relatório da administração")
        md.append(f"- **{texto(r.chave)}:** " + (", ".join(faltam) if faltam else "nada") + ".")
    return md


def _numeros_do_achado(t: str) -> set[tuple[str, float]]:
    """Os números que identificam um achado. Anos e números pequenos (páginas, notas) ficam de fora."""
    saida = set()
    for n in achar_numeros(t):
        if n.unidade in ("%", "x"):
            saida.add((n.unidade, round(abs(n.valor), 6)))
        elif not (n.valor.is_integer() and (abs(n.valor) <= 31 or 1900 <= abs(n.valor) <= 2100)):
            saida.add(("", abs(n.valor)))
    return saida


def repete_achado(observacao: str, paginas: list[int], conhecidos: list[tuple[str, list[int]]]) -> bool:
    """Rede de segurança: a observação da análise repete um alerta já listado?

    Repete quando fala de uma página em comum e todos os números dela já estão naquele alerta.
    Sem número, não dá para saber: a observação fica.
    """
    numeros = _numeros_do_achado(observacao)
    if not numeros:
        return False
    return any(set(paginas) & set(p) and numeros <= _numeros_do_achado(m) for m, p in conhecidos)


GLOSSARIO = [
    "- **EBITDA calculado (método da CVM):** lucro antes do resultado financeiro e dos impostos, mais depreciação e "
    "amortização da demonstração dos fluxos de caixa. Aparece à parte e nunca no lugar do EBITDA informado.",
    "- **EBITDA ajustado ou para covenants:** a definição da própria empresa, com ajustes. Não é comparável entre empresas.",
    "- **Dívida líquida:** empréstimos, financiamentos e debêntures (mais derivativos da dívida, quando a empresa os "
    "soma), menos caixa e aplicações financeiras. Negativa quer dizer caixa líquido.",
    "- **Alavancagem:** dívida líquida dividida pelo EBITDA. Com EBITDA negativo, o múltiplo não tem sentido.",
    "- **Variação:** (atual − anterior) ÷ |anterior|. Quando o valor troca de sinal, a variação não é calculada (n/a).",
]


# ------------------------------------------------------------------ relatório


def montar_relatorio(resultados: list[ResultadoDocumento], respostas: list[RespostaPergunta], *,
                     gerado_em: datetime, duracao_s: float | None = None) -> str:
    usos = [r.extracao.uso for r in resultados] + [r.qualitativa.uso for r in resultados if r.qualitativa]
    usos += [p.uso for p in respostas]
    custo_original = sum(u.custo_usd for u in usos)
    custo_agora = sum(u.custo_usd for u in usos if not u.gravada)
    modelos = sorted({u.modelo for u in usos})
    md = ["# Análise das demonstrações financeiras", "",
          f"Gerado em {gerado_em:%d/%m/%Y às %H:%M}. Documentos: {', '.join(texto(r.arquivo) for r in resultados)}. "
          f"Modelo: {', '.join(modelos)}.",
          f"Custo das chamadas à IA: US$ {numero_br(custo_original, 2)}"
          + (f" (nesta execução: US$ {numero_br(custo_agora, 2)}; o resto veio de respostas gravadas)"
             if custo_agora < custo_original else "")
          + (f". Tempo total: {duracao_s:.0f} s." if duracao_s is not None else "."), "",
          f"> **Como ler:** {INFORMADO} informado pela empresa e conferido no trecho do PDF · {CALCULADO} calculado pela "
          f"solução (não informado pela empresa) · {ALERTA} há alerta de validação · {NAO_ENCONTRADO} não encontrado no "
          "documento. Valores em R$ milhões. Cada número tem a página do PDF de onde veio.", "",
          "## 1. Resumo executivo", ""]
    for r in resultados:
        md += [f"### {texto(r.nome)} ({texto(r.arquivo)})", "", *[f"- {linha}" for linha in resumo_executivo(r)], ""]
    md += ["## 2. Tabela comparativa", "", *tabela(resultados), "",
           "As variações são calculadas pela solução, com os dois valores informados. A página de cada valor e o trecho "
           "exato estão em `saidas/<empresa>/indicadores.json`.", "", "## 3. Análise qualitativa", ""]
    for r in resultados:
        md += [f"### {texto(r.nome)}", "", *qualitativa(r)]
    md += ["## 4. Perguntas", ""]
    for p in sorted(respostas, key=lambda x: x.numero or 99):
        md += pergunta(p)
    if not respostas:
        md += ["Perguntas não executadas.", ""]
    md += ["## 5. Alertas", "", *alertas(resultados), "", "## 6. Glossário", "", *GLOSSARIO, ""]
    return "\n".join(md) + "\n"
