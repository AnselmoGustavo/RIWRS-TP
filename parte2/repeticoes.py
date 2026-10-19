"""Repete a construção das configurações principais para medir a variação de tempo e memória.

O tamanho do índice é determinístico; tempo e memória variam entre execuções. Cada
configuração roda N vezes, intercaladas (A, B, C, A, B, C...), para que uma variação
de carga da máquina não afete só uma delas. Saída: resultados/repeticoes.csv.

  python repeticoes.py --n 3
"""
import argparse
import csv
import json
import shutil
import statistics
import subprocess
import sys

import config

CONFIGS = [
    ('sem transformações (documento)', ['--granularidade', 'documento', '--stopwords', 'nenhuma', '--stemmer', 'nenhum']),
    ('referência (documento)', ['--granularidade', 'documento']),
    ('campos (índice principal)', ['--granularidade', 'campos']),
    ('chunk 128', ['--granularidade', 'chunk', '--chunk', '128']),
    ('campos, bloco de 500 mil', ['--granularidade', 'campos', '--bloco', '500000']),
]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--n', type=int, default=3)
    args = p.parse_args()
    medidas = {nome: [] for nome, _ in CONFIGS}
    for rodada in range(1, args.n + 1):
        for i, (nome, extra) in enumerate(CONFIGS):
            destino = f'_rep_{i}'
            subprocess.run([sys.executable, '-X', 'utf8', str(config.PARTE2 / 'indexar.py'), '--nome', destino, *extra],
                           check=True, stdout=subprocess.DEVNULL)
            meta = json.loads((config.INDICES / destino / 'meta.json').read_text(encoding='utf-8'))
            medidas[nome].append(meta)
            shutil.rmtree(config.INDICES / destino)
            print(f'rodada {rodada} {nome}: {meta["tempos_s"]["total"]:.1f}s', flush=True)
    linhas = []
    for nome, metas in medidas.items():
        tempos = [m['tempos_s']['total'] for m in metas]
        picos = [m['memoria_mb']['pico'] for m in metas]
        extras = [m['memoria_mb']['acrescimo_pico'] for m in metas]
        m = metas[0]
        linhas.append({
            'configuracao': nome, 'execucoes': len(metas),
            'tempo_mediana_s': round(statistics.median(tempos), 1), 'tempo_min_s': round(min(tempos), 1),
            'tempo_max_s': round(max(tempos), 1),
            'ram_pico_mediana_mib': round(statistics.median(picos), 1),
            'ram_acrescimo_mediana_mib': round(statistics.median(extras), 1),
            'ram_acrescimo_min_mib': round(min(extras), 1), 'ram_acrescimo_max_mib': round(max(extras), 1),
            'indice_mib': round(m['tamanho_bytes']['indice_total'] / 2 ** 20, 1),
            'vocabulario': m['contagens']['vocabulario'], 'unidades': m['contagens']['unidades'],
            'postings': m['contagens']['postings'],
        })
    config.RESULTADOS.mkdir(parents=True, exist_ok=True)
    with (config.RESULTADOS / 'repeticoes.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]))
        w.writeheader()
        w.writerows(linhas)
    for l in linhas:
        print(l)


if __name__ == '__main__':
    main()
