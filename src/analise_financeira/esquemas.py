"""O formato dos dados que a solução grava em disco (JSON), validado pelo Pydantic."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Evidencia(BaseModel):
    pagina: int = Field(description="Página do PDF, contando a capa como 1")
    trecho: str = Field(description="As linhas do PDF que a API citou, literalmente")


class Ocorrencia(BaseModel):
    """Um lugar do documento onde o campo aparece."""

    texto: str                      # como a IA copiou: "(1.910.411)", "R$1.180 milhões"
    numero: float | None = None     # o número lido pelo código, na unidade do documento
    unidade: str = ""               # "R$ mil", "R$ milhões", "%", "x" ou "" (texto)
    valor_reais: float | None = None  # o mesmo valor em reais, para comparar escalas
    fonte: str = ""                 # tipo da página citada: dre, balanco, dfc, dmpl, relatorio_adm, notas...
    evidencias: list[Evidencia] = []
    conferido: bool = False         # o número está no trecho citado, com o mesmo sinal


class Campo(BaseModel):
    status: Literal["encontrado", "nao_encontrado", "sem_evidencia", "sem_resposta"]
    principal: Ocorrencia | None = None  # a ocorrência que vai para a tabela
    ocorrencias: list[Ocorrencia] = []   # todas, inclusive as que divergem


class Uso(BaseModel):
    modelo: str
    tokens_entrada: int = 0
    tokens_saida: int = 0
    custo_usd: float = 0.0
    segundos: float = 0.0
    gravada: bool = False  # True quando veio de gravacoes/, sem chamar a API


class Extracao(BaseModel):
    documento: str
    paginas_enviadas: list[int]
    campos: dict[str, Campo]
    observacoes: list[Ocorrencia] = []  # incoerências que a própria IA notou, com citação
    uso: Uso
