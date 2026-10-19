"""Constrói um índice com a configuração escolhida e registra tempo, memória e espaço.

Exemplos:
  python indexar.py --nome principal --granularidade campos --documentos
  python indexar.py --nome chunk128 --granularidade chunk --chunk 128 --sobreposicao 32
"""
import argparse
import json
import shutil
import threading
import time
from collections import Counter

import psutil

import config
from indice import ConstrutorSPIMI, textos_campos, unidades
from preprocessamento import ESTRATEGIAS_STOPWORDS, STEMMERS, Analisador


class MonitorMemoria(threading.Thread):
    """Amostra a memória residente (RSS) do processo para registrar o pico durante a indexação."""

    def __init__(self, intervalo=0.05):
        super().__init__(daemon=True)
        self.processo = psutil.Process()
        self.intervalo = intervalo
        self.inicial = self.pico = self.processo.memory_info().rss
        self._parar = threading.Event()

    def run(self):
        while not self._parar.is_set():
            self.pico = max(self.pico, self.processo.memory_info().rss)
            time.sleep(self.intervalo)

    def parar(self):
        self._parar.set()
        self.join()
        return self.inicial, self.pico


def tamanho(caminho):
    return caminho.stat().st_size if caminho.exists() else 0


def construir(args):
    destino = config.INDICES / args.nome
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    analisador = Analisador(stopwords=args.stopwords, stemmer=args.stemmer,
                            remover_acentos=not args.manter_acentos, manter_numeros=args.numeros)
    cfg = {
        'nome': args.nome, 'granularidade': args.granularidade, 'chunk': args.chunk,
        'sobreposicao': args.sobreposicao, 'posicional': not args.sem_posicoes,
        'limite_postings_bloco': args.bloco, 'apenas_receitas': args.apenas_receitas,
        'analisador': analisador.config,
    }
    monitor = MonitorMemoria()
    monitor.start()
    inicio = time.perf_counter()
    construtor = ConstrutorSPIMI(destino, posicional=cfg['posicional'], limite_postings=args.bloco)
    t_leitura = t_analise = t_inversao = 0.0
    docs = n_unidades = tokens_brutos = 0
    heaps = []  # (ocorrências indexadas, tamanho do vocabulário) ao longo da coleção
    vocabulario_visto = set()
    ocorrencias = 0
    f_unid = (destino / 'unidades.tsv').open('w', encoding='utf-8', newline='\n')
    f_unid.write('unidade\tdoc_id\tinicio\tcomprimentos\n')
    f_docs = (destino / 'documentos.jsonl').open('w', encoding='utf-8', newline='\n') if args.documentos else None
    with config.CORPUS_LIMPO.open(encoding='utf-8') as corpus:
        while True:
            t = time.perf_counter()
            linha = corpus.readline()
            if not linha:
                break
            doc = json.loads(linha)
            t_leitura += time.perf_counter() - t
            if args.apenas_receitas and not doc['is_recipe']:
                continue
            if args.limite and docs >= args.limite:
                break
            docs += 1
            t = time.perf_counter()
            geradas = list(unidades(doc, analisador, args.granularidade, args.chunk, args.sobreposicao))
            tokens_brutos += sum(len(analisador.tokens(txt)) for txt in textos_campos(doc).values())
            t_analise += time.perf_counter() - t
            t = time.perf_counter()
            for termos, inicio_chunk, comprimentos in geradas:
                construtor.adicionar(n_unidades, termos)
                f_unid.write(f"{n_unidades}\t{doc['doc_id']}\t{inicio_chunk}\t{','.join(map(str, comprimentos))}\n")
                n_unidades += 1
                vocabulario_visto.update(t for t, _ in termos)
            if args.granularidade == 'chunk':  # a sobreposição repete termos; conta cada posição uma vez
                ocorrencias += len({p for termos, _, _ in geradas for _, p in termos})
            else:
                ocorrencias += sum(len(termos) for termos, _, _ in geradas)
            t_inversao += time.perf_counter() - t
            if docs % 1000 == 0:
                heaps.append((ocorrencias, len(vocabulario_visto)))
            if f_docs:
                f_docs.write(json.dumps({'doc_id': doc['doc_id'], 'url': doc['url'], 'site': doc['site'],
                                         'titulo': doc['titulo'], 'is_recipe': doc['is_recipe'],
                                         'meta': doc['meta']}, ensure_ascii=False) + '\n')
    f_unid.close()
    if f_docs:
        f_docs.close()
    vocabulario = construtor.finalizar()
    total = time.perf_counter() - inicio
    ram_inicial, ram_pico = monitor.parar()

    # Frequências de cada termo, para Zipf e para inspeção do vocabulário.
    cf, df = Counter(), {}
    with (destino / 'lexico.tsv').open(encoding='utf-8') as f:
        for linha in f:
            termo, d, c, _, _ = linha.split('\t')
            cf[termo], df[termo] = int(c), int(d)
    with (destino / 'frequencias.tsv').open('w', encoding='utf-8', newline='\n') as f:
        f.write('termo\tcf\tdf\n')
        for termo, c in cf.most_common():
            f.write(f'{termo}\t{c}\t{df[termo]}\n')

    p = construtor
    # Referência sem compressão: inteiros de 4 bytes (id, tf e cada posição).
    sem_compressao = 4 * (2 * p.total_postings + (p.total_posicoes if cfg['posicional'] else 0))
    tamanhos = {nome: tamanho(destino / nome) for nome in
                ('postings.bin', 'lexico.tsv', 'unidades.tsv', 'documentos.jsonl', 'frequencias.tsv')}
    meta = {
        'config': cfg,
        'contagens': {
            'documentos': docs, 'unidades': n_unidades, 'tokens_brutos': tokens_brutos,
            'ocorrencias_indexadas': p.total_posicoes, 'vocabulario': vocabulario,
            'postings': p.total_postings, 'blocos_spimi': len(p.blocos) or 1,
            'media_postings_por_termo': p.total_postings / max(vocabulario, 1),
            'media_termos_por_unidade': p.total_posicoes / max(n_unidades, 1),
            'hapax_legomena': sum(1 for c in cf.values() if c == 1),
        },
        'tempos_s': {
            'leitura_json': t_leitura, 'analise_lexica': t_analise, 'inversao_memoria': t_inversao,
            'escrita_blocos': p.tempos['escrita_blocos_s'], 'merge_final': p.tempos['merge_s'], 'total': total,
        },
        'memoria_mb': {'inicial': ram_inicial / 2 ** 20, 'pico': ram_pico / 2 ** 20,
                       'acrescimo_pico': (ram_pico - ram_inicial) / 2 ** 20},
        'tamanho_bytes': {**tamanhos,
                          'indice_total': tamanhos['postings.bin'] + tamanhos['lexico.tsv'] + tamanhos['unidades.tsv'],
                          'postings_sem_compressao_int32': sem_compressao,
                          'taxa_compressao_vbyte': sem_compressao / max(tamanhos['postings.bin'], 1)},
        'heaps': heaps,
    }
    (destino / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return meta


def argumentos(lista=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--nome', required=True, help='subpasta em saida/indices')
    p.add_argument('--granularidade', choices=('documento', 'campos', 'chunk'), default='campos')
    p.add_argument('--chunk', type=int, default=128, help='termos por chunk (granularidade chunk)')
    p.add_argument('--sobreposicao', type=int, default=0, help='termos repetidos entre chunks vizinhos')
    p.add_argument('--stopwords', choices=ESTRATEGIAS_STOPWORDS, default='nltk+dominio')
    p.add_argument('--stemmer', choices=STEMMERS, default='rslp')
    p.add_argument('--manter-acentos', action='store_true')
    p.add_argument('--numeros', action='store_true', help='indexa números (quantidades, temperaturas)')
    p.add_argument('--sem-posicoes', action='store_true', help='índice sem posições (não suporta frases)')
    p.add_argument('--bloco', type=int, default=2_000_000, help='postings por bloco SPIMI (0 = sem limite)')
    p.add_argument('--apenas-receitas', action='store_true')
    p.add_argument('--documentos', action='store_true', help='grava documentos.jsonl (metadados para exibição)')
    p.add_argument('--limite', type=int, default=0, help='indexa só os N primeiros documentos (testes)')
    args = p.parse_args(lista)
    if args.granularidade == 'chunk' and not 0 <= args.sobreposicao < args.chunk:
        p.error('a sobreposição deve ser menor que o tamanho do chunk')
    return args


if __name__ == '__main__':
    meta = construir(argumentos())
    print(json.dumps({k: meta[k] for k in ('contagens', 'tempos_s', 'memoria_mb', 'tamanho_bytes')},
                     ensure_ascii=False, indent=2))
