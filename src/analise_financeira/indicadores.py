"""Indicadores e alertas de cada documento: o JSON que o desafio pede.

Junta três coisas:
1. o que o documento informa (da extração, com página e trecho);
2. o que a solução calcula (calculos.py), sempre separado e com a fórmula;
3. os alertas: as regras de validacao.py, em código, e as observações da IA, com citação.

O que o documento não informa fica "nao_encontrado". O valor calculado aparece à
parte, com o rótulo "calculado pela solução", e nunca no lugar do informado.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel

from analise_financeira import calculos, validacao
from analise_financeira.esquemas import Evidencia, Extracao, Ocorrencia
from analise_financeira.pdf import Documento
from analise_financeira.roteamento import DEMONSTRACOES, Rotas

MIL = 1_000.0


class Dado(BaseModel):
    texto: str                  # como está no documento, ou a conta feita pela solução
    valor_reais: float | None = None
    unidade: str = ""           # "R$ mil", "R$ milhões", "x", "%"
    numero: float | None = None  # na unidade do documento (para múltiplos e percentuais)
    fontes: list[Evidencia] = []


class Indicador(BaseModel):
    status: Literal["encontrado", "nao_encontrado"]  # sobre o valor INFORMADO pelo documento
    atual: Dado | None = None
    anterior: Dado | None = None
    variacao: float | None = None       # calculada pela solução, em fração; None se não faz sentido
    definicao: str | None = None        # por exemplo, "EBITDA CVM"
    calculado: Dado | None = None       # calculado pela solução, sempre à parte
    calculado_anterior: Dado | None = None
    formula: str | None = None
    observacao: str | None = None


class AlertaSaida(BaseModel):
    regra: str
    severidade: Literal["erro", "aviso", "info"]
    origem: Literal["codigo", "ia"]     # "codigo": conferido em Python; "ia": apontado pela IA, com citação
    mensagem: str
    paginas: list[int] = []


class DocumentoAnalisado(BaseModel):
    documento: str
    empresa: str | None
    periodo_atual: str | None
    periodo_anterior: str | None
    receita_liquida: Indicador
    ebitda: Indicador
    margem_ebitda: Indicador
    lucro_liquido: Indicador
    lucro_controladores: Indicador
    divida_liquida: Indicador
    alavancagem: Indicador
    fluxo_caixa_operacional: Indicador
    capex: Indicador
    alertas: list[AlertaSaida] = []


# ------------------------------------------------------------------ apoio


def _principal(ext: Extracao, campo: str) -> Ocorrencia | None:
    c = ext.campos.get(campo)
    return c.principal if c and c.status == "encontrado" else None


def _dado(o: Ocorrencia | None) -> Dado | None:
    if o is None:
        return None
    return Dado(texto=o.texto, valor_reais=o.valor_reais, unidade=o.unidade, numero=o.numero, fontes=o.evidencias)


def _reais(o: Ocorrencia | None) -> float | None:
    return o.valor_reais if o else None


def _texto_reais(v: float) -> str:
    s = f"{abs(v) / 1e6:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if v < 0 else ''}R$ {s} milhões"


def _calculado(valor: float | None, *partes: Ocorrencia | None) -> Dado | None:
    if valor is None:
        return None
    fontes = [e for p in partes if p for e in p.evidencias]
    return Dado(texto=f"{_texto_reais(valor)} (calculado pela solução)", valor_reais=valor, unidade="R$", fontes=fontes)


def _ano(texto: str | None) -> str | None:
    anos = re.findall(r"(?:19|20)\d{2}", texto or "")
    return anos[-1] if anos else None


def _paginas(*ocorrencias: Ocorrencia | None) -> list[int]:
    return sorted({e.pagina for o in ocorrencias if o for e in o.evidencias})


# ------------------------------------------------------------------ indicadores


def _simples(ext: Extracao, campo: str) -> Indicador:
    atual, anterior = _principal(ext, f"{campo}_atual"), _principal(ext, f"{campo}_anterior")
    variacao = None
    if _reais(atual) is not None and _reais(anterior) is not None:
        variacao = calculos.variacao(atual.valor_reais, anterior.valor_reais)
    return Indicador(status="encontrado" if atual else "nao_encontrado", atual=_dado(atual), anterior=_dado(anterior),
                     variacao=variacao)


def _ebitda(ext: Extracao) -> tuple[Indicador, float | None]:
    ind = _simples(ext, "ebitda")
    definicao = _principal(ext, "ebitda_definicao")
    ind.definicao = definicao.texto if definicao else None
    ebit, da = _principal(ext, "ebit_atual"), _principal(ext, "depreciacao_atual")
    ebit_ant, da_ant = _principal(ext, "ebit_anterior"), _principal(ext, "depreciacao_anterior")
    calc = calculos.ebitda_calculado(ebit.valor_reais, da.valor_reais) if ebit and da else None
    calc_ant = calculos.ebitda_calculado(ebit_ant.valor_reais, da_ant.valor_reais) if ebit_ant and da_ant else None
    ind.calculado, ind.calculado_anterior = _calculado(calc, ebit, da), _calculado(calc_ant, ebit_ant, da_ant)
    ind.formula = "lucro antes do resultado financeiro e dos impostos + depreciação e amortização da DFC (método da CVM)"
    if ind.status == "nao_encontrado" and calc is not None:
        ind.observacao = "O documento não informa EBITDA. O valor calculado aparece à parte."
    return ind, calc


def _margem(ext: Extracao, ebitda_calc: float | None, receita: Ocorrencia | None) -> Indicador:
    informada = _principal(ext, "margem_ebitda_atual")
    ind = Indicador(status="encontrado" if informada else "nao_encontrado", atual=_dado(informada))
    margem = calculos.margem(ebitda_calc, receita.valor_reais) if ebitda_calc is not None and receita else None
    if margem is not None:
        ind.calculado = Dado(texto=f"{margem * 100:.1f}% (calculado pela solução)".replace(".", ","), numero=margem,
                             unidade="%", fontes=receita.evidencias)
        ind.formula = "EBITDA calculado ÷ receita líquida"
    return ind


def _divida(ext: Extracao) -> tuple[Indicador, float | None]:
    ind = _simples(ext, "divida_liquida")
    emp, cx = _principal(ext, "emprestimos_total_atual"), _principal(ext, "caixa_atual")
    apl, der = _principal(ext, "aplicacoes_financeiras_atual"), _principal(ext, "derivativos_divida_atual")
    calc = None
    if emp and cx:
        calc = calculos.divida_liquida_calculada(emp.valor_reais, cx.valor_reais, _reais(apl) or 0.0, _reais(der) or 0.0)
        ind.calculado = _calculado(calc, emp, der, cx, apl)
        ind.formula = "empréstimos e debêntures + derivativos da dívida − caixa − aplicações financeiras"
        if calc < 0:
            ind.observacao = "Dívida líquida negativa: a empresa tem caixa líquido."
    return ind, calc


def _alavancagem(ext: Extracao, divida: float | None, ebitda_calc: float | None) -> Indicador:
    ind = _simples(ext, "alavancagem")
    ind.variacao = None  # múltiplo: a variação em % não ajuda o analista
    definicao = _principal(ext, "alavancagem_definicao")
    ind.definicao = definicao.texto if definicao else None
    ind.formula = "dívida líquida ÷ EBITDA calculado"
    if divida is not None and ebitda_calc is not None:
        multiplo = calculos.alavancagem(divida, ebitda_calc)
        if multiplo is None:
            ind.observacao = "Com EBITDA calculado zero ou negativo, a alavancagem calculada não é significativa."
        elif divida < 0:
            ind.observacao = "Caixa líquido: a empresa não está alavancada."
        else:
            ind.calculado = Dado(texto=f"{multiplo:.2f}x (calculado pela solução)".replace(".", ","), numero=multiplo,
                                 unidade="x")
    return ind


def _capex(ext: Extracao) -> Indicador:
    informado = _principal(ext, "investimentos_informados_atual")
    imob, intang = _principal(ext, "capex_imobilizado_atual"), _principal(ext, "capex_intangivel_atual")
    ind = Indicador(status="encontrado" if (informado or imob) else "nao_encontrado", atual=_dado(informado))
    if imob:
        soma = -(imob.valor_reais + (_reais(intang) or 0.0))  # saídas de caixa: negativas na DFC
        ind.calculado = _calculado(soma, imob, intang)
        ind.formula = "aquisições de imobilizado + intangível, nas atividades de investimento da DFC"
    return ind


# ------------------------------------------------------------------ alertas


def _de_regra(alerta: validacao.Alerta | None, paginas: list[int]) -> list[AlertaSaida]:
    if alerta is None:
        return []
    return [AlertaSaida(regra=alerta.regra, severidade=alerta.severidade, origem="codigo", mensagem=alerta.mensagem,
                        paginas=paginas)]


_ESCALA = {"R$ mil": "mil", "R$ milhões": "milhões", "R$ bilhões": "bilhões", "R$ ": ""}
_CABECALHO = re.compile(r"^(?:\d{1,2}[./]\d{1,2}[./])?20\d{2,3}(?:\s*\|\s*(?:\d{1,2}[./]\d{1,2}[./])?20\d{2,3})+$")
_DATA = re.compile(r"\d{1,2} de [a-zç]+ de \d{4}", re.I)


def _data_de_aprovacao(texto: str, fim_do_exercicio: date) -> date | None:
    """A data em que as demonstrações foram aprovadas ou autorizadas para emissão.

    Procura a frase que fala das demonstrações financeiras e de aprovação ou
    autorização, e ignora a data do fim do exercício citada na mesma frase.
    """
    for frase in re.split(r"(?<=[.;])\s+", texto.replace("\n", " ")):
        if re.search(r"demonstra[çc]\w+ financeiras", frase, re.I) and re.search(r"aprovad|autoriz", frase, re.I):
            datas = [validacao.ler_data(d) for d in _DATA.findall(frase)]
            datas = [d for d in datas if d and d != fim_do_exercicio]
            if datas:
                return datas[0]
    return None


def _alertas(ext: Extracao, doc: Documento, rotas: Rotas, ebitda_calc: float | None, divida_calc: float | None) -> list[AlertaSaida]:
    alertas: list[AlertaSaida] = []
    p = lambda campo: _principal(ext, campo)  # noqa: E731
    periodo = _ano(p("periodo_atual").texto if p("periodo_atual") else None)
    anterior = _ano(p("periodo_anterior").texto if p("periodo_anterior") else None) or (
        str(int(periodo) - 1) if periodo else None)

    # V7: EBITDA informado contra EBIT + depreciação
    if p("ebitda_atual") and ebitda_calc is not None:
        alertas += _de_regra(validacao.conferir_ebitda(p("ebitda_atual").valor_reais, p("ebit_atual").valor_reais,
                                                       p("depreciacao_atual").valor_reais),
                             _paginas(p("ebitda_atual"), p("ebit_atual"), p("depreciacao_atual")))
    # V8: dívida líquida informada contra a calculada
    if p("divida_liquida_atual") and divida_calc is not None:
        emp, cx = p("emprestimos_total_atual"), p("caixa_atual")
        alertas += _de_regra(validacao.conferir_divida_liquida(
            p("divida_liquida_atual").valor_reais, emp.valor_reais, cx.valor_reais,
            _reais(p("aplicacoes_financeiras_atual")) or 0.0, _reais(p("derivativos_divida_atual")) or 0.0),
            _paginas(p("divida_liquida_atual"), emp, cx))
    # V9: alavancagem informada contra dívida líquida ÷ EBITDA
    divida_ref = _reais(p("divida_liquida_atual")) if p("divida_liquida_atual") else divida_calc
    if p("alavancagem_atual") and divida_ref is not None and ebitda_calc is not None:
        alertas += _de_regra(validacao.conferir_alavancagem(p("alavancagem_atual").numero, divida_ref, ebitda_calc),
                             _paginas(p("alavancagem_atual")))
    # V10: o mesmo campo em escalas diferentes (relatório em milhões x tabela em mil)
    for campo in ext.campos.values():
        if campo.status != "encontrado" or len(campo.ocorrencias) < 2 or campo.principal.valor_reais is None:
            continue
        for outra in campo.ocorrencias:
            if outra is campo.principal or outra.valor_reais is None or outra.unidade not in _ESCALA:
                continue
            alertas += _de_regra(validacao.conferir_escala(outra.numero, _ESCALA[outra.unidade], campo.principal.valor_reais),
                                 _paginas(campo.principal, outra))
    # V11: ano do texto contra o período do valor
    for nome, campo in ext.campos.items():
        o = campo.principal
        ano = periodo if nome.endswith("_atual") else anterior if nome.endswith("_anterior") else None
        if o is None or ano is None or o.fonte != "relatorio_adm":
            continue
        for e in o.evidencias:
            alertas += _de_regra(validacao.conferir_ano_no_texto(e.trecho.replace("\n", " "), o.texto, ano), [e.pagina])
    # V13: o mesmo número em duas demonstrações
    for nome, (a, b) in {"Lucro líquido (DRE × DMPL)": ("lucro_liquido_atual", "lucro_liquido_dmpl_atual"),
                         "Caixa (balanço × DFC)": ("caixa_atual", "caixa_final_dfc_atual"),
                         "Patrimônio líquido (balanço × notas)": ("patrimonio_liquido_atual", "patrimonio_liquido_notas_atual")}.items():
        oa, ob = p(a), p(b)
        if oa and ob and oa.valor_reais is not None and ob.valor_reais is not None:
            ocorr = [(oa.valor_reais / MIL, f"p. {_paginas(oa)}"), (ob.valor_reais / MIL, f"p. {_paginas(ob)}")]
            alertas += _de_regra(validacao.conferir_ocorrencias(f"{nome}, em R$ mil", ocorr), _paginas(oa, ob))
    # V14: período comparativo não auditado. Vale o aviso no parecer do auditor e nas
    # colunas "(não auditado)" das demonstrações; menção solta nas notas não entra.
    nao_auditado = []
    for pg in doc.paginas:
        tipo = rotas.tipos.get(pg.numero)
        topo = "\n".join(pg.linhas[:12])
        if tipo in DEMONSTRACOES and validacao.conferir_auditoria(topo, pg.numero):
            nao_auditado.append(pg.numero)
        elif tipo == "auditor" and anterior and any(
                anterior in frase and validacao.conferir_auditoria(frase, pg.numero)
                for frase in re.split(r"(?<=[.;])\s+", pg.texto.replace("\n", " "))):
            nao_auditado.append(pg.numero)
    if nao_auditado:
        lista = ", ".join(map(str, nao_auditado))
        alertas.append(AlertaSaida(regra="V14", severidade="aviso", origem="codigo", paginas=nao_auditado,
                                   mensagem=f"O período comparativo ({anterior}) não foi auditado (p. {lista}). "
                                            f"As variações contra {anterior} usam números não auditados."))
    # V15: data de aprovação das demonstrações
    if periodo:
        fim = date(int(periodo), 12, 31)
        for pg in doc.paginas:
            data = _data_de_aprovacao(pg.texto, fim)
            if data:
                alertas += _de_regra(validacao.conferir_datas(data, fim), [pg.numero])
    # V16: cabeçalho de tabela com ano repetido ou malformado
    if periodo and anterior:
        for pg in doc.paginas:
            for linha in pg.linhas:
                if _CABECALHO.match(linha.strip()):
                    alertas += _de_regra(validacao.conferir_anos_do_cabecalho(linha, periodo, anterior), [pg.numero])
    # Observações da IA: entram como aviso, com a citação, marcadas como "apontado pela IA"
    for obs in ext.observacoes:
        alertas.append(AlertaSaida(regra="IA", severidade="aviso", origem="ia", mensagem=obs.texto,
                                   paginas=sorted({e.pagina for e in obs.evidencias})))
    return alertas


def analisar_numeros(ext: Extracao, doc: Documento, rotas: Rotas) -> DocumentoAnalisado:
    receita = _simples(ext, "receita_liquida")
    ebitda, ebitda_calc = _ebitda(ext)
    divida, divida_calc = _divida(ext)
    texto = lambda campo: _principal(ext, campo).texto if _principal(ext, campo) else None  # noqa: E731
    return DocumentoAnalisado(
        documento=ext.documento,
        empresa=texto("empresa"),
        periodo_atual=texto("periodo_atual"),
        periodo_anterior=texto("periodo_anterior"),
        receita_liquida=receita,
        ebitda=ebitda,
        margem_ebitda=_margem(ext, ebitda_calc, _principal(ext, "receita_liquida_atual")),
        lucro_liquido=_simples(ext, "lucro_liquido"),
        lucro_controladores=_simples(ext, "lucro_controladores"),
        divida_liquida=divida,
        alavancagem=_alavancagem(ext, _reais(_principal(ext, "divida_liquida_atual")) or divida_calc, ebitda_calc),
        fluxo_caixa_operacional=_simples(ext, "fco"),
        capex=_capex(ext),
        alertas=_alertas(ext, doc, rotas, ebitda_calc, divida_calc),
    )
