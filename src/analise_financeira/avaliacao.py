"""Avaliação: compara a extração com o gabarito (avaliacao/gabarito.json).

Mede quatro coisas, campo a campo:
- valor certo: o número da tabela bate com o gabarito (tolerância de 0,1%, em reais);
- página certa: a evidência aponta uma página onde o valor certo aparece;
- "não encontrado" certo: a IA diz "não encontrado" onde o documento não tem o dado;
- evidência conferida: o número está no trecho citado, com o mesmo sinal.

Inventar um número onde o documento não tem nada é o pior erro, e aparece na
coluna "inventou".
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from analise_financeira.esquemas import Campo, Extracao
from analise_financeira.numeros import em_reais, ler_numero


def _valor_esperado(item: dict) -> tuple[float, float | None]:
    """(número, valor em reais) do valor do gabarito. Valor sem escala escrita é de tabela em R$ mil."""
    n = ler_numero(item["valor"])
    if n.unidade in ("%", "x"):
        return n.valor, None
    return n.valor, em_reais(n, "" if n.unidade else "mil")


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
            obtido = campo.principal.texto if campo.principal else campo.status
            linhas.append({"campo": nome, "esperado": item["valor"], "obtido": obtido, "ok": valor_ok and pagina_ok})
    encontrados = [c for c in extracao.campos.values() if c.status in ("encontrado", "sem_evidencia")]
    conferidos = sum(1 for c in encontrados if c.principal and c.principal.conferido)
    return {"documento": extracao.documento, "contagem": contagem, "linhas": linhas,
            "evidencia_conferida": (conferidos, len(encontrados))}


def _pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "-"


def avaliar(pasta_saidas: str | Path = "saidas", gabarito: str | Path = "avaliacao/gabarito.json",
            pasta_resultados: str | Path = "avaliacao/resultados") -> str:
    dados = json.loads(Path(gabarito).read_text(encoding="utf-8"))
    resultados = []
    for doc, esperado in dados.items():
        if doc.startswith("_"):
            continue
        arquivo = Path(pasta_saidas) / Path(doc).stem / "extracao.json"
        extracao = Extracao.model_validate_json(arquivo.read_text(encoding="utf-8"))
        resultados.append((extracao, avaliar_documento(extracao, esperado)))

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
    md += ["", "Ressalva: são só 3 documentos, e o gabarito foi montado lendo esses mesmos documentos. "
           "Serve para achar erro, e não para prometer acerto em produção.", "", "## Campos com erro", ""]
    erros = [f"- {r['documento']} · `{linha['campo']}`: esperado {linha['esperado']}, obtido {linha['obtido']}"
             for _, r in resultados for linha in r["linhas"] if not linha["ok"]]
    md += erros or ["Nenhum."]

    destino = Path(pasta_resultados)
    destino.mkdir(parents=True, exist_ok=True)
    texto = "\n".join(md) + "\n"
    (destino / f"{date.today():%Y-%m-%d}_{modelo}.md").write_text(texto, encoding="utf-8")
    (destino / f"{date.today():%Y-%m-%d}_{modelo}.json").write_text(
        json.dumps([r for _, r in resultados], ensure_ascii=False, indent=1), encoding="utf-8")
    return texto
