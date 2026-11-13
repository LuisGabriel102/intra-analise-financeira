"""Um SDK falso da Anthropic. Os testes nunca chamam a IA de verdade."""

import copy


class _Bloco:
    def __init__(self, dados: dict):
        self._dados = dados
        self.type = dados["type"]

    def model_dump(self, **_opcoes) -> dict:
        return copy.deepcopy(self._dados)


class _Uso:
    input_tokens = 1000
    output_tokens = 200
    cache_read_input_tokens = 0


class _Mensagem:
    def __init__(self, blocos: list[dict], parada: str = "end_turn"):
        self.content = [_Bloco(b) for b in blocos]
        self.usage = _Uso()
        self.stop_reason = parada


class _Fluxo:
    def __init__(self, mensagem: _Mensagem):
        self._mensagem = mensagem

    def __enter__(self):
        return self

    def __exit__(self, *erro):
        return False

    def get_final_message(self) -> _Mensagem:
        return self._mensagem


class SdkFalso:
    """Devolve sempre os mesmos blocos e conta as chamadas."""

    def __init__(self, blocos: list[dict]):
        self.blocos = blocos
        self.chamadas = 0
        self.ultimo_pedido: dict = {}
        self.messages = self

    def stream(self, **pedido):
        self.chamadas += 1
        self.ultimo_pedido = pedido
        return _Fluxo(_Mensagem([{"type": "thinking", "thinking": "..."}, *self.blocos]))


class SdkRoteiro:
    """Uma resposta diferente a cada chamada, na ordem do roteiro. Guarda cada pedido.

    roteiro: lista de (blocos, parada). Para simular o agente: primeiro "tool_use", depois "end_turn".
    """

    def __init__(self, roteiro: list[tuple[list[dict], str]]):
        self.roteiro = roteiro
        self.pedidos: list[dict] = []
        self.messages = self

    @property
    def chamadas(self) -> int:
        return len(self.pedidos)

    def stream(self, **pedido):
        self.pedidos.append(copy.deepcopy(pedido))
        blocos, parada = self.roteiro[len(self.pedidos) - 1]
        pensamento = {"type": "thinking", "thinking": "pensando", "signature": f"assinatura-{len(self.pedidos)}"}
        return _Fluxo(_Mensagem([pensamento, *blocos], parada))


def fluxo(blocos: list[dict], parada: str = "end_turn") -> _Fluxo:
    """A resposta falsa pronta para devolver em stream(): para SDKs falsos escritos nos próprios testes."""
    return _Fluxo(_Mensagem(blocos, parada))
