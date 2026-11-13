"""Chamada ao Claude, com gravação das respostas, modo replay e registro de custo.

- Toda resposta real fica gravada em gravacoes/. A mesma pergunta não é paga duas vezes.
- No modo replay, a solução roda só com as respostas gravadas: sem chave e sem custo.
- Cada chamada vira uma linha em saidas/traces.jsonl, com modelo, tokens, custo e tempo.
  Os nomes dos campos seguem as convenções GenAI do OpenTelemetry, para irem direto
  ao Application Insights em produção.

O Opus 5.5 não aceita temperature e não deixa desligar o raciocínio. A estabilidade
vem do formato fixo, da conferência em código e das respostas gravadas.

Dois jeitos de chamar:
- perguntar(): uma pergunta, uma resposta (extrator e analista);
- conversar(): o agente com ferramentas. A IA pede uma ferramenta, o código executa
  e devolve o resultado, até a resposta final. Cada rodada é gravada à parte.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# US$ por milhão de tokens: entrada, saída e leitura de cache.
# Fonte: página de preços da Claude Platform, conferida em 13/11/2026.
PRECOS = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),  # prompts de até 100 mil tokens; acima, 0,50 / 2,50
}


class SemGravacao(RuntimeError):
    """No modo replay, a pergunta não tem resposta gravada."""


ESCRITA_CACHE = 1.25  # gravar no cache (5 minutos) custa 1,25x o preço da entrada


@dataclass
class Resposta:
    blocos: list[dict]  # blocos da resposta: no perguntar(), só os de texto, com as citações
    modelo: str
    tokens_entrada: int
    tokens_saida: int
    tokens_cache: int = 0          # lidos do cache
    segundos: float = 0.0
    gravada: bool = False          # veio de gravacoes/, sem chamar a API
    tokens_cache_escrita: int = 0  # gravados no cache
    parada: str = ""               # por que a IA parou: end_turn, tool_use, max_tokens...

    @property
    def custo_usd(self) -> float:
        entrada, saida, cache = PRECOS.get(self.modelo, (0.0, 0.0, 0.0))
        return (self.tokens_entrada * entrada + self.tokens_cache_escrita * entrada * ESCRITA_CACHE
                + self.tokens_saida * saida + self.tokens_cache * cache) / 1e6


@dataclass
class Conversa:
    """O resultado de conversar(): as rodadas e a resposta final."""

    rodadas: list[Resposta]
    ferramentas_usadas: list[dict]  # {"nome": ..., "entrada": {...}}, na ordem
    completa: bool                  # False se parou no limite de rodadas

    @property
    def final(self) -> Resposta:
        return self.rodadas[-1]

    @property
    def custo_usd(self) -> float:
        return sum(r.custo_usd for r in self.rodadas)


def _para_reenvio(bloco: dict) -> dict | None:
    """O bloco da resposta do jeito que volta para a API na rodada seguinte.

    O raciocínio volta inteiro, com a assinatura: a API exige isso no uso de ferramentas.
    As citações não voltam (não são necessárias), e bloco de texto vazio a API recusa.
    """
    tipo = bloco.get("type")
    if tipo == "text":
        return {"type": "text", "text": bloco["text"]} if bloco.get("text", "").strip() else None
    if tipo == "thinking":
        return {"type": "thinking", "thinking": bloco.get("thinking", ""), "signature": bloco.get("signature", "")}
    if tipo == "redacted_thinking":
        return {"type": "redacted_thinking", "data": bloco["data"]}
    if tipo == "tool_use":
        return {"type": "tool_use", "id": bloco["id"], "name": bloco["name"], "input": bloco.get("input") or {}}
    return bloco


@dataclass
class ClienteLLM:
    modelo: str = "claude-opus-5-5"
    effort: str = "high"
    replay: bool = False
    chave: str | None = None
    pasta_gravacoes: Path = Path("gravacoes")
    arquivo_traces: Path = Path("saidas/traces.jsonl")
    sdk: object | None = None  # nos testes, um cliente falso entra aqui
    max_tokens: int = 32000  # teto da resposta, raciocínio incluído; só se paga o que for gerado
    _trava: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def perguntar(self, conteudo: list[dict], *, sistema: str, etapa: str, documento: str) -> Resposta:
        """Faz a pergunta, ou devolve a resposta gravada se a mesma pergunta já foi feita."""
        chave = self._chave({"modelo": self.modelo, "effort": self.effort, "sistema": sistema, "conteudo": conteudo})
        return self._obter(chave, etapa, documento, lambda: self._chamar_api(conteudo, sistema))

    def conversar(self, pergunta: str, *, sistema: str, ferramentas: list[dict],
                  executar: Callable[[str, dict], list[dict] | str], etapa: str, documento: str,
                  max_rodadas: int = 8) -> Conversa:
        """O agente: a IA pede ferramentas, o código executa, até a IA dar a resposta final.

        Cada rodada depende só das anteriores. Por isso cada uma é gravada à parte, e o
        replay refaz a conversa inteira com as rodadas gravadas, sem chamar a API.
        O cache automático da API guarda o começo da conversa entre uma rodada e outra.
        """
        mensagens: list[dict] = [{"role": "user", "content": [{"type": "text", "text": pergunta}]}]
        rodadas: list[Resposta] = []
        usadas: list[dict] = []
        for _ in range(max_rodadas):
            pedido = {"system": sistema, "tools": ferramentas, "messages": mensagens}
            chave = self._chave({"modelo": self.modelo, "effort": self.effort, "pedido": pedido})
            resposta = self._obter(chave, etapa, documento, lambda p=pedido: self._chamar_api_conversa(p))
            rodadas.append(resposta)
            pedidos = [b for b in resposta.blocos if b.get("type") == "tool_use"]
            if resposta.parada != "tool_use" or not pedidos:
                return Conversa(rodadas=rodadas, ferramentas_usadas=usadas, completa=True)
            reenvio = [b for b in map(_para_reenvio, resposta.blocos) if b is not None]
            resultados = []
            for b in pedidos:
                entrada = b.get("input") or {}
                usadas.append({"nome": b["name"], "entrada": entrada})
                try:
                    conteudo = executar(b["name"], entrada)
                    resultados.append({"type": "tool_result", "tool_use_id": b["id"], "content": conteudo})
                except (KeyError, ValueError, TypeError) as erro:  # entrada errada: a IA vê o erro e corrige
                    resultados.append({"type": "tool_result", "tool_use_id": b["id"], "is_error": True,
                                       "content": f"Erro na ferramenta {b['name']}: {erro}"})
            mensagens = [*mensagens, {"role": "assistant", "content": reenvio}, {"role": "user", "content": resultados}]
        return Conversa(rodadas=rodadas, ferramentas_usadas=usadas, completa=False)

    def _obter(self, chave: str, etapa: str, documento: str, chamar: Callable[[], Resposta]) -> Resposta:
        """A resposta gravada, se existir; senão, chama a API e grava."""
        arquivo = Path(self.pasta_gravacoes) / f"{etapa}_{Path(documento).stem}_{chave}.json"
        if arquivo.exists():
            resposta = Resposta(**json.loads(arquivo.read_text(encoding="utf-8")))
            resposta.gravada = True
        elif self.replay:
            raise SemGravacao(f"Sem resposta gravada para '{etapa}' de {documento}. Rode sem --replay, com a chave no .env.")
        else:
            resposta = chamar()
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(json.dumps(asdict(resposta), ensure_ascii=False, indent=1), encoding="utf-8")
        self._registrar(resposta, etapa, documento)
        return resposta

    @staticmethod
    def _chave(pedido: dict) -> str:
        bruto = json.dumps(pedido, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:16]

    def _chamar_api(self, conteudo: list[dict], sistema: str) -> Resposta:
        sdk = self.sdk or self._criar_sdk()
        inicio = time.perf_counter()
        # Em fluxo (stream): com raciocínio, uma resposta pode demorar.
        with sdk.messages.stream(model=self.modelo, max_tokens=self.max_tokens, system=sistema,
                                 messages=[{"role": "user", "content": conteudo}],
                                 output_config={"effort": self.effort}) as fluxo:
            mensagem = fluxo.get_final_message()
        return self._resposta(mensagem, inicio, so_texto=True)

    def _chamar_api_conversa(self, pedido: dict) -> Resposta:
        sdk = self.sdk or self._criar_sdk()
        inicio = time.perf_counter()
        # cache_control no topo do pedido: o cache automático marca o fim da conversa a cada rodada.
        argumentos = dict(model=self.modelo, max_tokens=self.max_tokens, system=pedido["system"], tools=pedido["tools"],
                          messages=pedido["messages"], output_config={"effort": self.effort})
        try:
            with sdk.messages.stream(**argumentos, extra_body={"cache_control": {"type": "ephemeral"}}) as fluxo:
                mensagem = fluxo.get_final_message()
        except Exception as erro:
            # Se a plataforma não aceitar o cache automático (ex.: Bedrock), segue sem cache: só fica mais caro.
            if "cache_control" not in str(erro):
                raise
            with sdk.messages.stream(**argumentos) as fluxo:
                mensagem = fluxo.get_final_message()
        return self._resposta(mensagem, inicio, so_texto=False)

    def _resposta(self, mensagem, inicio: float, *, so_texto: bool) -> Resposta:
        uso = mensagem.usage
        blocos = [b.model_dump(mode="json", exclude_none=True) for b in mensagem.content
                  if not so_texto or b.type == "text"]
        return Resposta(
            blocos=blocos,
            modelo=self.modelo,
            tokens_entrada=uso.input_tokens,
            tokens_saida=uso.output_tokens,
            tokens_cache=getattr(uso, "cache_read_input_tokens", 0) or 0,
            tokens_cache_escrita=getattr(uso, "cache_creation_input_tokens", 0) or 0,
            segundos=round(time.perf_counter() - inicio, 2),
            parada=getattr(mensagem, "stop_reason", "") or "",
        )

    def _criar_sdk(self):
        if not self.chave:
            raise RuntimeError("Defina ANTHROPIC_API_KEY no .env, ou rode com --replay para usar as respostas gravadas.")
        import anthropic

        # Mais tentativas que o padrão (2): limite de taxa (429) e sobrecarga (529) passam sozinhos.
        return anthropic.Anthropic(api_key=self.chave, max_retries=6)

    def _registrar(self, r: Resposta, etapa: str, documento: str) -> None:
        linha = {
            "momento": datetime.now(UTC).isoformat(timespec="seconds"),
            "etapa": etapa,
            "documento": documento,
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": r.modelo,
            "gen_ai.usage.input_tokens": r.tokens_entrada,
            "gen_ai.usage.output_tokens": r.tokens_saida,
            "tokens_cache_lidos": r.tokens_cache,
            "tokens_cache_gravados": r.tokens_cache_escrita,
            "parada": r.parada,
            "custo_usd": 0.0 if r.gravada else round(r.custo_usd, 6),  # quanto esta execução gastou
            "custo_original_usd": round(r.custo_usd, 6),                # quanto a chamada custou quando foi feita
            "duracao_s": r.segundos,
            "gravada": r.gravada,
        }
        arquivo = Path(self.arquivo_traces)
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        with self._trava, arquivo.open("a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
