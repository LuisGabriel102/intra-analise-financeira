"""Chamada ao Claude, com gravação das respostas, modo replay e registro de custo.

- Toda resposta real fica gravada em gravacoes/. A mesma pergunta não é paga duas vezes.
- No modo replay, a solução roda só com as respostas gravadas: sem chave e sem custo.
- Cada chamada vira uma linha em saidas/traces.jsonl, com modelo, tokens, custo e tempo.
  Os nomes dos campos seguem as convenções GenAI do OpenTelemetry, para irem direto
  ao Application Insights em produção.

O Opus 5.5 não aceita temperature e não deixa desligar o raciocínio. A estabilidade
vem do formato fixo, da conferência em código e das respostas gravadas.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
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


@dataclass
class Resposta:
    blocos: list[dict]  # blocos de texto da resposta, com as citações
    modelo: str
    tokens_entrada: int
    tokens_saida: int
    tokens_cache: int = 0
    segundos: float = 0.0
    gravada: bool = False  # veio de gravacoes/, sem chamar a API

    @property
    def custo_usd(self) -> float:
        entrada, saida, cache = PRECOS.get(self.modelo, (0.0, 0.0, 0.0))
        return (self.tokens_entrada * entrada + self.tokens_saida * saida + self.tokens_cache * cache) / 1e6


@dataclass
class ClienteLLM:
    modelo: str = "claude-opus-5-5"
    effort: str = "high"
    replay: bool = False
    chave: str | None = None
    pasta_gravacoes: Path = Path("gravacoes")
    arquivo_traces: Path = Path("saidas/traces.jsonl")
    sdk: object | None = None  # nos testes, um cliente falso entra aqui
    max_tokens: int = 16000
    _trava: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def perguntar(self, conteudo: list[dict], *, sistema: str, etapa: str, documento: str) -> Resposta:
        """Faz a pergunta, ou devolve a resposta gravada se a mesma pergunta já foi feita."""
        chave = self._chave(sistema, conteudo)
        arquivo = Path(self.pasta_gravacoes) / f"{etapa}_{Path(documento).stem}_{chave}.json"
        if arquivo.exists():
            resposta = Resposta(**json.loads(arquivo.read_text(encoding="utf-8")))
            resposta.gravada = True
        elif self.replay:
            raise SemGravacao(f"Sem resposta gravada para '{etapa}' de {documento}. Rode sem --replay, com a chave no .env.")
        else:
            resposta = self._chamar_api(conteudo, sistema)
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            arquivo.write_text(json.dumps(asdict(resposta), ensure_ascii=False, indent=1), encoding="utf-8")
        self._registrar(resposta, etapa, documento)
        return resposta

    def _chave(self, sistema: str, conteudo: list[dict]) -> str:
        bruto = json.dumps({"modelo": self.modelo, "effort": self.effort, "sistema": sistema, "conteudo": conteudo},
                           sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:16]

    def _chamar_api(self, conteudo: list[dict], sistema: str) -> Resposta:
        sdk = self.sdk or self._criar_sdk()
        inicio = time.perf_counter()
        # Em fluxo (stream): com raciocínio, uma resposta pode demorar.
        with sdk.messages.stream(model=self.modelo, max_tokens=self.max_tokens, system=sistema,
                                 messages=[{"role": "user", "content": conteudo}],
                                 output_config={"effort": self.effort}) as fluxo:
            mensagem = fluxo.get_final_message()
        uso = mensagem.usage
        return Resposta(
            blocos=[b.model_dump() for b in mensagem.content if b.type == "text"],
            modelo=self.modelo,
            tokens_entrada=uso.input_tokens,
            tokens_saida=uso.output_tokens,
            tokens_cache=getattr(uso, "cache_read_input_tokens", 0) or 0,
            segundos=round(time.perf_counter() - inicio, 2),
        )

    def _criar_sdk(self):
        if not self.chave:
            raise RuntimeError("Defina ANTHROPIC_API_KEY no .env, ou rode com --replay para usar as respostas gravadas.")
        import anthropic

        return anthropic.Anthropic(api_key=self.chave)

    def _registrar(self, r: Resposta, etapa: str, documento: str) -> None:
        linha = {
            "momento": datetime.now(UTC).isoformat(timespec="seconds"),
            "etapa": etapa,
            "documento": documento,
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": r.modelo,
            "gen_ai.usage.input_tokens": r.tokens_entrada,
            "gen_ai.usage.output_tokens": r.tokens_saida,
            "custo_usd": 0.0 if r.gravada else round(r.custo_usd, 6),  # quanto esta execução gastou
            "custo_original_usd": round(r.custo_usd, 6),                # quanto a chamada custou quando foi feita
            "duracao_s": r.segundos,
            "gravada": r.gravada,
        }
        arquivo = Path(self.arquivo_traces)
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        with self._trava, arquivo.open("a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
