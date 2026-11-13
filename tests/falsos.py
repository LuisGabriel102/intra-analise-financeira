"""Um SDK falso da Anthropic. Os testes nunca chamam a IA de verdade."""


class _Bloco:
    def __init__(self, dados: dict):
        self._dados = dados
        self.type = dados["type"]

    def model_dump(self) -> dict:
        return self._dados


class _Uso:
    input_tokens = 1000
    output_tokens = 200
    cache_read_input_tokens = 0


class _Mensagem:
    def __init__(self, blocos: list[dict]):
        self.content = [_Bloco(b) for b in blocos]
        self.usage = _Uso()


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
