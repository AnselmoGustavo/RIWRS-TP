"""Gera figuras (PNG) e tabelas LaTeX do relatório a partir dos resultados dos experimentos.

  python graficos.py
Entradas: saida/estatisticas_limpeza.json, saida/indices/exp_*/ e resultados/experimentos.json.
Saídas: resultados/figuras/*.png e resultados/tabelas/*.tex.
"""
import json
from collections import Counter, defaultdict

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

import config
from preprocessamento import Analisador, STEMMERS

# Paleta categórica de referência (modo claro), usada na ordem fixa dos slots.
COR = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100']
TINTA, TINTA_2, GRADE = '#0b0b0b', '#52514e', '#e4e3df'
TABELAS = config.RESULTADOS / 'tabelas'

plt.rcParams.update({
    'figure.dpi': 150, 'savefig.dpi': 200, 'font.size': 9, 'axes.edgecolor': GRADE,
    'axes.labelcolor': TINTA_2, 'xtick.color': TINTA_2, 'ytick.color': TINTA_2, 'axes.grid': True,
    'grid.color': GRADE, 'grid.linewidth': 0.6, 'axes.spines.top': False, 'axes.spines.right': False,
    'axes.titlesize': 10, 'axes.titlecolor': TINTA, 'axes.titleweight': 'bold', 'legend.frameon': False,
    'axes.axisbelow': True,
})


def carregar():
    exp = json.loads((config.RESULTADOS / 'experimentos.json').read_text(encoding='utf-8'))
    return {e['nome']: e for e in exp}


def salvar(fig, nome):
    config.FIGURAS.mkdir(parents=True, exist_ok=True)
    fig.savefig(config.FIGURAS / nome, bbox_inches='tight', facecolor='white')
    plt.close(fig)


def fmt(n, casas=0):
    """Número no padrão brasileiro (milhar com ponto, decimal com vírgula)."""
    s = f'{n:,.{casas}f}'
    return s.replace(',', 'X').replace('.', ',').replace('X', '.')


NOMES_SITES = {
    'anamariabrogui': 'Ana Maria Brogui', 'estadao_paladar': 'Estadão Paladar', 'panelinha': 'Panelinha',
    'petitchef': 'Petitchef', 'receitas_globo': 'Receitas Globo', 'receitasdeminuto': 'Receitas de Minuto',
    'teleculinaria': 'TeleCulinária', 'terra_degusta': 'Terra Degusta', 'tudogostoso': 'TudoGostoso',
    'tudoreceitas': 'TudoReceitas',
}


def celula_cabecalho(texto):
    """Cabeçalho em negrito; '\\n' quebra a célula em duas linhas para a tabela caber sem encolher."""
    if '\n' in texto:
        return r'\textbf{\shortstack{' + texto.replace('\n', r'\\') + '}}'
    return r'\textbf{' + texto + '}'


def tabela(nome, legenda, rotulo, cabecalho, linhas, alinhamento):
    TABELAS.mkdir(parents=True, exist_ok=True)
    corpo = '\n'.join(' & '.join(map(str, l)) + r' \\' for l in linhas)
    # Fonte reduzida e colunas mais próximas; o \resizebox só atua se ainda assim passar da largura da página.
    tex = (f'\\begin{{table}}[htbp]\n\\centering\n\\caption{{{legenda}}}\n\\label{{{rotulo}}}\n\\footnotesize\n'
           f'\\setlength{{\\tabcolsep}}{{4pt}}\n'
           f'\\resizebox{{\\ifdim\\width>\\textwidth\\textwidth\\else\\width\\fi}}{{!}}{{%\n'
           f'\\begin{{tabular}}{{{alinhamento}}}\n\\hline\n'
           f'{" & ".join(map(celula_cabecalho, cabecalho))} \\\\\n\\hline\n{corpo}\n\\hline\n\\end{{tabular}}%\n}}\n'
           f'\\end{{table}}\n')
    (TABELAS / nome).write_text(tex, encoding='utf-8')


# --- Limpeza -------------------------------------------------------------------------
def tabela_limpeza():
    e = json.loads((config.SAIDA / 'estatisticas_limpeza.json').read_text(encoding='utf-8'))
    linhas = []
    for site, c in sorted(e['por_site'].items(), key=lambda x: -x[1]['docs_entrada']):
        linhas.append([NOMES_SITES.get(site, site), fmt(c['docs_entrada']), fmt(c.get('duplicatas_removidas', 0)),
                       fmt(c.get('docs_saida', 0)), fmt(c.get('receitas', 0)),
                       fmt(c['chars_brutos'] / 1e6, 1), fmt(c.get('chars_limpos', 0) / 1e6, 1),
                       fmt(c.get('meta_tempo_total_min', 0))])
    t = e['total']
    linhas.append([r'\textbf{Total}', fmt(t['docs_entrada']), fmt(t['duplicatas_removidas']), fmt(t['docs_saida']),
                   fmt(t['receitas']), fmt(t['chars_brutos'] / 1e6, 1), fmt(t['chars_limpos'] / 1e6, 1),
                   fmt(t['meta_tempo_total_min'])])
    tabela('limpeza.tex', 'Resultado da limpeza e deduplicação por fonte', 'tab:limpeza',
           ['Fonte', 'Entrada', 'Duplicatas', 'Mantidos', 'Receitas', 'Texto bruto\n(M caract.)',
            'Texto limpo\n(M caract.)', 'Com tempo\nde preparo'], linhas, 'lrrrrrrr')


# --- Zipf e Heaps --------------------------------------------------------------------
def frequencias(nome):
    with (config.INDICES / f'exp_{nome}' / 'frequencias.tsv').open(encoding='utf-8') as f:
        next(f)
        return [(l.split('\t')[0], int(l.split('\t')[1])) for l in f]


def zipf_heaps(exp):
    bruto = 'sw-nenhuma__st-nenhum'
    freq = np.array([c for _, c in frequencias(bruto)], dtype=float)
    rank = np.arange(1, len(freq) + 1)
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    ax.loglog(rank, freq, color=COR[0], linewidth=2, label='vocabulário observado')
    ax.loglog(rank, freq[0] / rank, color=TINTA_2, linewidth=1, linestyle='--', label='Zipf ideal (f ∝ 1/r)')
    ax.set_xlabel('posição no ranking (r)')
    ax.set_ylabel('frequência na coleção (f)')
    ax.set_title('Lei de Zipf (sem remoção de stopwords nem stemming)')
    ax.legend(loc='lower left')
    salvar(fig, 'zipf.png')

    meta = json.loads((config.INDICES / f'exp_{bruto}' / 'meta.json').read_text(encoding='utf-8'))
    n, v = (np.array(x, dtype=float) for x in zip(*meta['heaps']))
    beta, log_k = np.polyfit(np.log(n), np.log(v), 1)
    k = float(np.exp(log_k))
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    ax.plot(n / 1e6, v / 1e3, color=COR[0], linewidth=2, label='vocabulário observado')
    ax.plot(n / 1e6, k * n ** beta / 1e3, color=TINTA_2, linewidth=1, linestyle='--',
            label=f'ajuste $V = {fmt(k, 1).replace(",", "{,}")}\\,n^{{{fmt(beta, 3).replace(",", "{,}")}}}$')
    ax.set_xlabel('ocorrências indexadas (milhões)')
    ax.set_ylabel('termos distintos (mil)')
    ax.set_title('Lei de Heaps — crescimento do vocabulário')
    ax.legend(loc='lower right')
    salvar(fig, 'heaps.png')
    return {'heaps_k': k, 'heaps_beta': float(beta)}


# --- Pré-processamento ---------------------------------------------------------------
SW = [('nenhuma', 'sem stopwords'), ('nltk', 'stopwords NLTK'), ('nltk_dominio', 'NLTK + domínio')]
ST = [('nenhum', 'nenhum'), ('plural', 'plural'), ('rslp', 'RSLP'), ('snowball', 'Snowball')]


def preprocessamento(exp):
    medidas = [('vocabulario', 'Vocabulário (mil termos)', 1e3), ('indice_mb', 'Tamanho do índice (MiB)', 1)]
    fig, eixos = plt.subplots(1, 2, figsize=(9, 3.4))
    largura = 0.26
    x = np.arange(len(ST))
    for ax, (campo, titulo, escala) in zip(eixos, medidas):
        for i, (sw, rotulo) in enumerate(SW):
            valores = [exp[f'sw-{sw}__st-{st}'][campo] / escala for st, _ in ST]
            barras = ax.bar(x + (i - 1) * largura, valores, largura - 0.03, color=COR[i], label=rotulo)
            if i == 0:
                ax.bar_label(barras, fmt=' %.0f', fontsize=7, color=TINTA_2, padding=1)
        ax.set_xticks(x, [r for _, r in ST])
        ax.set_xlabel('stemmer')
        ax.set_title(titulo)
        ax.grid(axis='x', visible=False)
    eixos[0].legend(loc='upper right', fontsize=8)
    salvar(fig, 'preprocessamento.png')

    linhas = []
    for sw, rsw in SW:
        for st, rst in ST:
            e = exp[f'sw-{sw}__st-{st}']
            linhas.append([rsw, rst, fmt(e['vocabulario']), fmt(e['ocorrencias'] / 1e6, 2), fmt(e['postings'] / 1e6, 2),
                           fmt(e['indice_mb'], 1), fmt(e['tempo_total_s'], 1), fmt(e['tempo_analise_s'], 1)])
    for nome, rotulo in (('sw-nltk_dominio__st-rslp__acentos', 'mantendo acentos'),
                         ('sw-nltk_dominio__st-rslp__numeros', 'indexando números')):
        e = exp[nome]
        linhas.append(['NLTK + domínio', f'RSLP, {rotulo}', fmt(e['vocabulario']), fmt(e['ocorrencias'] / 1e6, 2),
                       fmt(e['postings'] / 1e6, 2), fmt(e['indice_mb'], 1), fmt(e['tempo_total_s'], 1),
                       fmt(e['tempo_analise_s'], 1)])
    tabela('preprocessamento.tex', 'Efeito das transformações léxicas (granularidade documento, índice posicional)',
           'tab:preprocessamento', ['Stopwords', 'Stemmer', 'Vocabulário', 'Ocorrências\n(milhões)',
                                    'Postings\n(milhões)', 'Índice\n(MiB)', 'Tempo\ntotal (s)', 'Análise\nléxica (s)'],
           linhas, 'llrrrrrr')


def analise_stemming():
    """Conflação: quantas palavras distintas cada stemmer junta num mesmo radical."""
    cache = config.RESULTADOS / 'vocabulario_bruto.tsv'
    if not cache.exists():
        a = Analisador(stopwords='nltk', stemmer='nenhum', remover_acentos=False)
        contagem = Counter()
        with config.CORPUS_LIMPO.open(encoding='utf-8') as f:
            for linha in f:
                d = json.loads(linha)
                texto = ' '.join([d['titulo'], d['descricao'], *d['ingredientes'], *d['preparo'], d['corpo']])
                contagem.update(a.analisar(texto))
        with cache.open('w', encoding='utf-8', newline='\n') as f:
            for palavra, c in contagem.most_common():
                f.write(f'{palavra}\t{c}\n')
    contagem = {}
    with cache.open(encoding='utf-8') as f:
        for linha in f:
            p, c = linha.rstrip('\n').split('\t')
            contagem[p] = int(c)
    frequentes = [p for p, c in contagem.items() if c >= 5]  # ignora erros de digitação raros
    linhas, exemplos = [], []
    for st in STEMMERS:
        radical = Analisador(stopwords='nenhuma', stemmer=st, remover_acentos=False).radical
        grupos = defaultdict(list)
        for p in frequentes:
            grupos[radical(p)].append(p)
        tamanhos = [len(g) for g in grupos.values()]
        linhas.append([dict(ST)[st], fmt(len(frequentes)), fmt(len(grupos)), fmt(100 * (1 - len(grupos) / len(frequentes)), 1) + r'\%',
                       fmt(np.mean(tamanhos), 2), max(tamanhos)])
        if st != 'nenhum':
            exemplos.append(f'## {st}')
            for alvo in ('cebola', 'batata', 'assado', 'massa', 'pão', 'mexer', 'forno', 'leite'):
                r = radical(alvo)
                grupo = sorted(grupos.get(r, []), key=lambda w: -contagem[w])[:12]
                exemplos.append(f'{alvo} -> {r}: {", ".join(grupo)}')
            maiores = sorted(grupos.items(), key=lambda g: -len(g[1]))[:5]
            for r, g in maiores:
                exemplos.append(f'maior grupo {r!r} ({len(g)}): {", ".join(sorted(g, key=lambda w: -contagem[w])[:15])}')
    tabela('stemming.tex', 'Conflação de palavras por stemmer (palavras com frequência $\\geq 5$, stopwords NLTK)',
           'tab:stemming', ['Stemmer', 'Palavras', 'Radicais', 'Redução', 'Palavras/radical', 'Maior grupo'],
           linhas, 'lrrrrr')
    (config.RESULTADOS / 'stemming_exemplos.txt').write_text('\n'.join(exemplos) + '\n', encoding='utf-8')


# --- Granularidade -------------------------------------------------------------------
def granularidade(exp):
    tams = [32, 64, 128, 256, 512]
    chunks = [exp[f'chunk{t}'] for t in tams]
    medidas = [('unidades', 'Unidades indexadas (mil)', 1e3), ('indice_mb', 'Tamanho do índice (MiB)', 1),
               ('tempo_total_s', 'Tempo de indexação (s)', 1)]
    fig, eixos = plt.subplots(1, 3, figsize=(10, 3.2))
    for ax, (campo, titulo, escala) in zip(eixos, medidas):
        valores = [c[campo] / escala for c in chunks]
        ax.plot(tams, valores, color=COR[0], linewidth=2, marker='o', markersize=5)
        ref = exp['documento'][campo] / escala
        ax.axhline(ref, color=TINTA_2, linewidth=1, linestyle='--')
        ax.annotate('documento inteiro', (tams[0], ref), xytext=(0, 4), textcoords='offset points',
                    ha='left', fontsize=7, color=TINTA_2)
        ax.set_xscale('log', base=2)
        ax.set_xticks(tams, [str(t) for t in tams])
        ax.set_xlabel('termos por trecho')
        ax.set_title(titulo)
        ax.annotate(fmt(valores[0], 0 if valores[0] >= 10 else 1), (tams[0], valores[0]), xytext=(6, 0),
                    textcoords='offset points', fontsize=7, color=TINTA)
    salvar(fig, 'chunks.png')

    linhas = []
    ordem = [('documento', 'Documento', '--'), ('campos', 'Campos (zonas)', '--')]
    ordem += [(f'chunk{t}', f'Trecho de {t}', '0') for t in tams]
    ordem += [(f'chunk128_sob{s}', 'Trecho de 128', str(s)) for s in (16, 32, 64)]
    for nome, rotulo, sob in ordem:
        e = exp[nome]
        linhas.append([rotulo, sob, fmt(e['unidades']), fmt(e['vocabulario']), fmt(e['postings'] / 1e6, 2),
                       fmt(e['ocorrencias'] / 1e6, 2), fmt(e['indice_mb'], 1), fmt(e['tempo_total_s'], 1),
                       fmt(e['ram_acrescimo_mb'], 0)])
    tabela('granularidade.tex', 'Granularidade da representação (NLTK + domínio, RSLP, posicional)',
           'tab:granularidade', ['Granularidade', 'Sobre-\nposição', 'Unidades', 'Vocabulário', 'Postings\n(milhões)',
                                 'Posições\n(milhões)', 'Índice\n(MiB)', 'Tempo\n(s)', 'RAM extra\n(MiB)'],
           linhas, 'lrrrrrrrr')


# --- Bloco SPIMI ---------------------------------------------------------------------
def bloco(exp):
    nomes = ['bloco100000', 'bloco500000', 'bloco2000000', 'bloco5000000', 'bloco_ilimitado']
    rotulos = ['100 mil', '500 mil', '2 M', '5 M', 'sem limite']
    es = [exp[n] for n in nomes]
    fig, eixos = plt.subplots(1, 2, figsize=(8.5, 3.2))
    for ax, (campo, titulo) in zip(eixos, [('ram_acrescimo_mb', 'Pico de memória acima do inicial (MiB)'),
                                           ('tempo_total_s', 'Tempo total de indexação (s)')]):
        valores = [e[campo] for e in es]
        barras = ax.bar(rotulos, valores, 0.6, color=COR[0])
        ax.bar_label(barras, labels=[fmt(v, 0) for v in valores], fontsize=7, color=TINTA_2, padding=2)
        ax.set_xlabel('postings por lote')
        ax.set_title(titulo)
        ax.grid(axis='x', visible=False)
    salvar(fig, 'bloco_spimi.png')
    linhas = [[r, fmt(e['blocos']), fmt(e['ram_acrescimo_mb'], 1), fmt(e['tempo_inversao_s'], 1),
               fmt(e['tempo_blocos_s'], 2), fmt(e['tempo_merge_s'], 2), fmt(e['tempo_total_s'], 1)]
              for r, e in zip(rotulos, es)]
    tabela('bloco_spimi.tex', 'Tamanho do lote na construção SPIMI (índice por campos, posicional)', 'tab:bloco',
           ['Postings\npor lote', 'Lotes', 'RAM extra\n(MiB)', 'Montagem em\nmemória (s)', 'Escrita dos\nlotes (s)',
            'Intercalação\n(s)', 'Total\n(s)'], linhas, 'lrrrrrr')


# --- Estrutura e tempos --------------------------------------------------------------
def estrutura(exp):
    pares = [('documento', 'Documento, posicional'), ('documento_sem_posicoes', 'Documento, sem posições'),
             ('campos', 'Campos, posicional'), ('campos_sem_posicoes', 'Campos, sem posições'),
             ('campos_apenas_receitas', 'Campos, só receitas')]
    linhas = []
    for nome, rotulo in pares:
        e = exp[nome]
        linhas.append([rotulo, fmt(e['documentos']), fmt(e['vocabulario']), fmt(e['postings_mb'], 1),
                       fmt(e['postings_int32_mb'], 1), fmt(e['compressao_vbyte'], 2) + r'$\times$',
                       fmt(e['lexico_mb'], 1), fmt(e['unidades_mb'], 1), fmt(e['indice_mb'], 1)])
    tabela('estrutura.tex', 'Espaço ocupado pelo índice: posições, compressão VByte e escopo', 'tab:estrutura',
           ['Configuração', 'Documentos', 'Vocabulário', 'Postings\nVByte (MiB)', 'Postings\nint32 (MiB)',
            'Compressão', 'Léxico\n(MiB)', 'Unidades\n(MiB)', 'Total\n(MiB)'], linhas, 'lrrrrrrrr')

    fases = [('tempo_leitura_s', 'leitura do JSON'), ('tempo_analise_s', 'análise léxica'),
             ('tempo_inversao_s', 'montagem em memória'), ('tempo_merge_s', 'lotes e intercalação')]
    configs = [('documento', 'Documento'), ('campos', 'Campos'), ('chunk128', 'Trecho de 128'),
               ('chunk128_sob64', 'Trecho de 128, sobrep. 64')]
    fig, ax = plt.subplots(figsize=(7.5, 2.6))
    esquerda = np.zeros(len(configs))
    for i, (campo, rotulo) in enumerate(fases):
        valores = np.array([exp[n][campo] + (exp[n]['tempo_blocos_s'] if campo == 'tempo_merge_s' else 0)
                            for n, _ in configs])
        ax.barh([r for _, r in configs], valores, left=esquerda, height=0.55, color=COR[i], label=rotulo,
                edgecolor='white', linewidth=1)
        esquerda += valores
    for y, total in enumerate(esquerda):
        ax.annotate(f'{fmt(total, 0)} s', (total, y), xytext=(4, 0), textcoords='offset points', va='center',
                    fontsize=8, color=TINTA)
    ax.invert_yaxis()
    ax.set_xlim(0, esquerda.max() * 1.1)
    ax.set_xlabel('segundos')
    ax.set_title('Tempo de indexação por fase')
    ax.grid(axis='y', visible=False)
    ax.legend(ncol=4, loc='upper center', bbox_to_anchor=(0.5, -0.28), fontsize=8)
    salvar(fig, 'tempos_fases.png')


def main():
    exp = carregar()
    tabela_limpeza()
    resumo = zipf_heaps(exp)
    preprocessamento(exp)
    granularidade(exp)
    bloco(exp)
    estrutura(exp)
    analise_stemming()
    (config.RESULTADOS / 'resumo_graficos.json').write_text(json.dumps(resumo, indent=2) + '\n', encoding='utf-8')
    print('figuras em', config.FIGURAS, '| tabelas em', TABELAS, '|', resumo)


if __name__ == '__main__':
    main()
