"""Etapa D: grade de hiperparâmetros da representação.

Cada configuração roda em um processo separado (indexar.py), para que o pico de
memória de uma não contamine a outra. Ao final, os arquivos pesados de cada índice
são apagados; ficam meta.json e frequencias.tsv. Os resultados vão para
resultados/experimentos.csv e resultados/experimentos.json.

  python experimentos.py              # roda o que ainda não tem meta.json
  python experimentos.py --refazer    # roda tudo de novo
"""
import argparse
import csv
import json
import subprocess
import sys
import time

import config

# Referência comum: posicional, nltk+domínio, RSLP, sem acentos, sem números, blocos de 2M postings.
BASE = ['--granularidade', 'documento', '--stopwords', 'nltk+dominio', '--stemmer', 'rslp']

EXPERIMENTOS = []
# E1: transformações léxicas (stopwords x stemming), granularidade documento.
for sw in ('nenhuma', 'nltk', 'nltk+dominio'):
    for st in ('nenhum', 'plural', 'rslp', 'snowball'):
        EXPERIMENTOS.append(('E1_preprocessamento', f'sw-{sw.replace("+", "_")}__st-{st}',
                             ['--granularidade', 'documento', '--stopwords', sw, '--stemmer', st]))
EXPERIMENTOS += [
    ('E1_preprocessamento', 'sw-nltk_dominio__st-rslp__acentos', BASE + ['--manter-acentos']),
    ('E1_preprocessamento', 'sw-nltk_dominio__st-rslp__numeros', BASE + ['--numeros']),
]
# E2: granularidade e tamanho do chunk.
EXPERIMENTOS += [('E2_granularidade', 'documento', BASE), ('E2_granularidade', 'campos', ['--granularidade', 'campos'])]
for tam in (32, 64, 128, 256, 512):
    EXPERIMENTOS.append(('E2_granularidade', f'chunk{tam}', ['--granularidade', 'chunk', '--chunk', str(tam)]))
for sob in (16, 32, 64):
    EXPERIMENTOS.append(('E2_granularidade', f'chunk128_sob{sob}',
                         ['--granularidade', 'chunk', '--chunk', '128', '--sobreposicao', str(sob)]))
# E3: tamanho do bloco SPIMI (buckets em memória) no índice por campos.
for bloco in (100_000, 500_000, 2_000_000, 5_000_000, 0):
    EXPERIMENTOS.append(('E3_bloco_spimi', f'bloco{bloco or "_ilimitado"}',
                         ['--granularidade', 'campos', '--bloco', str(bloco)]))
# E4: posições e escopo da coleção.
EXPERIMENTOS += [
    ('E4_estrutura', 'campos_sem_posicoes', ['--granularidade', 'campos', '--sem-posicoes']),
    ('E4_estrutura', 'documento_sem_posicoes', BASE + ['--sem-posicoes']),
    ('E4_estrutura', 'campos_apenas_receitas', ['--granularidade', 'campos', '--apenas-receitas']),
]

PESADOS = ('postings.bin', 'lexico.tsv', 'unidades.tsv', 'documentos.jsonl')


def linha_resultado(grupo, nome, meta):
    c, t, m, s = meta['contagens'], meta['tempos_s'], meta['memoria_mb'], meta['tamanho_bytes']
    a = meta['config']['analisador']
    return {
        'grupo': grupo, 'nome': nome, 'granularidade': meta['config']['granularidade'],
        'chunk': meta['config']['chunk'] if meta['config']['granularidade'] == 'chunk' else '',
        'sobreposicao': meta['config']['sobreposicao'] if meta['config']['granularidade'] == 'chunk' else '',
        'stopwords': a['stopwords'], 'stemmer': a['stemmer'], 'sem_acentos': a['remover_acentos'],
        'numeros': a['manter_numeros'], 'posicional': meta['config']['posicional'],
        'apenas_receitas': meta['config']['apenas_receitas'], 'bloco': meta['config']['limite_postings_bloco'],
        'documentos': c['documentos'], 'unidades': c['unidades'], 'tokens_brutos': c['tokens_brutos'],
        'ocorrencias': c['ocorrencias_indexadas'], 'vocabulario': c['vocabulario'], 'hapax': c['hapax_legomena'],
        'postings': c['postings'], 'blocos': c['blocos_spimi'],
        'tempo_total_s': round(t['total'], 2), 'tempo_analise_s': round(t['analise_lexica'], 2),
        'tempo_inversao_s': round(t['inversao_memoria'], 2), 'tempo_blocos_s': round(t['escrita_blocos'], 2),
        'tempo_merge_s': round(t['merge_final'], 2), 'tempo_leitura_s': round(t['leitura_json'], 2),
        'ram_pico_mb': round(m['pico'], 1), 'ram_acrescimo_mb': round(m['acrescimo_pico'], 1),
        'postings_mb': round(s['postings.bin'] / 2 ** 20, 2), 'lexico_mb': round(s['lexico.tsv'] / 2 ** 20, 2),
        'unidades_mb': round(s['unidades.tsv'] / 2 ** 20, 2), 'indice_mb': round(s['indice_total'] / 2 ** 20, 2),
        'postings_int32_mb': round(s['postings_sem_compressao_int32'] / 2 ** 20, 2),
        'compressao_vbyte': round(s['taxa_compressao_vbyte'], 2),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--refazer', action='store_true')
    p.add_argument('--grupo', help='roda só um grupo (ex.: E2_granularidade)')
    args = p.parse_args()
    config.RESULTADOS.mkdir(parents=True, exist_ok=True)
    linhas = []
    for i, (grupo, nome, extra) in enumerate(EXPERIMENTOS, 1):
        diretorio = config.INDICES / f'exp_{nome}'
        meta_path = diretorio / 'meta.json'
        if (not args.grupo or args.grupo == grupo) and (args.refazer or not meta_path.exists()):
            t = time.perf_counter()
            print(f'[{i}/{len(EXPERIMENTOS)}] {grupo} {nome} ...', end=' ', flush=True)
            subprocess.run([sys.executable, '-X', 'utf8', str(config.PARTE2 / 'indexar.py'),
                            '--nome', f'exp_{nome}', *extra], check=True, stdout=subprocess.DEVNULL)
            for arquivo in PESADOS:
                (diretorio / arquivo).unlink(missing_ok=True)
            print(f'{time.perf_counter() - t:.0f}s', flush=True)
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            linhas.append(linha_resultado(grupo, nome, meta))
    with (config.RESULTADOS / 'experimentos.csv').open('w', encoding='utf-8-sig', newline='') as f:
        escritor = csv.DictWriter(f, fieldnames=list(linhas[0]))
        escritor.writeheader()
        escritor.writerows(linhas)
    (config.RESULTADOS / 'experimentos.json').write_text(
        json.dumps(linhas, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(linhas)} configurações em {config.RESULTADOS / "experimentos.csv"}')


if __name__ == '__main__':
    main()
