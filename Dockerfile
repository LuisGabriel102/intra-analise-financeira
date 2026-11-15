# A solução inteira numa imagem. Roda com as respostas gravadas: sem chave e sem custo.
#
#   docker build -t analise-financeira .
#   docker run --rm analise-financeira                      # replay, comparação de tom e avaliação
#   docker run --rm analise-financeira python -m pytest -q  # os testes
#
# Com a IA de verdade, a chave entra só na hora de rodar, e nunca fica na imagem:
#   docker run --rm --env-file .env analise-financeira python -m analise_financeira analisar
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# As dependências primeiro: esta camada fica em cache enquanto o pyproject.toml não muda.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -e ".[dev]"

COPY . .

# A imagem não precisa de root para rodar.
RUN useradd --create-home analista && chown -R analista /app
USER analista

CMD ["sh", "-c", "python -m analise_financeira analisar --replay && python -m analise_financeira tom --replay && python -m analise_financeira avaliar"]
