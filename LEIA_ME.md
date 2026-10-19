# Corpus centralizado para a etapa de representação e indexação

## Resultado da unificação

- Coleta antiga (crawler_receitas(1).zip): 45.107 registros lidos.
- Coleta com sites novos (saida_coleta(3).zip): 41.498 registros lidos.
- Total de entrada: 86.605 registros.
- Removidos por URL repetida: 2.672 registros.
- Corpus final: 83.933 documentos com URLs distintas, provenientes de 10 sites.

A contagem é obtida dos JSONL, não dos relatórios das execuções. O relatório antigo registra 42.288, mas seus arquivos contêm 45.107 registros. O relatório da coleta nova registra 41.498 e ainda traz `finish_reason: running`; o conteúdo disponível no ZIP contém exatamente essa quantidade. Esse relatório é um checkpoint, não prova encerramento normal.

## Arquivos necessários para a parte 2

- `corpus.jsonl`: entrada principal da indexação. Cada linha é um documento JSON com URL, título, texto, site, campos originais da coleta, `doc_id` sequencial e `provenance` indicando ZIP, arquivo e linha de origem. Não depende de banco de dados.
- `manifesto.json`: contagens, identificação das duas entradas, regras de deduplicação e SHA-256 do corpus. Use-o para documentar e conferir a versão do conjunto.
- `inventario_fontes.csv`: distribuição dos documentos por site e origem, antes/depois da remoção de URLs repetidas.

## Arquivos de auditoria e reprodução

- `duplicatas_removidas.csv`: uma linha por registro descartado, com localização da versão removida e da versão mantida.
- `validacao.json`: conferência independente da contagem, URLs distintas, IDs e hash do corpus produzido.
- `unificar.py`: código-fonte que reproduz a unificação a partir dos dois ZIPs originais; utiliza somente a biblioteca padrão do Python.
- `relatorios_originais/`: cópias dos relatórios e configurações disponíveis, preservadas para rastreabilidade. A pasta coleta_1 representa o crawler antigo e coleta_2 os sites novos. Não some seus indicadores como se fossem de uma única execução.

## Regra aplicada

A chave é o campo `url`, retirando somente espaços nas extremidades. Na repetição da mesma URL, é mantido o registro com `fetched_at` mais recente. No empate, priorizam-se campos preenchidos, maior tamanho de texto e primeira ocorrência. Caminhos, queries, HTTP/HTTPS, variantes com www e barras finais diferentes continuam sendo URLs diferentes. O campo canonical não substitui essa chave, pois isso exigiria uma regra adicional de equivalência de URLs.

Os valores originais de conteúdo e hashes de coleta são preservados. Campos de ingredientes e instruções que não existiam na coleta antiga continuam ausentes; não foram fabricados nem extraídos nesta preparação. O campo `content_sha256` pertence ao crawler de origem, cujos critérios diferem entre as versões: não use esse campo como se fosse um hash homogêneo entre ambas as coletas.

A remoção realizada é por URL repetida. Não foi aplicada deduplicação por texto nem reclassificação das páginas como receitas. Assim, 83.933 é o número de documentos distintos por URL, não uma contagem de receitas únicas validadas. A limpeza textual, avaliação de conteúdo, tokenização, stopwords, stemming, índice invertido e experimentos pertencem à próxima etapa.

## Como usar

Extraia o ZIP e mantenha a pasta completa. A etapa 2 deve ler o arquivo `corpus.jsonl` linha a linha em UTF-8. Não é necessário executar o crawler novamente nem instalar as bibliotecas dele. Não abra e salve esse JSONL pelo Excel, pois ele não é uma planilha.

Para reproduzir a unificação (a pasta de saída não pode existir):

```powershell
python unificar.py "C:\dados\crawler_receitas(1).zip" "C:\dados\saida_coleta(3).zip" --saida "C:\dados\base_reproduzida"
```

Esse comando recria o corpus, manifesto, inventário, auditoria e cópias dos relatórios. O campo de data de geração do manifesto muda. O arquivo validacao.json deste pacote foi gerado na conferência independente posterior à unificação.

Os ZIPs originais permanecem como cópias de segurança e não precisam ser incluídos novamente no trabalho de indexação. Para integrar o relatório parcial ao Overleaf, ainda será necessário o principal.tex atualizado e, para o cronograma nominal, os integrantes e o prazo de conclusão.
