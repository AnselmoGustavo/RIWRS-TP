"""Etapa C: índice invertido em arquivos, construído por SPIMI e comprimido com VByte.

Formato no diretório do índice:
  postings.bin  listas de postings concatenadas; para cada unidade da lista:
                gap do id da unidade, tf e, no índice posicional, os gaps das posições,
                todos codificados em Variable Byte;
  lexico.tsv    termo, df, cf, deslocamento e tamanho (bytes) da lista em postings.bin;
  unidades.tsv  unidade indexada -> documento, início do chunk e número de termos;
  meta.json     configuração, contagens, tempos e tamanhos.

SPIMI (Manning et al., cap. 4): os postings são acumulados num dicionário em memória,
já comprimidos. Quando o bloco atinge o limite de postings, os termos são ordenados e
o bloco vai para o disco. No fim, os blocos são intercalados (k-way merge) num único
arquivo. Como as unidades chegam em ordem crescente, a junção de listas de blocos
diferentes só precisa recodificar o primeiro gap de cada parte.
"""
import heapq
import json
import struct
import time
from pathlib import Path

import config

# --- Variable Byte -------------------------------------------------------------------
# Convenção de Manning et al.: 7 bits por byte; o bit alto marca o último byte do número.
_TABELA = [bytes([n | 0x80]) if n < 128 else bytes([n >> 7, (n & 0x7F) | 0x80]) for n in range(1 << 14)]


def vb(n):
    if n < 16384:
        return _TABELA[n]
    saida = bytearray()
    while True:
        saida.insert(0, n & 0x7F)
        if n < 128:
            break
        n >>= 7
    saida[-1] |= 0x80
    return bytes(saida)


def vb_decodificar(buf, inicio=0, fim=None):
    numeros, n = [], 0
    for byte in memoryview(buf)[inicio:fim]:
        if byte & 0x80:
            numeros.append((n << 7) | (byte & 0x7F))
            n = 0
        else:
            n = (n << 7) | byte
    return numeros


def vb_primeiro(buf):
    """Primeiro número de buf e quantos bytes ele ocupa."""
    n = 0
    for i, byte in enumerate(buf):
        if byte & 0x80:
            return (n << 7) | (byte & 0x7F), i + 1
        n = (n << 7) | byte
    raise ValueError('VByte incompleto')


# --- Unidades indexadas (granularidade) ---------------------------------------------
SEPARACAO_CAMPOS = 50  # salto de posição entre campos, para não casar frases entre eles


def textos_campos(doc):
    return {
        'titulo': doc['titulo'], 'descricao': doc['descricao'],
        'ingredientes': ' \n '.join(doc['ingredientes']), 'preparo': ' \n '.join(doc['preparo']),
        'corpo': doc['corpo'],
    }


def unidades(doc, analisador, granularidade, tam_chunk, sobreposicao):
    """Gera (termos_com_posições, início, comprimentos_por_campo) para cada unidade do documento."""
    campos = textos_campos(doc)
    if granularidade == 'campos':
        termos, comprimentos = [], []
        for campo, texto in campos.items():
            prefixo = config.CAMPOS[campo] + ':'
            analisados = analisador.analisar_com_posicoes(texto)
            termos.extend((prefixo + t, p) for t, p in analisados)
            comprimentos.append(len(analisados))
        yield termos, 0, comprimentos
        return
    termos, deslocamento = [], 0
    for texto in campos.values():
        tokens = analisador.analisar_com_posicoes(texto, deslocamento)
        termos.extend(tokens)
        deslocamento = (tokens[-1][1] if tokens else deslocamento) + SEPARACAO_CAMPOS
    if granularidade == 'documento':
        yield termos, 0, [len(termos)]
        return
    passo = tam_chunk - sobreposicao
    for inicio in range(0, max(len(termos) - sobreposicao, 1), passo):
        janela = termos[inicio:inicio + tam_chunk]
        if janela:
            yield janela, inicio, [len(janela)]


# --- Construção SPIMI ----------------------------------------------------------------
_CAB = struct.Struct('<HIIII')  # tamanho do termo, df, cf, última unidade, tamanho da lista


class ConstrutorSPIMI:
    def __init__(self, destino, posicional=True, limite_postings=0):
        self.destino = Path(destino)
        self.destino.mkdir(parents=True, exist_ok=True)
        self.posicional = posicional
        self.limite = limite_postings  # 0 = um único bloco em memória
        self.blocos = []
        self.tempos = {'escrita_blocos_s': 0.0, 'merge_s': 0.0}
        self.total_postings = self.total_posicoes = 0
        self._novo_bloco()

    def _novo_bloco(self):
        # termo -> [df, cf, última unidade, lista comprimida]
        self.dicionario = {}
        self.postings_bloco = 0

    def adicionar(self, unidade, termos_posicoes):
        """Inverte uma unidade: agrupa as posições de cada termo e anexa ao dicionário."""
        por_termo = {}
        for termo, pos in termos_posicoes:
            lista = por_termo.get(termo)
            if lista is None:
                por_termo[termo] = [pos]
            else:
                lista.append(pos)
        dicionario, posicional = self.dicionario, self.posicional
        for termo, posicoes in por_termo.items():
            entrada = dicionario.get(termo)
            if entrada is None:
                entrada = dicionario[termo] = [0, 0, 0, bytearray()]
            tf = len(posicoes)
            dados = entrada[3]
            dados += vb(unidade - entrada[2])
            dados += vb(tf)
            if posicional:
                anterior = 0
                for p in posicoes:
                    dados += vb(p - anterior)
                    anterior = p
            entrada[0] += 1
            entrada[1] += tf
            entrada[2] = unidade
        n = len(por_termo)
        self.postings_bloco += n
        self.total_postings += n
        self.total_posicoes += len(termos_posicoes)
        if self.limite and self.postings_bloco >= self.limite:
            self._gravar_bloco()

    def _gravar_bloco(self):
        if not self.dicionario:
            return
        t = time.perf_counter()
        caminho = self.destino / f'_bloco_{len(self.blocos):04d}.bin'
        with caminho.open('wb') as f:
            for termo in sorted(self.dicionario):
                df, cf, ultima, dados = self.dicionario[termo]
                chave = termo.encode('utf-8')
                f.write(_CAB.pack(len(chave), df, cf, ultima, len(dados)))
                f.write(chave)
                f.write(dados)
        self.blocos.append(caminho)
        self._novo_bloco()
        self.tempos['escrita_blocos_s'] += time.perf_counter() - t

    @staticmethod
    def _ler_bloco(caminho):
        # Buffer pequeno: no merge todos os blocos ficam abertos ao mesmo tempo.
        with open(caminho, 'rb', buffering=1 << 16) as f:
            while True:
                cab = f.read(_CAB.size)
                if not cab:
                    return
                tam, df, cf, ultima, n = _CAB.unpack(cab)
                yield f.read(tam).decode('utf-8'), df, cf, ultima, f.read(n)

    def finalizar(self):
        """Grava postings.bin e lexico.tsv; devolve o tamanho do vocabulário."""
        if self.blocos:
            self._gravar_bloco()
            fontes = [self._ler_bloco(c) for c in self.blocos]
        else:  # tudo coube num bloco: grava direto da memória, sem arquivo intermediário
            fontes = [((t, *v) for t, v in sorted(self.dicionario.items()))]
        t = time.perf_counter()
        vocabulario = 0
        with (self.destino / 'postings.bin').open('wb', buffering=1 << 20) as post, \
                (self.destino / 'lexico.tsv').open('w', encoding='utf-8', newline='\n') as lex:
            deslocamento = 0
            # heapq.merge intercala as fontes por termo; empates preservam a ordem dos blocos.
            atual, partes = None, []
            for item in heapq.merge(*fontes, key=lambda x: x[0]):
                if item[0] != atual:
                    if partes:
                        deslocamento += self._gravar_termo(post, lex, atual, partes, deslocamento)
                        vocabulario += 1
                    atual, partes = item[0], []
                partes.append(item)
            if partes:
                deslocamento += self._gravar_termo(post, lex, atual, partes, deslocamento)
                vocabulario += 1
        for caminho in self.blocos:
            caminho.unlink()
        self.dicionario = {}
        self.tempos['merge_s'] = time.perf_counter() - t
        return vocabulario

    @staticmethod
    def _gravar_termo(post, lex, termo, partes, deslocamento):
        df = cf = 0
        ultima = 0
        tamanho = 0
        for i, (_, d, c, u, dados) in enumerate(partes):
            if i:  # recodifica só o primeiro gap, que no bloco era relativo a zero
                primeiro, n = vb_primeiro(dados)
                dados = vb(primeiro - ultima) + dados[n:]
            post.write(dados)
            tamanho += len(dados)
            df, cf, ultima = df + d, cf + c, u
        lex.write(f'{termo}\t{df}\t{cf}\t{deslocamento}\t{tamanho}\n')
        return tamanho


# --- Leitura -------------------------------------------------------------------------
class LeitorIndice:
    def __init__(self, diretorio):
        self.dir = Path(diretorio)
        self.meta = json.loads((self.dir / 'meta.json').read_text(encoding='utf-8'))
        self.posicional = self.meta['config']['posicional']
        self.lexico = {}
        with (self.dir / 'lexico.tsv').open(encoding='utf-8') as f:
            for linha in f:
                termo, df, cf, desl, tam = linha.rstrip('\n').split('\t')
                self.lexico[termo] = (int(df), int(cf), int(desl), int(tam))
        self._postings = (self.dir / 'postings.bin').open('rb')
        self.unidades = []  # unidade -> (doc_id, inicio, comprimentos)
        with (self.dir / 'unidades.tsv').open(encoding='utf-8') as f:
            next(f)
            for linha in f:
                _, doc, inicio, comp = linha.rstrip('\n').split('\t')
                self.unidades.append((int(doc), int(inicio), [int(x) for x in comp.split(',')]))

    def df(self, termo):
        return self.lexico.get(termo, (0,))[0]

    def postings(self, termo):
        """Lista de (unidade, tf, posições) do termo; posições vazias no índice não posicional."""
        if termo not in self.lexico:
            return []
        df, _, desl, tam = self.lexico[termo]
        self._postings.seek(desl)
        numeros = vb_decodificar(self._postings.read(tam))
        saida, i, unidade = [], 0, 0
        for _ in range(df):
            unidade += numeros[i]
            tf = numeros[i + 1]
            i += 2
            posicoes = []
            if self.posicional:
                p = 0
                for g in numeros[i:i + tf]:
                    p += g
                    posicoes.append(p)
                i += tf
            saida.append((unidade, tf, posicoes))
        return saida

    def fechar(self):
        self._postings.close()
