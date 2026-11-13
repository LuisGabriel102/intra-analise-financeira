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

## Servidor MCP: os dados para qualquer agente

O comando `mcp` sobe um servidor [MCP](https://modelcontextprotocol.io) com os dados que o `analisar` gravou em `saidas/`. Qualquer agente compatível (Claude Desktop, por exemplo) passa a consultar os indicadores conferidos, os alertas e as páginas dos PDFs. O servidor só lê: não grava nada, não chama a IA e não acessa a rede.

| Ferramenta | O que devolve |
|---|---|
| `listar_empresas` | as empresas, o período, se há relatório da administração e quantos alertas há |
| `obter_indicadores` | cada indicador com o valor informado (página e trecho), o calculado pela solução (à parte, com a fórmula) e os alertas |
| `listar_alertas` | as inconsistências conferidas em código e as observações da IA, com a página |
| `obter_analise_qualitativa` | motivos, riscos, guidance, perspectivas, eventos, comparabilidade e tom, com os trechos citados |
| `buscar_paginas` | as páginas mais relevantes para uma consulta, de uma empresa ou de todas |
| `ler_pagina` | o texto de uma página do PDF, para conferir um trecho |

O relatório também fica disponível como recurso (`relatorio://atual`).

Para usar no Claude Desktop, instale o extra e acrescente o servidor ao `claude_desktop_config.json` (no Windows, em `%APPDATA%\Claude\`), trocando o caminho pelo da sua pasta:

```bash
.venv/Scripts/python -m pip install -e ".[mcp]"
```

```json
{
  "mcpServers": {
    "analise-financeira": {
      "command": "C:\\caminho\\para\\intra-analise-financeira\\.venv\\Scripts\\python.exe",
      "args": ["-m", "analise_financeira", "mcp"]
    }
  }
}
```

Depois de reiniciar o Claude Desktop, pergunte, por exemplo: "Qual a alavancagem da Light? Cite a página e os alertas." ou "Quais inconsistências a Millet tem nas demonstrações?".

