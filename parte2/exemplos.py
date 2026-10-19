"""Exemplos do relatório: transformações etapa por etapa e conferência manual de termos.

  python exemplos.py
Saída: resultados/exemplos.txt (texto) e resultados/exemplos.json.
"""
import json

import config
from indice import LeitorIndice
from preprocessamento import Analisador, sem_acentos

DOC_EXEMPLO = 'https://panelinha.com.br/receita/caldinho-feijao-preto-pimentao'
TRECHO = slice(0, 175)  # início do campo de ingredientes


def documento(url):
    with config.CORPUS_LIMPO.open(encoding='utf-8') as f:
        for linha in f:
            d = json.loads(linha)
            if d['url'] == url:
                return d
    raise KeyError(url)


def transformacoes(texto):
    sem_nada = Analisador(stopwords='nenhuma', stemmer='nenhum', remover_acentos=False, manter_numeros=True,
                          tamanho_minimo=1)
    completo = Analisador()  # configuração do índice principal
    tokens = sem_nada.tokens(texto)
    sem_numeros = [t for t in tokens if not t[0].isdigit() and len(t) >= 2]
    sem_stop = [t for t in sem_numeros if t not in completo.stopwords]
    radicais = [completo.radical(t) for t in sem_stop]
    return {
        'entrada': texto,
        'tokens': tokens,
        'sem_numeros_e_letras_isoladas': sem_numeros,
        'sem_stopwords': sem_stop,
        'stemming_rslp': radicais,
        'sem_acentos': [sem_acentos(r) for r in radicais],
        'conferencia_analisador': completo.analisar(texto),
    }


def conferir_termos(leitor, analisador, docs):
    """Compara o df do índice com uma contagem direta no corpus limpo, para termos presentes e ausentes."""
    palavras = [('ingredientes', 'cebola'), ('ingredientes', 'natas'), ('ingredientes', 'chávena'),
                ('ingredientes', 'xícara'), ('titulo', 'feijoada'), ('preparo', 'airfryer'),
                ('ingredientes', 'ornitorrinco')]
    resultado = []
    for campo, palavra in palavras:
        termo = analisador.analisar(palavra)[0]
        chave = f'{config.CAMPOS[campo]}:{termo}'
        contagem_direta = 0
        for d in docs:
            texto = ' '.join(d[campo]) if isinstance(d[campo], list) else d[campo]
            if termo in analisador.analisar(texto):
                contagem_direta += 1
        postings = leitor.postings(chave)
        exemplo = []
        for unidade, tf, posicoes in postings[:3]:
            doc_id = leitor.unidades[unidade][0]
            exemplo.append({'unidade': unidade, 'doc_id': doc_id, 'tf': tf, 'posicoes': posicoes[:5],
                            'titulo': docs[doc_id - 1]['titulo']})
        resultado.append({'campo': campo, 'palavra': palavra, 'termo_indice': chave, 'df_indice': leitor.df(chave),
                          'df_contagem_direta': contagem_direta, 'primeiros_postings': exemplo})
    return resultado


def main():
    doc = documento(DOC_EXEMPLO)
    texto = doc['ingredientes'][0][TRECHO].rsplit(' ', 1)[0]
    exemplo = {'doc_id': doc['doc_id'], 'url': doc['url'], 'titulo': doc['titulo'], **transformacoes(texto)}
    with config.CORPUS_LIMPO.open(encoding='utf-8') as f:
        docs = [json.loads(l) for l in f]
    assert all(d['doc_id'] == i for i, d in enumerate(docs, 1))
    leitor = LeitorIndice(config.INDICES / 'principal')
    a = leitor.meta['config']['analisador']
    analisador = Analisador(a['stopwords'], a['stemmer'], a['remover_acentos'], a['manter_numeros'], a['tamanho_minimo'])
    termos = conferir_termos(leitor, analisador, docs)
    leitor.fechar()
    saida = {'transformacoes': exemplo, 'conferencia_termos': termos}
    (config.RESULTADOS / 'exemplos.json').write_text(json.dumps(saida, ensure_ascii=False, indent=2) + '\n',
                                                     encoding='utf-8')
    linhas = [f'Documento {exemplo["doc_id"]}: {exemplo["titulo"]} ({exemplo["url"]})']
    for etapa in ('entrada', 'tokens', 'sem_numeros_e_letras_isoladas', 'sem_stopwords', 'stemming_rslp',
                  'sem_acentos', 'conferencia_analisador'):
        valor = exemplo[etapa]
        linhas.append(f'{etapa}: {valor if isinstance(valor, str) else " ".join(valor)}')
    linhas.append('')
    for t in termos:
        linhas.append(f'{t["palavra"]:12} {t["termo_indice"]:12} df índice={t["df_indice"]:6} '
                      f'contagem direta={t["df_contagem_direta"]:6}  {t["primeiros_postings"][:2]}')
    (config.RESULTADOS / 'exemplos.txt').write_text('\n'.join(linhas) + '\n', encoding='utf-8')
    print('\n'.join(linhas))


if __name__ == '__main__':
    main()
