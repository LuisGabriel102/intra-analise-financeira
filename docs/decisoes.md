# Registro de decisões

Uma decisão por parágrafo: o que foi decidido e por quê. Este registro alimenta o README e a apresentação.

## 1. Pipeline fixo, com papéis separados

O caminho é o mesmo para todo documento: ler o PDF, achar as páginas certas, extrair, conferir, responder e redigir. Cada etapa grava o seu resultado em disco, o que permite auditar, repetir uma etapa só e testar. A autonomia de agente fica só onde há incerteza, nas perguntas livres. Onde há regra, nos números, o caminho é determinístico.

## 2. A IA lê e aponta; o Python calcula e confere

A IA nunca faz conta. Margem, variação, EBITDA calculado, dívida líquida e alavancagem saem de `calculos.py`, e as conferências saem de `validacao.py`. Um modelo de linguagem erra conta e sinal de um jeito que parece certo, e código é auditável e testável. Foi conferindo em código que apareceu o EBITDA da Light publicado sem o sinal de menos.

## 3. A prova de cada número vem da API de citações (em teste em 13/11/2026)

A IA responde "campo: valor" e cita o documento, seguindo o padrão da documentação oficial da Anthropic. Quem recorta o trecho do PDF é a API, e não a IA, então o trecho não tem como ser inventado. O código confere se o número está no trecho, com o mesmo sinal. Há dois motivos a mais. A saída estruturada não pode ser usada junto com as citações (a API recusa), e ela também não existe no Claude do Microsoft Foundry hospedado no Azure, enquanto as citações existem. Uma ressalva: a citação prova que o número está na linha citada, mas não que é a coluna certa. Isso fica com as regras cruzadas e com o gabarito.

## 4. Sem framework de agentes

A orquestração é Python puro. Com cinco etapas fixas, um framework acrescentaria dependência e código para explicar, sem ganho. Os papéis de agente (extrator, analista, validador, perguntas, redator) continuam separados, cada um num arquivo.

## 5. O validador só sinaliza, e as demonstrações valem mais que o texto

Nenhum valor é corrigido em silêncio. Quando o relatório da administração e as demonstrações divergem, o número das demonstrações vai para a tabela, e o do relatório vira alerta. O próprio auditor da Light avisa que não opina sobre o relatório da administração (p. 115), e é lá que estão os erros de sinal.

## 6. Dinheiro em reais dentro do código

As tabelas vêm em R$ mil e os textos em R$ milhões. Dentro do código, tudo vira reais (`numeros.em_reais`), para nunca misturar escalas. O relatório mostra em R$ milhões.

## 7. Variação com base negativa

A variação é (atual − anterior) ÷ |anterior|. Assim, um prejuízo que aumenta aparece como piora. Quando o valor troca de sinal, como de lucro para prejuízo, a variação em % não tem sentido e aparece como "n/a".

## 8. Nenhuma regra feita para uma empresa

As regras valem para qualquer demonstração brasileira. Os casos dos três PDFs entram nos testes, e não no código.
