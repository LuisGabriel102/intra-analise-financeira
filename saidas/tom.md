# Tom do texto da administração: ML tradicional comparado com a IA

Gerado em 16/11/2026 10:49. Os rótulos da IA são a referência desta comparação, e não a verdade.

## Light.pdf

170 frases do texto da administração (p. 2 a 14). A IA (claude-opus-5-5) rotulou 170: 24 positivas, 117 neutras e 29 negativas.

| Método | Concorda com a IA | F1 médio | Kappa | Negativas achadas | Tom do documento | Custo e tempo |
|---|---|---|---|---|---|---|
| IA, frase a frase | referência | — | — | — | neutro | US$ 0,0956 em 18 s, cerca de US$ 0,00056 por frase |
| Léxico de finanças, sem treino | 65% | 0,50 | 0,23 | 13 de 29 | neutro | US$ 0, menos de 1 s |
| TF-IDF e regressão logística (validação cruzada em 5 partes) | 72% | 0,49 | 0,31 | 12 de 29 | neutro | US$ 0, 226 ms para treinar e prever |
| Sempre a classe mais comum (piso) | 69% | 0,27 | 0,00 | 0 de 29 | neutro | US$ 0 |

Tom do documento inteiro, na análise qualitativa (a IA lendo o texto todo): **negativo**.

**Por que os dois tons não batem.** A contagem dá o mesmo peso a toda frase. Aqui são 29 negativas e 24 positivas em 170: a diferença é 2,9% das frases. A regra só sai do neutro a partir de 10%. A leitura do texto inteiro pesa cada frase pelo que ela diz. Um fato grave pode decidir o tom sozinho, e muitas frases leves podem não decidir.

Os termos que mais puxam cada rótulo no modelo clássico, treinado com todas as frases:

- negativo: milhoes, abaixo, faturado, totalizou, totalizou milhoes, receita
- positivo: covenants, aumento, deci, feci, acima apurado, milhoes resultado
- neutro: servicos, projetos, investimentos, social, gestao, qualidade

Termos que são palavras de tom do léxico: 0 de 6 em negativo e 0 de 6 em positivo. Com 170 frases, é sinal de que o modelo aprendeu mais o assunto das frases do que o tom delas.

### Onde o léxico discorda da IA

O léxico discorda da IA em 60 das 170 frases. Aqui vão 6, com as negativas primeiro. Todas estão em saidas/tom.json.

| Página | IA | Léxico | Clássico | Frase |
|---|---|---|---|---|
| 2 | negativo | neutro | negativo | O consumo faturado de energia do Rio de Janeiro em 2022 permaneceu em níveis inferiores ao pré-Covid. |
| 2 | negativo | neutro | neutro | Quando observamos a trajetória de longo-prazo, constatamos que o consumo faturado de baixa tensão da Light em 2022 foi 12,5% menor que em 2013. |
| 2 | negativo | neutro | neutro | E as taxas de juros no Brasil voltaram para um patamar muito alto; a expectativa é que permaneçam nesse patamar. |
| 3 | negativo | positivo | neutro | Porém, não há garantia de que a Companhia terá êxito nas estratégias, visto que parte relevante dos elementos das estratégias não está sob o controle da Administração da Companhia, existindo, portanto, uma incerteza… |
| 7 | negativo | neutro | neutro | O índice de arrecadação total média móvel 12 meses em dezembro/22 atingiu 96,0%, 1,4 p.p. abaixo da apresentada em dezembro/21 (97,4%). |
| 8 | negativo | neutro | negativo | Em 2022, o EBITDA CVM1 da distribuidora foi de R$1.817 milhões, uma redução de R$2.996 milhões em relação aos R$1.179 milhões apurados em 2021. |

## Documentos sem texto da administração

Brasal.pdf, Millet.pdf: não se aplica. A análise qualitativa também diz que o tom não se aplica.

## Como ler

- **Concorda com a IA** é a fração de frases com o mesmo rótulo que a IA deu. O **kappa** desconta o acerto por acaso: 0 é acaso, 1 é concordância total.
- O **piso** chuta sempre o rótulo mais comum. Um método só ajuda se passar dele.
- **Negativas achadas** conta quantas frases negativas da IA o método também achou. Para quem empresta dinheiro, deixar passar uma frase negativa custa mais do que errar uma neutra.
- O modelo clássico aprende com as frases de um documento só. O número serve para comparar métodos, e não para prometer acerto em outros documentos.
- O léxico não entende negação ("não houve perdas") nem contexto ("aumento" de receita e "aumento" de perdas).
- Em produção, um modelo clássico treinado com rótulos da IA em milhares de frases pode fazer a triagem a custo quase zero, e a IA fica para as frases em que ele tem pouca certeza.
