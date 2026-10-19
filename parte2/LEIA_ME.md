# Parte 2: representação e indexação

Código da etapa de representação do buscador de receitas. Não usa banco de dados: o índice invertido é gravado em arquivos binários e de texto próprios.

## Instalação

```powershell
pip install -r requirements.txt
python -c "import nltk; nltk.download('stopwords'); nltk.download('rslp')"
```

Python 3.12. A entrada é o `corpus.jsonl` da pasta acima (gerado na parte 1 por `unificar.py`).

## Ordem de execução

| Passo | Comando | Duração aprox. | Saída |
|---|---|---|---|
| A. Limpeza | `python limpeza.py` | 2 min | `saida/corpus_limpo.jsonl`, `saida/estatisticas_limpeza.json`, `saida/duplicatas_conteudo.csv` |
| Testes | `python testes.py` | 1 min | confere VByte, SPIMI com 1 e N blocos e postings por força bruta |
| C. Índice principal | `python indexar.py --nome principal --granularidade campos --documentos` | 1,5 min | `saida/indices/principal/` |
| D. Experimentos | `python experimentos.py` | 50 min | `resultados/experimentos.csv` e `.json` |
| Repetições | `python repeticoes.py --n 3` | 25 min | `resultados/repeticoes.csv` (mediana e faixa de tempo e memória) |
| Figuras e tabelas | `python graficos.py` | 2 min | `resultados/figuras/*.png`, `resultados/tabelas/*.tex` |
| Exemplos do relatório | `python exemplos.py` | 2 min | `resultados/exemplos.txt`: transformações etapa por etapa e conferência de termos |
| Demonstração | `python consulta_demo.py "leite condensado" coco --campo ingredientes` | < 1 s | lista de receitas |

No Windows, use `python -X utf8 ...` para o terminal exibir acentos.

## Arquivos

- `config.py`: caminhos e nomes dos campos.
- `limpeza.py` (etapa A):
  - extrai título, descrição, ingredientes, preparo e corpo de cada página. Na coleta 1 usa marcadores de seção por site; na coleta 2, os campos JSON-LD;
  - remove boilerplate pelas janelas de 8 palavras presentes em pelo menos 20% das páginas do site;
  - classifica a página como receita ou não e extrai metadados (tempo, rendimento, dificuldade, categoria);
  - elimina duplicatas por URL normalizada e por conteúdo.
- `preprocessamento.py` (etapa B): análise léxica configurável. Faz tokenização, stopwords (nenhuma, NLTK ou NLTK + domínio), stemming (nenhum, plural, RSLP ou Snowball), remoção de acentos e tratamento de números.
- `indice.py` (etapa C):
  - VByte;
  - construtor SPIMI com blocos em disco e k-way merge;
  - leitor de postings;
  - granularidades documento, campos e chunk.
- `indexar.py`: CLI que constrói um índice e mede tempo por fase, pico de RAM e tamanho.
- `experimentos.py` (etapa D): grade de hiperparâmetros, com um processo por configuração.
- `repeticoes.py`: repete 3 vezes as configurações principais, de forma intercalada, para medir a variação de tempo e memória.
- `graficos.py`: Zipf, Heaps, comparação das configurações e tabelas LaTeX.
- `exemplos.py`: exemplo real das transformações e conferência do df do índice por contagem direta no corpus.
- `consulta_demo.py`: AND booleano, frases por posição e TF-IDF com peso por campo. Serve só para validar o índice; o ranking é da parte 3.
- `testes.py`: testes de correção.

## Formato do índice (`saida/indices/<nome>/`)

| Arquivo | Conteúdo |
|---|---|
| `postings.bin` | listas concatenadas; cada posting tem gap da unidade, tf e gaps das posições, em Variable Byte |
| `lexico.tsv` | `termo  df  cf  deslocamento  bytes` |
| `unidades.tsv` | unidade indexada → `doc_id`, início do chunk, número de termos (por campo, no índice por campos) |
| `documentos.jsonl` | URL, título, site, flag de receita e metadados, para exibir resultados |
| `frequencias.tsv` | termos ordenados por frequência (Zipf) |
| `meta.json` | configuração, contagens, tempos, memória, tamanhos e curva de Heaps |

No índice por campos, cada termo tem o prefixo do campo: `t:` título, `d:` descrição, `i:` ingredientes, `p:` preparo, `c:` corpo. Por exemplo, `i:cebol`.
