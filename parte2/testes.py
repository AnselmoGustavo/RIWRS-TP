"""Testes de correção do índice: python testes.py"""
import json
import random
import shutil
from collections import defaultdict

import config
import indexar
from indice import LeitorIndice, textos_campos, unidades, vb, vb_decodificar
from preprocessamento import Analisador, remover_plural

N_DOCS = 1500


def testar_vbyte():
    rnd = random.Random(1)
    numeros = [0, 1, 127, 128, 16383, 16384, 2 ** 21, 2 ** 28 + 5] + [rnd.randrange(10 ** 7) for _ in range(5000)]
    assert vb_decodificar(b''.join(vb(n) for n in numeros)) == numeros
    assert vb(5) == bytes([0x85]) and vb(130) == bytes([0x01, 0x82])  # exemplo do livro de Manning
    print('ok  vbyte: codifica e decodifica', len(numeros), 'inteiros')


def testar_plural():
    casos = {'cebolas': 'cebola', 'pães': 'pão', 'limões': 'limão', 'animais': 'animal', 'colheres': 'colher',
             'nozes': 'noz', 'atuns': 'atum', 'ovos': 'ovo', 'arroz': 'arroz', 'lápis': 'lápis'}
    for entrada, esperado in casos.items():
        assert remover_plural(entrada) == esperado, (entrada, remover_plural(entrada))
    print('ok  plural:', len(casos), 'casos')


def construir(nome, *extra):
    return indexar.construir(indexar.argumentos(['--nome', nome, '--limite', str(N_DOCS), *extra]))


def esperado_forca_bruta(granularidade, analisador):
    """Recalcula os postings sem SPIMI: termo -> {unidade: posições}."""
    postings = defaultdict(lambda: defaultdict(list))
    unidade = 0
    with config.CORPUS_LIMPO.open(encoding='utf-8') as f:
        for i, linha in enumerate(f):
            if i >= N_DOCS:
                break
            for termos, _, _ in unidades(json.loads(linha), analisador, granularidade, 64, 16):
                for termo, pos in termos:
                    postings[termo][unidade].append(pos)
                unidade += 1
    return postings, unidade


def testar_indice(granularidade, extra=()):
    a = construir('_teste_um_bloco', '--granularidade', granularidade, '--bloco', '0',
                  '--chunk', '64', '--sobreposicao', '16', *extra)
    b = construir('_teste_varios', '--granularidade', granularidade, '--bloco', '20000',
                  '--chunk', '64', '--sobreposicao', '16', *extra)
    assert b['contagens']['blocos_spimi'] > 1
    for arquivo in ('postings.bin', 'lexico.tsv', 'unidades.tsv'):
        um = (config.INDICES / '_teste_um_bloco' / arquivo).read_bytes()
        varios = (config.INDICES / '_teste_varios' / arquivo).read_bytes()
        assert um == varios, f'{arquivo} difere entre 1 e {b["contagens"]["blocos_spimi"]} blocos'
    leitor = LeitorIndice(config.INDICES / '_teste_varios')
    esperado, n_unidades = esperado_forca_bruta(granularidade, Analisador())
    assert len(leitor.unidades) == n_unidades
    assert set(leitor.lexico) == set(esperado)
    amostra = random.Random(2).sample(sorted(esperado), 400) + ['i:cebol', 'i:sal', 'cebol', 'sal']
    for termo in amostra:
        if termo not in esperado:
            continue
        obtido = {u: pos for u, _, pos in leitor.postings(termo)}
        assert obtido == {u: p for u, p in esperado[termo].items()}, termo
    leitor.fechar()
    print(f'ok  índice {granularidade:9}: {b["contagens"]["blocos_spimi"]} blocos = 1 bloco; '
          f'{len(amostra)} listas conferidas por força bruta')


def testar_consulta_igual_documento():
    a = Analisador()
    assert a.analisar('CEBOLAS picadas') == a.analisar('cebola picada') == ['cebol', 'pic']
    assert a.analisar('Açúcar') == a.analisar('acucar')
    print('ok  consulta e documento passam pelo mesmo analisador')


if __name__ == '__main__':
    testar_vbyte()
    testar_plural()
    testar_consulta_igual_documento()
    try:
        testar_indice('documento')
        testar_indice('campos')
        testar_indice('chunk')
    finally:
        for nome in ('_teste_um_bloco', '_teste_varios'):
            shutil.rmtree(config.INDICES / nome, ignore_errors=True)
    print('todos os testes passaram')
