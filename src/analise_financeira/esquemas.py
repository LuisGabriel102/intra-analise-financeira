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
    tokens_entrada: int = 0  # inclui os lidos e os gravados no cache
    tokens_saida: int = 0
    custo_usd: float = 0.0   # quanto a chamada custou quando foi feita (no replay, esta execução não paga nada)
    segundos: float = 0.0
    gravada: bool = False    # True quando veio de gravacoes/, sem chamar a API
    tokens_cache_lidos: int = 0


class Extracao(BaseModel):
    documento: str
    paginas_enviadas: list[int]
    campos: dict[str, Campo]
    observacoes: list[Ocorrencia] = []  # incoerências que a própria IA notou, com citação
    uso: Uso


# ------------------------------------------------------------------ análise qualitativa


class Item(BaseModel):
    """Uma afirmação da análise qualitativa, com os trechos do PDF que a sustentam."""

    texto: str                         # escrito pela IA, com as palavras dela
    evidencias: list[Evidencia] = []   # recortados pela API (citação), conferidos pelo código
    fontes: list[str] = []             # tipo das páginas citadas: relatorio_adm, notas, auditor, outros
    conferido: bool = False            # tem pelo menos um trecho citado e conferido
    numeros_sem_fonte: list[str] = []  # números do texto que não estão nos trechos nem nos números da solução


class AnaliseQualitativa(BaseModel):
    documento: str
    paginas_enviadas: list[int]
    tem_relatorio_administracao: bool   # decidido pelo código: há páginas de relatório da administração
    paginas_administracao: list[int] = []
    motivos: list[Item] = []
    riscos: list[Item] = []
    guidance: list[Item] = []
    guidance_status: Literal["encontrado", "nao_encontrado", "sem_resposta"] = "sem_resposta"
    perspectivas: list[Item] = []
    eventos: list[Item] = []
    comparabilidade: list[Item] = []
    tom: Literal["positivo", "neutro", "negativo", "nao_aplicavel"] | None = None
    justificativa_tom: Item | None = None
    observacoes: list[Item] = []        # incoerências que a IA notou, com citação
    nao_encontrados: list[str] = []     # campos que a IA declarou "não encontrado"
    completa: bool = True               # False se a resposta foi cortada no limite de tamanho
    uso: Uso


# ------------------------------------------------------------------ perguntas


class Fonte(BaseModel):
    documento: str           # "Light.pdf"
    paginas: list[int]
    titulo: str              # o título do resultado citado
    trecho: str              # o texto citado, literal (cited_text)
    calculado: bool = False  # o trecho é um número calculado pela solução, e não texto do PDF


class RespostaPergunta(BaseModel):
    numero: int | None = None    # 1 a 5 nas perguntas obrigatórias
    pergunta: str
    texto: str                   # a resposta, com as marcas [1], [2] que levam às fontes
    fontes: list[Fonte] = []
    ferramentas: list[str] = []  # as ferramentas que o agente usou, na ordem
    completa: bool = True        # False se o agente parou no limite de rodadas
    rodadas: int = 0
    uso: Uso
