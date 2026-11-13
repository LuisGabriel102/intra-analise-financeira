"""Avaliação: compara a extração com o gabarito (avaliacao/gabarito.json).

Mede quatro coisas, campo a campo:
- valor certo: o número da tabela bate com o gabarito (tolerância de 0,1%, em reais);
- página certa: a evidência aponta uma página onde o valor certo aparece;
- "não encontrado" certo: a IA diz "não encontrado" onde o documento não tem o dado;
- evidência conferida: o número está no trecho citado, com o mesmo sinal.

Inventar um número onde o documento não tem nada é o pior erro, e aparece na
coluna "inventou".

Mede também quantas das 15 armadilhas principais viraram alerta: pela regra em
código ou pela observação da IA (que vem com citação, mas não é conferida em código).

Quando a análise qualitativa e as perguntas já rodaram, faz uma checagem aproximada,
por palavras: o tom certo, o guidance "não encontrado", os fatos que precisam aparecer
e as respostas com os termos esperados. É grosseira de propósito: pega o erro grande
(tom errado, Alibra esquecida, recuperação judicial da cliente atribuída à Light).
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from analise_financeira.esquemas import AnaliseQualitativa, Campo, Extracao, Item, RespostaPergunta
from analise_financeira.indicadores import AlertaSaida, DocumentoAnalisado
from analise_financeira.numeros import em_reais, ler_numero


def _valor_esperado(item: dict) -> tuple[float, float | None]:
    """(número, valor em reais) do valor do gabarito. Valor sem escala escrita é de tabela em R$ mil."""
    n = ler_numero(item["valor"])
    if n.unidade in ("%", "x"):
        return n.valor, None
    return n.valor, em_reais(n, "" if n.unidade else "mil")


def _reais(v: float | None) -> str:
    """9032236000 -> 'R$ 9,03 bi' (para o erro mostrar a escala)."""
    if v is None:
        return ""
    for limite, nome in ((1e9, "bi"), (1e6, "mi"), (1e3, "mil")):
        if abs(v) >= limite:
            return f" = R$ {v / limite:.2f} {nome}".replace(".", ",")
    return f" = R$ {v:.2f}".replace(".", ",")


def _bate(campo: Campo, item: dict) -> tuple[bool, bool]:
    """(valor certo, página certa) para um campo com valor esperado."""
    p = campo.principal
    if campo.status != "encontrado" or p is None or p.numero is None:
        return False, False
    paginas_certas = set(item["paginas"]) | set(item.get("tambem", {}).get("paginas", []))
    pagina_ok = any(e.pagina in paginas_certas for e in p.evidencias)
    for alternativa in (item, item.get("tambem")):
        if not alternativa:
            continue
        numero, reais = _valor_esperado(alternativa)
        if reais is not None and p.valor_reais is not None:
            if abs(p.valor_reais - reais) <= 0.001 * abs(reais):
                return True, pagina_ok
        elif abs(p.numero - numero) <= 0.001 * max(abs(numero), 1e-9):
            return True, pagina_ok
    return False, pagina_ok


def avaliar_documento(extracao: Extracao, esperado: dict) -> dict:
    linhas, contagem = [], {"valores": 0, "valor_ok": 0, "pagina_ok": 0, "nao_enc": 0, "nao_enc_ok": 0, "inventou": 0}
    for nome, item in esperado["campos"].items():
        campo = extracao.campos.get(nome) or Campo(status="sem_resposta")
        if item.get("status") == "nao_encontrado":
            contagem["nao_enc"] += 1
            ok = campo.status == "nao_encontrado"
            contagem["nao_enc_ok"] += ok
            contagem["inventou"] += campo.status in ("encontrado", "sem_evidencia")
            linhas.append({"campo": nome, "esperado": "não encontrado", "obtido": campo.status, "ok": ok})
        else:
            contagem["valores"] += 1
            valor_ok, pagina_ok = _bate(campo, item)
            contagem["valor_ok"] += valor_ok
            contagem["pagina_ok"] += pagina_ok
            p = campo.principal
            obtido = f"{p.texto} ({p.unidade or 'sem escala'}){_reais(p.valor_reais)}" if p else campo.status
            esperado_txt = f"{item['valor']}{_reais(_valor_esperado(item)[1])}"
            linhas.append({"campo": nome, "esperado": esperado_txt, "obtido": obtido, "ok": valor_ok and pagina_ok})
    encontrados = [c for c in extracao.campos.values() if c.status in ("encontrado", "sem_evidencia")]
    conferidos = sum(1 for c in encontrados if c.principal and c.principal.conferido)
    return {"documento": extracao.documento, "contagem": contagem, "linhas": linhas,
            "evidencia_conferida": (conferidos, len(encontrados))}


def armadilhas_detectadas(analise: DocumentoAnalisado, esperadas: list[dict],
                          extras: list[AlertaSaida] | None = None) -> list[dict]:
    """Para cada armadilha esperada: foi detectada? por código ou pela IA?

    extras: observações da IA na análise qualitativa, que também valem como alerta da IA.
    Uma observação da IA conta quando cai numa das páginas da armadilha e, se o gabarito
    trouxer "termos_ia", quando fala de um deles. A mensagem vai junto, para conferência.
    """
    alertas = [*analise.alertas, *(extras or [])]
    resultado = []
    for esperada in esperadas:
        paginas = set(esperada["paginas"])
        termos = [_sem_acento(t) for t in esperada.get("termos_ia", [])]

        def conta(a: AlertaSaida, paginas=paginas, termos=termos, esperada=esperada) -> bool:
            if not paginas & set(a.paginas):
                return False
            if a.origem == "codigo":
                return a.regra == esperada["regra"]
            if esperada["regra"] != "IA" and not termos:
                return False
            return not termos or any(t in _sem_acento(a.mensagem) for t in termos)

        achou = sorted((a for a in alertas if conta(a)), key=lambda a: -len(paginas & set(a.paginas)))
        por_codigo = [a for a in achou if a.origem == "codigo"]
        escolhido = (por_codigo or achou or [None])[0]
        resultado.append({"id": esperada["id"], "detectada": bool(achou),
                          "por": ("código" if por_codigo else "IA") if achou else None,
                          "mensagem": escolhido.mensagem[:160] if escolhido else None})
    return resultado


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()


def _itens(q: AnaliseQualitativa, secoes: list[str] | None = None) -> list[Item]:
    nomes = secoes or ["motivos", "riscos", "guidance", "perspectivas", "eventos", "comparabilidade", "observacoes"]
    return [i for nome in nomes for i in getattr(q, nome)]


def avaliar_qualitativa(q: AnaliseQualitativa, esperado: dict) -> dict:
    """Checagem aproximada da análise qualitativa: tom, guidance, fatos que precisam aparecer e o que não pode."""
    checagens = [
        {"o_que": "tom", "ok": q.tom in esperado["tom"],
         "detalhe": f"{q.tom} (esperado: {' ou '.join(esperado['tom'])})"},
        {"o_que": "relatório da administração", "ok": q.tem_relatorio_administracao == esperado["tem_relatorio_administracao"],
         "detalhe": "sim" if q.tem_relatorio_administracao else "não"},
        {"o_que": "guidance", "ok": q.guidance_status == esperado["guidance"], "detalhe": q.guidance_status},
    ]
    for m in esperado.get("deve_mencionar", []):
        achou = [i for i in _itens(q, m["secoes"]) if any(t in _sem_acento(i.texto) for t in m["termos"])]
        checagens.append({"o_que": m["o_que"], "ok": bool(achou),
                          "detalhe": achou[0].texto[:140] if achou else "não mencionado"})
    for m in esperado.get("nao_deve", []):
        ruins = [i for i in _itens(q) if any(t in _sem_acento(i.texto) for t in m["termos"])
                 and not any(x in _sem_acento(i.texto) for x in m["exceto"])]
        checagens.append({"o_que": f"não errar: {m['o_que']}", "ok": not ruins,
                          "detalhe": ruins[0].texto[:140] if ruins else "ok"})
    itens = _itens(q)
    return {"documento": q.documento, "checagens": checagens, "itens": len(itens),
            "com_trecho": sum(1 for i in itens if i.conferido),
            "com_numero_sem_fonte": sum(1 for i in itens if i.numeros_sem_fonte)}


def paragrafo_da_empresa(texto: str, empresa: str) -> str:
    """O parágrafo da resposta sobre uma empresa: o que começa com o nome dela ("**Brasal:** ...", "- Brasal: ...").

    Se nenhum começar com o nome, valem os parágrafos que citam a empresa (e não a conclusão inteira).
    """
    paragrafos = re.split(r"\n\s*\n|\n(?=\s*[-*]\s)", texto)
    padrao = re.compile(rf"^\s*(?:[-*]\s+)?(?:\*\*)?{re.escape(empresa)}\b", re.IGNORECASE)
    proprios = [p for p in paragrafos if padrao.match(p)]
    return "\n".join(proprios or [p for p in paragrafos[1:] if re.search(rf"\b{re.escape(empresa)}\b", p, re.I)])


_NEGA = r"nao (?:encontr|cit|mencion|aparec|list)\w*"


def menciona(trecho: str, termo: str) -> bool:
    """O termo aparece de forma afirmativa? "não encontrei risco de juros" não conta como citar juros."""
    for m in re.finditer(re.escape(termo), trecho):
        antes = re.split(r"[.;!?]\s", trecho[max(0, m.start() - 80):m.start()])[-1]
        if not re.search(_NEGA, antes):
            return True
    return False


def avaliar_perguntas(respostas: list[RespostaPergunta], esperado: dict) -> list[dict]:
    """Cada resposta tem os termos esperados (no todo e no parágrafo de cada empresa)? Tem fonte? Terminou?

    Um número sem trecho citado também reprova a resposta: é a mesma régua da análise qualitativa.
    """
    linhas = []
    for r in sorted(respostas, key=lambda x: x.numero or 99):
        e = esperado.get(str(r.numero))
        if not e:
            continue
        texto = _sem_acento(r.texto)
        faltam = [" ou ".join(alternativas) for alternativas in e["deve_conter"]
                  if not any(a in texto for a in alternativas)]
        for empresa, itens in e.get("por_empresa", {}).items():
            trecho = _sem_acento(paragrafo_da_empresa(r.texto, empresa))
            faltam += [f"{empresa}: {' ou '.join(alternativas)}" for alternativas in itens
                       if not any(menciona(trecho, a) for a in alternativas)]
        linhas.append({"numero": r.numero, "faltam": faltam, "fontes": len(r.fontes), "completa": r.completa,
                       "numeros_sem_fonte": r.numeros_sem_fonte,
                       "ok": not faltam and bool(r.fontes) and r.completa and not r.numeros_sem_fonte})
    return linhas


def _pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "-"


def avaliar(pasta_saidas: str | Path = "saidas", gabarito: str | Path = "avaliacao/gabarito.json",
            pasta_resultados: str | Path = "avaliacao/resultados") -> str:
    dados = json.loads(Path(gabarito).read_text(encoding="utf-8"))
    resultados = []
    for doc, esperado in dados.items():
        if doc.startswith("_"):
            continue
        pasta = Path(pasta_saidas) / Path(doc).stem
        extracao = Extracao.model_validate_json((pasta / "extracao.json").read_text(encoding="utf-8"))
        r = avaliar_documento(extracao, esperado)
        qualitativa = None
        if (pasta / "analise.json").exists():
            qualitativa = AnaliseQualitativa.model_validate_json((pasta / "analise.json").read_text(encoding="utf-8"))
            if doc in dados.get("_qualitativo", {}):
                r["qualitativo"] = avaliar_qualitativa(qualitativa, dados["_qualitativo"][doc])
        analise_json = pasta / "indicadores.json"
        if analise_json.exists() and esperado.get("alertas_esperados"):
            analise = DocumentoAnalisado.model_validate_json(analise_json.read_text(encoding="utf-8"))
            extras = [AlertaSaida(regra="IA", severidade="aviso", origem="ia", mensagem=o.texto,
                                  paginas=sorted({e.pagina for e in o.evidencias}))
                      for o in (qualitativa.observacoes if qualitativa else [])]
            r["armadilhas"] = armadilhas_detectadas(analise, esperado["alertas_esperados"], extras)
        resultados.append((extracao, r))

    modelo = resultados[0][0].uso.modelo if resultados else "-"
    md = [f"# Avaliação da extração ({date.today():%d/%m/%Y}, modelo `{modelo}`)", "",
          "| Documento | Valor certo | Página certa | \"Não encontrado\" certo | Inventou | Evidência conferida |",
          "|---|---|---|---|---|---|"]
    total = {"valores": 0, "valor_ok": 0, "pagina_ok": 0, "nao_enc": 0, "nao_enc_ok": 0, "inventou": 0}
    conf = [0, 0]
    for _, r in resultados:
        c = r["contagem"]
        for k in total:
            total[k] += c[k]
        conf[0] += r["evidencia_conferida"][0]
        conf[1] += r["evidencia_conferida"][1]
        md.append(f"| {r['documento']} | {_pct(c['valor_ok'], c['valores'])} | {_pct(c['pagina_ok'], c['valores'])} | "
                  f"{_pct(c['nao_enc_ok'], c['nao_enc'])} | {c['inventou']} | {_pct(*r['evidencia_conferida'])} |")
    md.append(f"| **Total** | **{_pct(total['valor_ok'], total['valores'])}** | **{_pct(total['pagina_ok'], total['valores'])}** | "
              f"**{_pct(total['nao_enc_ok'], total['nao_enc'])}** | **{total['inventou']}** | **{_pct(*conf)}** |")
    armadilhas = [a for _, r in resultados for a in r.get("armadilhas", [])]
    if armadilhas:
        detectadas = [a for a in armadilhas if a["detectada"]]
        por_codigo = sum(1 for a in detectadas if a["por"] == "código")
        md += ["", f"**Armadilhas principais detectadas: {len(detectadas)} de {len(armadilhas)}** "
               f"({por_codigo} conferidas em código e {len(detectadas) - por_codigo} apontadas pela IA, com citação).", ""]
        md += [f"- {a['id']}: " + (f"detectada ({a['por']}): {a['mensagem']}" if a["detectada"] else "não detectada")
               for a in armadilhas]
    md += ["", "## Campos com erro", ""]
    erros = [f"- {r['documento']} · `{linha['campo']}`: esperado {linha['esperado']}, obtido {linha['obtido']}"
             for _, r in resultados for linha in r["linhas"] if not linha["ok"]]
    md += erros or ["Nenhum."]
    qualitativos = [r["qualitativo"] for _, r in resultados if "qualitativo" in r]
    if qualitativos:
        certas = sum(c["ok"] for q in qualitativos for c in q["checagens"])
        total_q = sum(len(q["checagens"]) for q in qualitativos)
        itens = sum(q["itens"] for q in qualitativos)
        md += ["", f"## Análise qualitativa (checagem aproximada, por palavras): {certas} de {total_q}", "",
               f"Itens com trecho citado: {_pct(sum(q['com_trecho'] for q in qualitativos), itens)}. "
               f"Itens com número que não está no trecho: {sum(q['com_numero_sem_fonte'] for q in qualitativos)}.", ""]
        for q in qualitativos:
            md += [f"- {q['documento']} · {c['o_que']}: {'ok' if c['ok'] else 'FALHOU'} ({c['detalhe']})"
                   for c in q["checagens"]]
    arquivo_perguntas = Path(pasta_saidas) / "perguntas.json"
    if arquivo_perguntas.exists() and "_perguntas" in dados:
        respostas = [RespostaPergunta.model_validate(x)
                     for x in json.loads(arquivo_perguntas.read_text(encoding="utf-8"))]
        linhas = avaliar_perguntas(respostas, dados["_perguntas"])
        md += ["", f"## Perguntas (checagem aproximada, por palavras): {sum(x['ok'] for x in linhas)} de {len(linhas)}", ""]
        md += [f"- Pergunta {x['numero']}: " + ("ok" if x["ok"] else "FALHOU") + f" ({x['fontes']} fontes"
               + (f"; faltou: {'; '.join(x['faltam'])}" if x["faltam"] else "")
               + (f"; número sem trecho citado: {', '.join(x['numeros_sem_fonte'])}" if x["numeros_sem_fonte"] else "")
               + ("" if x["completa"] else "; resposta incompleta") + ")" for x in linhas]

    md += ["", "Ressalva: são só 3 documentos, e o gabarito foi montado lendo esses mesmos documentos. "
           "Serve para achar erro, e não para prometer acerto em produção."]

    destino = Path(pasta_resultados)
    destino.mkdir(parents=True, exist_ok=True)
    texto = "\n".join(md) + "\n"
    (destino / f"{date.today():%Y-%m-%d}_{modelo}.md").write_text(texto, encoding="utf-8")
    (destino / f"{date.today():%Y-%m-%d}_{modelo}.json").write_text(
        json.dumps([r for _, r in resultados], ensure_ascii=False, indent=1), encoding="utf-8")
    return texto
