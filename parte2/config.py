"""Caminhos e parâmetros compartilhados pelas etapas da parte 2."""
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CORPUS_ORIGINAL = BASE / 'corpus.jsonl'

PARTE2 = Path(__file__).resolve().parent
SAIDA = PARTE2 / 'saida'
CORPUS_LIMPO = SAIDA / 'corpus_limpo.jsonl'
INDICES = SAIDA / 'indices'
RESULTADOS = PARTE2 / 'resultados'
FIGURAS = RESULTADOS / 'figuras'

# Sites da coleta 1 só têm o texto corrido; os da coleta 2 trazem campos estruturados.
SITES_COLETA_1 = {'estadao_paladar', 'panelinha', 'receitas_globo', 'terra_degusta', 'tudogostoso', 'tudoreceitas'}
SITES_COLETA_2 = {'anamariabrogui', 'petitchef', 'receitasdeminuto', 'teleculinaria'}

# Campos indexáveis do documento limpo, com o prefixo usado no índice por campos.
CAMPOS = {'titulo': 't', 'descricao': 'd', 'ingredientes': 'i', 'preparo': 'p', 'corpo': 'c'}
