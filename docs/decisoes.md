# Registro de decisões

Uma decisão por parágrafo: o que foi decidido e por quê. Este registro alimenta o README e a apresentação.

## 1. Pipeline fixo, com papéis separados

O caminho é o mesmo para todo documento: ler o PDF, achar as páginas certas, extrair, conferir, responder e redigir. Cada etapa grava o seu resultado em disco, o que permite auditar, repetir uma etapa só e testar. A autonomia de agente fica só onde há incerteza, nas perguntas livres. Onde há regra, nos números, o caminho é determinístico.

## 2. A IA lê e aponta; o Python calcula e confere

A IA nunca faz conta. Margem, variação, EBITDA calculado, dívida líquida e alavancagem saem de `calculos.py`, e as conferências saem de `validacao.py`. Um modelo de linguagem erra conta e sinal de um jeito que parece certo, e código é auditável e testável. Foi conferindo em código que apareceu o EBITDA da Light publicado sem o sinal de menos.

## 3. A prova de cada número vem da API de citações

A IA responde "campo: valor" e cita o documento, seguindo o padrão da documentação oficial da Anthropic. Cada página vai como um documento, e cada linha da página é um bloco que pode ser citado, então a citação aponta a linha exata da tabela. Num teste com 4 páginas da Light, em 13/11/2026, os 10 campos voltaram com a página e a linha certas, o "não encontrado" veio certo, e a chamada custou US$ 0,07 em 12 segundos. Quem recorta o trecho do PDF é a API, e não a IA, então o trecho não tem como ser inventado. O código confere se o número está no trecho, com o mesmo sinal. Há dois motivos a mais. A saída estruturada não pode ser usada junto com as citações (a API recusa), e ela também não existe no Claude do Microsoft Foundry hospedado no Azure, enquanto as citações existem. Uma ressalva: a citação prova que o número está na linha citada, mas não que é a coluna certa. Isso fica com as regras cruzadas e com o gabarito.

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

## 9. Respostas da IA gravadas

Toda resposta real da IA fica gravada em `gravacoes/`, com a pergunta inteira como chave. A mesma pergunta não é paga duas vezes, e o modo `--replay` roda a solução inteira só com as gravações, sem chave e sem custo. É assim que o avaliador consegue rodar tudo, e é assim que os testes nunca chamam a IA de verdade.

## 10. Dois tipos de alerta: o que o código confere e o que a IA aponta

Os alertas de regra (V3 a V16) são conferidos em Python, com os dois valores e as páginas. As observações da IA também entram no relatório, porque ela vê coisas que nenhuma regra previu, mas com outro rótulo: vêm com citação, e não foram conferidas em código. Na rodada real de 13/11/2026, a IA apontou sozinha 19 incoerências nos três documentos. Mas ela não apontou a mais grave, o EBITDA da Light publicado sem o sinal de menos: quem pegou foi a regra V7, em código. É o argumento central da solução.

## 11. Escala da página e escala do documento

Nas notas explicativas, o aviso "(Em milhares de reais)" costuma aparecer só na primeira página. A página que não avisa usa a escala mais comum do documento. Usar a escala da última página que avisou seria pior: uma tabela em milhões no meio das notas contaminaria todas as páginas seguintes. O erro apareceu na primeira rodada real (a dívida líquida da Light saía em reais, e não em milhares) e virou teste.

## 12. As páginas do analista: prioridade e orçamento

O analista não lê o PDF inteiro. O roteamento dá uma prioridade a cada página: primeiro o relatório da administração; depois o parecer do auditor, o contexto operacional, a continuidade, os eventos subsequentes, as aquisições, as vendas de ativos e os segmentos; depois os riscos e as cláusulas de dívida; o resto das notas só entra se couber. O orçamento é de 90 mil caracteres por documento, então o custo não cresce com o tamanho do PDF: a Brasal e a Millet vão quase inteiras, e a Light vai em 32 das 124 páginas. Na mesma prioridade, entra antes a página que fala mais do assunto, porque uma menção de passagem pesa menos que a nota inteira. Um caso real mudou a regra: na Brasal, "(não auditado)" é o rótulo das colunas de 2021 em quase todas as notas, e não um assunto; por isso pesa pouco e não puxa a página sozinho. As tabelas ficam de fora, porque os números já vêm da extração.

## 13. O analista escreve com as palavras dele, e o código confere

Na análise qualitativa, a IA precisa escrever frases, e não copiar números. Por isso o código confere duas coisas em cada frase. A primeira é o trecho: toda frase vem com a citação da API, e a frase sem trecho aparece marcada no relatório. A segunda são os números: cada número da frase precisa estar no trecho citado ou no resumo de números já conferidos pela solução, com 1% de folga para arredondamento ("R$ 5,7 bilhões" bate com "5.672.203" em milhares). O número que não bate fica marcado como "sem fonte conferida". Três regras de leitura vão no pedido, porque são os erros mais prováveis: guidance segue a definição da decisão 19; problema de um cliente não é problema da empresa (na Light, a recuperação judicial citada é da SuperVia); texto padrão do parecer não é fato da empresa. Se há relatório da administração quem decide é o código, pelo roteamento, e não a IA.

## 14. O agente de perguntas usa ferramentas, e a fonte vem da API

A autonomia de agente fica nas perguntas livres, como diz a decisão 1. O agente tem três ferramentas: os indicadores conferidos, a análise qualitativa e uma busca nas páginas dos PDFs. Ele decide o que chamar, e pode chamar várias de uma vez. As ferramentas devolvem o resultado como "resultado de busca" da API, com a citação ligada. Assim, cada frase da resposta final volta com o documento, as páginas e o trecho exato, sem a IA escrever a fonte. Os números chegam prontos, com o rótulo "calculado pela solução" quando for o caso: o agente compara, mas não faz conta. A conversa tem limite de 8 rodadas, e o raciocínio da IA volta inteiro para a API a cada rodada, como a API exige no uso de ferramentas. Cada rodada é gravada à parte, então o replay refaz a conversa inteira sem chamar a API.

## 15. Cache automático nas perguntas

Cada rodada do agente reenvia a conversa anterior inteira. Com o cache automático da API, o começo da conversa é lido do cache a US$ 0,20 por milhão de tokens, em vez de US$ 4. Se a plataforma não aceitar o cache automático, a conversa segue sem ele, só mais cara. Medido na rodada real de 13/11: a 3ª rodada leu do cache o que a 2ª gravou (9.934 tokens na pergunta 4), mas a 2ª rodada nunca leu a 1ª. Nas perguntas de 2 rodadas, o cache só custou a gravação, 25% mais cara que a entrada comum. No saldo daquela rodada, o cache custou cerca de US$ 0,04 a mais do que economizou. Continua ligado porque as perguntas livres e as comparações entre empresas passam de 2 rodadas, e aí ele compensa. Os traces guardam os tokens lidos e gravados de cada rodada, então essa conta fica medida, e não suposta. O mesmo vale para o limite de taxa: o cliente tenta de novo até 6 vezes, e o que já deu certo fica gravado, então rodar de novo continua de onde parou.

## 16. Busca por palavra, sem banco de vetores

São 3 documentos e 217 páginas com texto. A busca BM25, escrita em poucas linhas e sem biblioteca, acha "covenants", "risco de liquidez" e "continuidade operacional" na página certa, e dá para explicar por que uma página ganhou. Um caso real mostrou um ajuste necessário: buscando "recuperação judicial", a melhor página era uma nota da Brasal sobre recuperação de créditos e decisão judicial. Contando também os pares de palavras vizinhas, as primeiras passaram a ser as p. 48 e 49 da Light, onde está o caso da SuperVia. Em produção, com milhares de documentos, o lugar disso é o Azure AI Search, com busca por palavra, por vetor e reranqueamento.

## 17. O relatório é montado em código

A IA não escreve o relatório. A tabela, os números, os alertas e o resumo executivo saem dos dados conferidos, então o relatório não tem como inventar um número. O texto da IA só entra onde ela já trabalhou com citação: a análise qualitativa e as respostas, sempre com a página ao lado. Cada célula da tabela tem um selo: informado e conferido, calculado pela solução, com alerta, ou não encontrado. Todo texto que veio do PDF ou da IA passa por escape, porque texto de PDF dentro de HTML é uma porta para injeção.

## 18. A avaliação também confere a análise e as respostas

A extração é avaliada número a número contra o gabarito. A análise qualitativa e as 5 respostas não têm um valor exato, então a checagem é aproximada, por palavras: o tom certo, o guidance "não encontrado", os fatos que precisam aparecer (como a compra da Alibra no meio de 2021) e o erro que não pode aparecer (a recuperação judicial da cliente atribuída à Light). É grosseira de propósito: pega o erro grande, e não dá nota de redação. Nas armadilhas, uma observação da IA só conta se falar do assunto da armadilha, e não só por cair na mesma página.

## 19. Uma definição de guidance, a mesma para os dois agentes

Na primeira rodada real, a análise marcou como guidance a compensação de crédito fiscal da Brasal ("o restante de 38,9% deverá acontecer até julho de 2023") e as metas do balanço social da Light (reduzir reclamações em 10%, zerar acidentes). Ao mesmo tempo, a resposta da pergunta 5 dizia que nenhuma empresa dá guidance financeiro. O relatório se contradizia. A causa era a regra antiga: "compromisso com prazo" deixava passar qualquer prazo. Agora guidance é a projeção ou a meta da administração para o desempenho financeiro ou operacional do próximo período, como receita, margem, EBITDA, investimentos ou alavancagem. Meta social, prazo de uma operação ou de uma compensação de crédito e decisão de regulador entram como perspectiva. A mesma frase vai no pedido do analista e no do agente de perguntas, para os dois não discordarem.

## 20. A busca em todas as empresas traz páginas de cada uma

Na pergunta 4, o agente buscou "risco de taxa de juros" em todas as empresas e recebeu as 3 melhores páginas do conjunto, nenhuma da Brasal. Concluiu que a Brasal não cita juros, mas a nota 26 da Brasal (p. 49) cita. A busca com "todas" agora devolve as 2 melhores páginas de cada empresa. O agente também ganhou uma regra: só diz que uma empresa não cita um tema depois de buscar nas páginas dela. No analista, risco e evento passaram de 6 para até 10 linhas, porque as três empresas tinham batido no limite de 6, e a pergunta 4 depende da lista completa.

## 21. Os números das respostas também são conferidos

A régua da análise qualitativa passou a valer para as respostas: cada número precisa estar num trecho citado pela própria resposta, ou na pergunta. Na rodada real, a resposta da pergunta 5 trazia "61,1%" e "38,9%" sem citação. Os dois números estão na p. 28 da Brasal, mas o leitor não tinha como saber. Agora o relatório marca a resposta, e a avaliação a reprova. Pelo mesmo motivo, o item da análise que cita um valor que a conferência em código marcou com erro ganha um aviso: na Light, a frase da administração com o EBITDA de R$ 1.180 milhões aparece com o alerta do sinal trocado.

## 22. O analista recebe o que já foi achado, e só aponta o que é novo

A seção de alertas da primeira rodada repetia achados. O EBITDA da distribuidora, a troca de MWm por MWh e o ano do covenant da Light apareciam uma vez pela extração e outra pela análise, porque o analista não sabia o que a extração já tinha apontado. Agora o pedido do analista leva essa lista, com os avisos da conferência em código e as observações da extração, e pede só o que for novo. No relatório, uma rede de segurança esconde a observação da análise que fala de uma página já apontada e não traz nenhum número novo. Observação sem número fica, porque aí não dá para saber se repete.
