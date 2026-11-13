# Análise inteligente de demonstrações financeiras

Lê demonstrações financeiras em PDF, extrai os indicadores com a página e o trecho de onde cada número saiu, confere as contas em código e gera um relatório para o analista.

> Em construção. O README completo (arquitetura, decisões, avaliação, custo, segurança, limitações e caminho para o Azure) entra no fim. As decisões já tomadas estão em [`docs/decisoes.md`](docs/decisoes.md).

## Como rodar

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # no Linux/Mac: .venv/bin/python
.venv/Scripts/python -m analise_financeira analisar --replay   # tudo, com as respostas gravadas: sem chave e sem custo
.venv/Scripts/python -m analise_financeira avaliar             # compara com o gabarito
.venv/Scripts/python -m pytest -q
```

O comando `analisar` faz a extração, a análise qualitativa, as 5 perguntas do desafio e o relatório (`saidas/relatorio.md`). Para uma pergunta livre: `python -m analise_financeira perguntar "Qual empresa tem mais caixa?"`.

Para chamar a IA de verdade, copie `.env.example` para `.env`, preencha a `ANTHROPIC_API_KEY` e rode sem o `--replay`.
