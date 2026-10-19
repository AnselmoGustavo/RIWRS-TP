"""Etapa B: análise léxica configurável (tokenização, stopwords, stemming, acentos).

O mesmo Analisador deve processar documentos e consultas, para que os termos coincidam.
Cada token distinto é processado uma única vez e guardado em cache, pois o
vocabulário é muito menor que o número de ocorrências.
"""
import re
import unicodedata

from nltk.corpus import stopwords as nltk_stopwords
from nltk.stem import RSLPStemmer, SnowballStemmer

# Números (inteiros, decimais e frações como 1/2) ou sequências de letras.
# Hífens e apóstrofos separam tokens: "pimenta-do-reino" vira pimenta, do, reino.
TOKEN = re.compile(r'\d+(?:[.,/]\d+)*|[^\W\d_]+')
FRACOES = str.maketrans({'½': ' 1/2 ', '⅓': ' 1/3 ', '⅔': ' 2/3 ', '¼': ' 1/4 ', '¾': ' 3/4 ', '⅛': ' 1/8 '})

# Termos frequentes no domínio que quase não distinguem uma receita de outra.
STOPWORDS_DOMINIO = {
    'receita', 'receitas', 'ingrediente', 'ingredientes', 'modo', 'preparo', 'preparação', 'passo',
    'gosto', 'q.b', 'qb', 'aproximadamente', 'cerca', 'ainda', 'bem', 'aqui', 'confira', 'veja',
    'faça', 'fazer', 'pode', 'você', 'vai', 'fica', 'ficar', 'deixe', 'coloque', 'adicione', 'junte',
    'acrescente', 'misture', 'reserve', 'leve', 'sirva', 'utilize', 'use',
}

ESTRATEGIAS_STOPWORDS = ('nenhuma', 'nltk', 'nltk+dominio')
STEMMERS = ('nenhum', 'plural', 'rslp', 'snowball')


def sem_acentos(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')


def remover_plural(palavra):
    """Stemming leve: só reduz plurais regulares do português (cebolas→cebola, pães→pão)."""
    if len(palavra) <= 3 or not palavra.endswith('s'):
        return palavra
    for sufixo, troca in (('ões', 'ão'), ('ães', 'ão'), ('ais', 'al'), ('éis', 'el'), ('eis', 'el'),
                          ('óis', 'ol'), ('uis', 'ul'), ('res', 'r'), ('zes', 'z'), ('ns', 'm')):
        if palavra.endswith(sufixo) and len(palavra) > len(sufixo):
            return palavra[:-len(sufixo)] + troca
    if palavra[-2] in 'su':  # ônibus, vírus: não são plurais regulares
        return palavra
    if palavra[-2] == 'i' and any(c in 'áéíóúâêô' for c in palavra[:-2]):  # lápis, tênis: invariáveis
        return palavra
    return palavra[:-1]


class Analisador:
    def __init__(self, stopwords='nltk+dominio', stemmer='rslp', remover_acentos=True,
                 manter_numeros=False, tamanho_minimo=2):
        if stopwords not in ESTRATEGIAS_STOPWORDS:
            raise ValueError(f'stopwords deve ser um de {ESTRATEGIAS_STOPWORDS}')
        if stemmer not in STEMMERS:
            raise ValueError(f'stemmer deve ser um de {STEMMERS}')
        self.config = {'stopwords': stopwords, 'stemmer': stemmer, 'remover_acentos': remover_acentos,
                       'manter_numeros': manter_numeros, 'tamanho_minimo': tamanho_minimo}
        lista = set()
        if stopwords != 'nenhuma':
            lista |= set(nltk_stopwords.words('portuguese'))
        if stopwords == 'nltk+dominio':
            lista |= STOPWORDS_DOMINIO
        # Compara também sem acento, já que o usuário pode digitar "voce" ou "nao".
        self.stopwords = lista | {sem_acentos(p) for p in lista}
        self.radical = {
            'nenhum': lambda p: p,
            'plural': remover_plural,
            'rslp': RSLPStemmer().stem,
            'snowball': SnowballStemmer('portuguese').stem,
        }[stemmer]
        self.remover_acentos = remover_acentos
        self.manter_numeros = manter_numeros
        self.tamanho_minimo = tamanho_minimo
        self._cache = {}

    def tokens(self, texto):
        """Análise léxica: minúsculas, frações unicode convertidas e separação em tokens."""
        return TOKEN.findall(texto.translate(FRACOES).lower())

    def termo(self, token):
        """Transforma um token em termo de índice, ou None se ele for descartado."""
        try:
            return self._cache[token]
        except KeyError:
            pass
        if token[0].isdigit():
            resultado = token if self.manter_numeros else None
        elif len(token) < self.tamanho_minimo or token in self.stopwords:
            resultado = None
        else:
            resultado = self.radical(token)
            if self.remover_acentos:
                resultado = sem_acentos(resultado)
            if not resultado:
                resultado = None
        self._cache[token] = resultado
        return resultado

    def analisar(self, texto):
        """Lista de termos na ordem do texto (os descartados são omitidos)."""
        termo = self.termo
        return [t for t in map(termo, self.tokens(texto)) if t is not None]

    def analisar_com_posicoes(self, texto, deslocamento=0):
        """Pares (termo, posição). A posição conta todos os tokens, inclusive stopwords,
        para que consultas por frase respeitem a distância original entre as palavras."""
        termo = self.termo
        saida = []
        for i, tok in enumerate(self.tokens(texto), deslocamento):
            t = termo(tok)
            if t is not None:
                saida.append((t, i))
        return saida

    def descricao(self):
        c = self.config
        return f"sw={c['stopwords']}|stem={c['stemmer']}|sem_acento={'sim' if c['remover_acentos'] else 'nao'}" \
               f"|num={'sim' if c['manter_numeros'] else 'nao'}"


if __name__ == '__main__':
    exemplo = 'Pimentas-do-reino, 2½ xícaras de AÇÚCAR e cebolas picadas; pães de queijo assados.'
    for sw in ESTRATEGIAS_STOPWORDS:
        for st in STEMMERS:
            a = Analisador(stopwords=sw, stemmer=st)
            print(f'{a.descricao():55} {a.analisar(exemplo)}')
