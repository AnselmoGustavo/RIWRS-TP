"""Consulta de validação sobre o índice (o ranking definitivo fica para a parte 3).

Interseção booleana (AND) dos termos, ordenação TF-IDF com pesos por campo e, entre
aspas, busca por frase usando as posições. Exemplos:
  python consulta_demo.py frango batata
  python consulta_demo.py "leite condensado" coco --campo ingredientes
"""
import argparse
import json
import math
import shlex
import time

import config
from indice import LeitorIndice
from preprocessamento import Analisador

PESOS = {'t': 3.0, 'd': 1.5, 'i': 2.0, 'p': 1.0, 'c': 0.5}


def carregar_documentos(diretorio):
    docs = {}
    with (diretorio / 'documentos.jsonl').open(encoding='utf-8') as f:
        for linha in f:
            d = json.loads(linha)
            docs[d['doc_id']] = d
    return docs


def contem_frase(listas_posicoes, deslocamentos):
    """True se existe p em que cada termo ocorre na mesma distância que tem na consulta.
    As posições contam também as stopwords: em "pão de queijo", queijo fica em p+2."""
    primeiro, *resto = listas_posicoes
    conjuntos = [set(p) for p in resto]
    return any(all(p + d in s for d, s in zip(deslocamentos[1:], conjuntos)) for p in primeiro)


def buscar(leitor, analisador, consulta, campos, apenas_receitas, docs, k=10):
    n = len(leitor.unidades)
    grupos = []  # cada grupo: termos de uma palavra ou de uma frase entre aspas, com as posições
    for parte in shlex.split(consulta):
        analisados = analisador.analisar_com_posicoes(parte)
        if analisados:
            grupos.append(analisados)
    if not grupos:
        return [], []
    pontuacao, candidatos = {}, None
    for analisados in grupos:
        termos = [t for t, _ in analisados]
        deslocamentos = [p - analisados[0][1] for _, p in analisados]
        # unidade -> lista de posições de cada termo da frase, em qualquer campo pedido
        por_unidade, peso_grupo = {}, {}
        for j, termo in enumerate(termos):
            vistos = {}
            for campo in campos:
                chave = f'{campo}:{termo}'
                df = leitor.df(chave)
                if not df:
                    continue
                idf = math.log10(n / df)
                for unidade, tf, posicoes in leitor.postings(chave):
                    vistos.setdefault(unidade, {})[campo] = posicoes
                    peso_grupo[unidade] = peso_grupo.get(unidade, 0) + PESOS[campo] * (1 + math.log10(tf)) * idf
            for unidade, por_campo in vistos.items():
                por_unidade.setdefault(unidade, [None] * len(termos))[j] = por_campo
        validos = set()
        for unidade, listas in por_unidade.items():
            if None in listas:
                continue
            if len(termos) == 1 or any(all(campo in l for l in listas)
                                       and contem_frase([l[campo] for l in listas], deslocamentos)
                                       for campo in listas[0]):
                validos.add(unidade)
        candidatos = validos if candidatos is None else candidatos & validos
        for unidade in validos:
            pontuacao[unidade] = pontuacao.get(unidade, 0) + peso_grupo[unidade]
    resultado = []
    for unidade in candidatos:
        doc = docs[leitor.unidades[unidade][0]]
        if apenas_receitas and not doc['is_recipe']:
            continue
        resultado.append((pontuacao[unidade], doc))
    resultado.sort(key=lambda x: -x[0])
    return resultado[:k], [[t for t, _ in g] for g in grupos]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('consulta', nargs='+')
    p.add_argument('--indice', default='principal')
    p.add_argument('--campo', action='append', choices=list(config.CAMPOS),
                   help='restringe a busca a um campo (pode repetir); padrão: todos')
    p.add_argument('--todas-paginas', action='store_true', help='inclui páginas que não são receitas')
    p.add_argument('-k', type=int, default=10)
    args = p.parse_args()
    diretorio = config.INDICES / args.indice
    t = time.perf_counter()
    leitor = LeitorIndice(diretorio)
    if leitor.meta['config']['granularidade'] != 'campos':
        p.error('a demonstração usa o índice por campos')
    docs = carregar_documentos(diretorio)
    a = leitor.meta['config']['analisador']
    analisador = Analisador(a['stopwords'], a['stemmer'], a['remover_acentos'], a['manter_numeros'], a['tamanho_minimo'])
    carga = time.perf_counter() - t
    campos = [config.CAMPOS[c] for c in args.campo] if args.campo else list(PESOS)
    consulta = ' '.join(f'"{x}"' if ' ' in x else x for x in args.consulta)
    t = time.perf_counter()
    resultado, grupos = buscar(leitor, analisador, consulta, campos, not args.todas_paginas, docs, args.k)
    tempo = time.perf_counter() - t
    print(f'consulta: {consulta}  ->  termos {grupos}  (carga do índice {carga:.1f}s, busca {tempo * 1000:.0f} ms)')
    for i, (score, d) in enumerate(resultado, 1):
        meta = d['meta']
        extra = ', '.join(x for x in (f"{meta['tempo_total_min']} min" if meta.get('tempo_total_min') else '',
                                      meta.get('dificuldade') or '') if x)
        print(f'{i:2}. {score:6.2f}  {d["titulo"][:70]:70}  [{d["site"]}] {extra}')
        print(f'              {d["url"]}')
    leitor.fechar()


if __name__ == '__main__':
    main()
