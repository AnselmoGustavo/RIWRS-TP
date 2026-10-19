"""Etapa A: limpeza, extração de campos, classificação e deduplicação do corpus.

Lê o corpus.jsonl da parte 1 e grava saida/corpus_limpo.jsonl, com um documento
por linha dividido nos campos titulo, descricao, ingredientes, preparo e corpo.
Usa somente a biblioteca padrão. Três passadas sobre o arquivo:

1. amostra de cada site para descobrir trechos repetidos (boilerplate);
2. limpeza de cada documento, gravada num arquivo temporário;
3. deduplicação por URL normalizada e por conteúdo, com novos doc_id sequenciais.
"""
import argparse
import csv
import hashlib
import html
import json
import re
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

import config

# --- Boilerplate ----------------------------------------------------------------
N_SHINGLE = 8             # tamanho da janela de palavras
LIMIAR_BOILERPLATE = 0.20  # fração mínima de páginas do site que contêm a janela
MIN_DOCS_BOILERPLATE = 5
AMOSTRA_POR_SITE = 1500

# --- Marcadores de seção da coleta 1 ----------------------------------------------
# (início dos ingredientes, início do preparo, fim da receita, corte extra dos ingredientes)
MARCADORES = {
    'estadao_paladar': (r'\bIngredientes\b', r'\bPreparo\b',
                        r'Compartilhar Siga nas redes|\bVeja mais\b|Tudo Sobre\b', None),
    'panelinha': (r'\bIngredientes\b', r'\bModo de preparo\b',
                  r'PODE ARMAZENAR|Veja a receita em vídeo|Autor Panelinha|Tempo de preparo|Siga o Panelinha', None),
    'receitas_globo': (r'\bIngredientes\b', r'\bModo de [Pp]reparo\b',
                       r'\b\d+ de \d+(?=\S)|Webstories|Confira (?:outras|mais)|Mais Receitas Navegue|globo entretenimento',
                       r'De olho no gshow'),
    'tudogostoso': (r'\bIngredientes\b', r'\bModo de preparo\b',
                    r'Veja também…|Categorias relacionadas|Denunciar conteúdo', None),
    'tudoreceitas': (r'\bIngredientes:', r'\bComo fazer [^:]{1,200}:',
                     r'Se você gostou da receita|Valor nutricional|Categorias relacionadas', r'Ver informação nutricional'),
    'terra_degusta': (r'\bIngredientes\b', r'\bModo de preparo\b',
                      r'Por: [^|]{0,120}?Compartilhar|Compartilhar TAGS|Comentários \(', None),
}
MARCADORES = {s: tuple(re.compile(p) if p else None for p in m) for s, m in MARCADORES.items()}
# Abas de navegação "Resumo Ingredientes Modo de preparo Comentários" do Receitas Globo.
ABAS_GLOBO = re.compile(r'Resumo Ingredientes Modo de preparo Comentários')
FRASES_RUIDO = re.compile(r'Continua após (?:a publicidade|patrocínio)|\bPUBLICIDADE\b|Publicidade\b')
# Listas de links para outras páginas: o corpo é cortado no primeiro desses marcadores.
CORTE_CORPO = re.compile(r'Gostou\? Então vai querer ver estas|Últimas matérias|Últimas: |Receitas relacionadas|'
                         r'Mais Receitas Navegue por categoria|Os mais vistos|Recomendado por Taboola|Posts relacionados')
PREFIXO_PREPARO = re.compile(r'^(?:Modo de preparo\s*:\s*(?:\d+\s*h)?\s*(?:\d+\s*min)?\s*)')

SUFIXO_TITULO = re.compile(
    r'(?:\s*[-|–]\s*(?:Panelinha|Estadão|TudoGostoso|Receitas|Vídeos|Ana Maria Brogui|Teleculinária|Petitchef))+\s*$',
    re.I)
TITULO_TUDOGOSTOSO = re.compile(r'^Receita de (.+?), enviada por .+$')
CONTROLE = re.compile(r'[\u0000-\u0008\u000b-\u001f\u007f-\u009f​-‏  ﻿�]')
ESPACOS = re.compile(r'\s+')


def normalizar(texto):
    """Decodifica entidades HTML, aplica NFC, remove caracteres de controle e espaços extras."""
    if not texto:
        return ''
    texto = unicodedata.normalize('NFC', html.unescape(str(texto)))
    return ESPACOS.sub(' ', CONTROLE.sub(' ', texto)).strip()


def chave_comparacao(texto):
    return ESPACOS.sub(' ', texto.lower()).strip()


def url_normalizada(url):
    """Host minúsculo sem www, sem esquema, fragmento e barra final; preserva caminho e query."""
    partes = urlsplit(url.strip())
    host = partes.netloc.lower()
    if host.startswith('www.'):
        host = host[4:]
    caminho = partes.path.rstrip('/')
    return host + caminho + ('?' + partes.query if partes.query else '')


# --- Boilerplate por janelas de palavras ------------------------------------------
def janelas(tokens):
    return [hash(tuple(tokens[i:i + N_SHINGLE])) for i in range(len(tokens) - N_SHINGLE + 1)]


def amostrado(doc_id, fracao):
    # Amostragem determinística pelo doc_id (hash multiplicativo de Knuth).
    return (doc_id * 2654435761 % 2 ** 32) / 2 ** 32 < fracao


def aprender_boilerplate(caminho, docs_por_site):
    df, n_amostra = defaultdict(Counter), Counter()
    for doc in ler_jsonl(caminho):
        site = doc['site']
        if not amostrado(doc['doc_id'], AMOSTRA_POR_SITE / docs_por_site[site]):
            continue
        n_amostra[site] += 1
        df[site].update(set(janelas(doc['text'].split())))
    padroes = {}
    for site, contagem in df.items():
        minimo = max(MIN_DOCS_BOILERPLATE, LIMIAR_BOILERPLATE * n_amostra[site])
        padroes[site] = {h for h, c in contagem.items() if c >= minimo}
    return padroes, n_amostra


def remover_boilerplate(texto, padroes):
    tokens = texto.split()
    if not padroes or len(tokens) < N_SHINGLE:
        return texto
    marca = bytearray(len(tokens))
    for i, h in enumerate(janelas(tokens)):
        if h in padroes:
            marca[i:i + N_SHINGLE] = b'\x01' * N_SHINGLE
    return ' '.join(t for t, m in zip(tokens, marca) if not m)


# --- Extração de campos -------------------------------------------------------------
def limpar_titulo(titulo, site):
    titulo = normalizar(titulo)
    if site == 'tudogostoso':
        m = TITULO_TUDOGOSTOSO.match(titulo)
        if m:
            return m.group(1)
    return SUFIXO_TITULO.sub('', titulo).strip() or titulo


def secoes_coleta_1(texto, site):
    """Localiza ingredientes e preparo pelos marcadores do site. Devolve (ingr, preparo, inicio, fim)."""
    m_ingr, m_prep, m_fim, m_corte = MARCADORES[site]
    if site == 'receitas_globo':
        texto = ABAS_GLOBO.sub(lambda m: ' ' * len(m.group()), texto)  # mesmo comprimento: preserva os índices
    for ingr in m_ingr.finditer(texto):
        prep = m_prep.search(texto, ingr.end())
        if not prep:
            return '', '', None, None
        if prep.start() - ingr.end() < 30:  # "Ingredientes Modo de preparo" é menu, não seção
            continue
        fim = m_fim.search(texto, prep.end())
        fim_pos = fim.start() if fim else len(texto)
        ingredientes = texto[ingr.end():prep.start()]
        if m_corte:
            corte = m_corte.search(ingredientes)
            if corte:
                ingredientes = ingredientes[:corte.start()]
        preparo = texto[prep.end():fim_pos]
        limpa = lambda s: normalizar(FRASES_RUIDO.sub(' ', s)).strip(' :.-')
        return limpa(ingredientes), limpa(PREFIXO_PREPARO.sub('', limpa(preparo))), ingr.start(), fim_pos
    return '', '', None, None


def passos(instrucoes):
    """Achata HowToStep, HowToSection e strings da coleta 2 numa lista de passos."""
    if isinstance(instrucoes, str):
        return [normalizar(instrucoes)] if instrucoes.strip() else []
    saida = []
    for item in instrucoes or []:
        if isinstance(item, str):
            saida.append(normalizar(item))
        elif isinstance(item, dict):
            if item.get('@type') == 'HowToSection':
                saida.extend(passos(item.get('itemListElement') or []))
            else:
                saida.append(normalizar(item.get('text') or item.get('name') or ''))
    return [p for p in saida if p]


# --- Metadados para filtros futuros -------------------------------------------------
ISO_DURACAO = re.compile(r'^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?', re.I)
DURACAO_TEXTO = re.compile(r'(?:(\d+)\s*h)?\s*(?:(\d+)\s*m(?:in)?)?', re.I)
DIFICULDADES = {'fácil': 'fácil', 'facil': 'fácil', 'muito baixa': 'fácil', 'baixa': 'fácil',
                'médio': 'média', 'medio': 'média', 'média': 'média', 'media': 'média',
                'difícil': 'difícil', 'dificil': 'difícil', 'dificio': 'difícil', 'alta': 'difícil', 'muito alta': 'difícil'}


def minutos_iso(valor):
    m = ISO_DURACAO.match(valor or '') if isinstance(valor, str) else None
    if not m or not any(m.groups()):
        return None
    d, h, mi = (int(x or 0) for x in m.groups())
    return d * 1440 + h * 60 + mi or None


def minutos_texto(valor):
    m = DURACAO_TEXTO.fullmatch(valor.strip()) if valor else None
    if not m or not any(m.groups()):
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0) or None


def primeiro_numero(valor):
    if isinstance(valor, list):
        valor = valor[0] if valor else None
    m = re.search(r'\d+', str(valor)) if valor is not None else None
    return int(m.group()) if m else None


def texto_lista(valor):
    if isinstance(valor, list):
        return ', '.join(normalizar(v) for v in valor if isinstance(v, str))
    return normalizar(valor) if isinstance(valor, str) else ''


def metadados_coleta_2(doc):
    receita = next((r for r in doc.get('recipe_data') or [] if isinstance(r, dict)), {})
    meta = {
        'tempo_total_min': minutos_iso(receita.get('totalTime'))
        or ((minutos_iso(receita.get('prepTime')) or 0) + (minutos_iso(receita.get('cookTime')) or 0)) or None,
        'rendimento': primeiro_numero(receita.get('recipeYield')),
        'categoria': texto_lista(receita.get('recipeCategory')),
        'culinaria': texto_lista(receita.get('recipeCuisine')),
        'palavras_chave': texto_lista(receita.get('keywords')),
        'dificuldade': None,
    }
    # O receitasdeminuto publica a dificuldade no campo recipeCuisine.
    if meta['culinaria'].lower() in DIFICULDADES:
        meta['dificuldade'] = DIFICULDADES[meta['culinaria'].lower()]
        meta['culinaria'] = ''
    if meta['culinaria'] == 'Pt':  # valor genérico do petitchef
        meta['culinaria'] = ''
    return meta


PADROES_META = {
    'estadao_paladar': re.compile(r'Dificuldade (Fácil|Média|Difícil) Tempo de preparo (.+?) Rendimento (\d+)'),
    'receitas_globo': re.compile(r'Nível (Fácil|Médio|Difícil) Tempo (\S+)'),
    'tudoreceitas': re.compile(r'(\d+) pessoas? ((?:\d+h ?)?(?:\d+m)?) ?(?:([A-ZÀ-Ú][\wà-ú ]{0,30}?) )?'
                               r'Dificuldade (muito baixa|baixa|média|alta|muito alta)'),
    'tudogostoso': re.compile(r'Modo de preparo : ((?:\d+h)? ?(?:\d+min)?)'),
    'panelinha': re.compile(r'Tempo de preparo (.+?) Serve (?:Até )?(\d+)?'),
}
# Trilha "Categorias Receitas doces e sobremesas Cocada": a categoria vem em minúsculas antes do título.
CATEGORIA_TUDOGOSTOSO = re.compile(r'Categorias Receitas ([a-zà-ú][a-zà-ú, ]*?) (?=[A-ZÀ-Ú0-9])')
RENDIMENTO_TUDOGOSTOSO = re.compile(r'\((\d+) porç')


def metadados_coleta_1(texto, site):
    meta = {'tempo_total_min': None, 'rendimento': None, 'categoria': '', 'culinaria': '',
            'palavras_chave': '', 'dificuldade': None, 'tempo_texto': ''}
    padrao = PADROES_META.get(site)
    m = padrao.search(texto) if padrao else None
    if m:
        g = m.groups()
        if site == 'estadao_paladar':
            meta.update(dificuldade=DIFICULDADES[g[0].lower()], tempo_texto=g[1], rendimento=int(g[2]))
        elif site == 'receitas_globo':
            meta.update(dificuldade=DIFICULDADES[g[0].lower()], tempo_texto=g[1], tempo_total_min=minutos_texto(g[1]))
        elif site == 'tudoreceitas':
            meta.update(rendimento=int(g[0]), tempo_texto=g[1], tempo_total_min=minutos_texto(g[1]),
                        categoria=g[2] or '', dificuldade=DIFICULDADES[g[3]])
        elif site == 'tudogostoso':
            meta.update(tempo_texto=g[0], tempo_total_min=minutos_texto(g[0]))
        elif site == 'panelinha':
            meta.update(tempo_texto=g[0], rendimento=int(g[1]) if g[1] else None)
    if site == 'tudogostoso':
        c, r = CATEGORIA_TUDOGOSTOSO.search(texto), RENDIMENTO_TUDOGOSTOSO.search(texto)
        meta['categoria'] = c.group(1) if c else ''
        meta['rendimento'] = int(r.group(1)) if r else None
    return meta


# --- Documento limpo ------------------------------------------------------------------
def retirar(texto, trechos):
    """Remove do corpo os trechos que já foram para ingredientes/preparo (evita contagem dupla)."""
    for trecho in sorted(set(trechos), key=len, reverse=True):
        if len(trecho) >= 8:
            texto = texto.replace(trecho, ' ')
    return ESPACOS.sub(' ', texto).strip()


def limpar_documento(doc, padroes):
    site = doc['site']
    bruto = doc['text']
    titulo_bruto = normalizar(doc.get('title'))
    titulo = limpar_titulo(doc.get('title'), site)
    descricao = normalizar(doc.get('description'))
    if site in config.SITES_COLETA_2:
        coleta = 2
        ingredientes = [normalizar(i) for i in doc.get('ingredients') or [] if normalizar(i)]
        preparo = passos(doc.get('instructions'))
        corpo = retirar(normalizar(bruto), ingredientes + preparo)
        receita = doc.get('classification') in ('jsonld_recipe', 'structured_text') and bool(ingredientes) and bool(preparo)
        meta = metadados_coleta_2(doc)
    else:
        coleta = 1
        ingr, prep, ini, fim = secoes_coleta_1(bruto, site)
        corpo = bruto[:ini] + ' ' + bruto[fim:] if ini is not None else bruto
        ingredientes, preparo = ([ingr] if ingr else []), ([prep] if prep else [])
        receita = len(ingr) >= 15 and len(prep) >= 30
        meta = metadados_coleta_1(normalizar(bruto), site)
    corpo = normalizar(FRASES_RUIDO.sub(' ', corpo))
    corte = CORTE_CORPO.search(corpo)
    if corte:
        corpo = corpo[:corte.start()]
    for repetido in (titulo_bruto, titulo):  # o texto da coleta 1 começa repetindo o título
        if repetido and corpo.startswith(repetido):
            corpo = corpo[len(repetido):].lstrip()
    corpo_limpo = remover_boilerplate(corpo, padroes.get(site))
    return {
        'orig_doc_id': doc['doc_id'], 'url': doc['url'], 'site': site, 'coleta': coleta,
        'locale': doc.get('locale') or '', 'is_recipe': receita,
        'titulo': titulo, 'descricao': descricao, 'ingredientes': ingredientes, 'preparo': preparo,
        'corpo': corpo_limpo, 'meta': meta,
    }, len(bruto), len(corpo) - len(corpo_limpo)


def tamanho_campos(d):
    return len(d['titulo']) + len(d['descricao']) + sum(map(len, d['ingredientes'])) + sum(map(len, d['preparo'])) + len(d['corpo'])


def chave_conteudo(d):
    partes = [d['titulo'], ' '.join(d['ingredientes']), ' '.join(d['preparo'])] if d['is_recipe'] else [d['titulo'], d['corpo']]
    return hashlib.sha1('\x1f'.join(chave_comparacao(p) for p in partes).encode('utf-8')).hexdigest()


def preferencia(d):
    """Entre cópias, prefere https, URL em minúsculas, documento mais completo e o primeiro doc_id."""
    url = d['url']
    return (url.startswith('https://'), url == url.lower(), '://www.' not in url, d['is_recipe'],
            tamanho_campos(d), -d['orig_doc_id'])


# --- Execução -------------------------------------------------------------------------
def ler_jsonl(caminho):
    with open(caminho, encoding='utf-8') as f:
        for linha in f:
            if linha.strip():
                yield json.loads(linha)


class Grupos:
    """Union-find para juntar documentos repetidos por URL normalizada ou por conteúdo."""

    def __init__(self):
        self.pai = {}

    def achar(self, x):
        self.pai.setdefault(x, x)
        while self.pai[x] != x:
            self.pai[x] = self.pai[self.pai[x]]
            x = self.pai[x]
        return x

    def unir(self, a, b):
        self.pai[self.achar(a)] = self.achar(b)


def executar(entrada, saida_dir):
    saida_dir.mkdir(parents=True, exist_ok=True)
    tempos, inicio = {}, time.perf_counter()
    docs_por_site = Counter(d['site'] for d in ler_jsonl(entrada))
    padroes, n_amostra = aprender_boilerplate(entrada, docs_por_site)
    tempos['boilerplate_s'] = time.perf_counter() - inicio

    t = time.perf_counter()
    temporario = saida_dir / '_limpeza_tmp.jsonl'
    est = defaultdict(Counter)
    resumo, grupos = [], Grupos()
    primeiro_por_chave = {}
    with temporario.open('w', encoding='utf-8', newline='\n') as tmp:
        for i, doc in enumerate(ler_jsonl(entrada)):
            limpo, chars_brutos, chars_boiler = limpar_documento(doc, padroes)
            s = est[limpo['site']]
            s['docs_entrada'] += 1
            s['chars_brutos'] += chars_brutos
            s['chars_boilerplate_removidos'] += chars_boiler
            for chave in ('url:' + url_normalizada(limpo['url']), 'conteudo:' + chave_conteudo(limpo)):
                if chave in primeiro_por_chave:
                    grupos.unir(i, primeiro_por_chave[chave])
                else:
                    primeiro_por_chave[chave] = i
            resumo.append((preferencia(limpo), limpo['url'], limpo['site']))
            tmp.write(json.dumps(limpo, ensure_ascii=False, separators=(',', ':')) + '\n')
    tempos['limpeza_s'] = time.perf_counter() - t

    t = time.perf_counter()
    melhores = {}
    for i, (pref, _, _) in enumerate(resumo):
        g = grupos.achar(i)
        if g not in melhores or pref > resumo[melhores[g]][0]:
            melhores[g] = i
    mantidos = set(melhores.values())
    novo_id = 0
    with (saida_dir / 'duplicatas_conteudo.csv').open('w', encoding='utf-8-sig', newline='') as f_dup, \
            config.CORPUS_LIMPO.open('w', encoding='utf-8', newline='\n') as f_out:
        dup = csv.writer(f_dup)
        dup.writerow(['url_removida', 'site_removido', 'url_mantida', 'site_mantido'])
        for i, limpo in enumerate(ler_jsonl(temporario)):
            s = est[limpo['site']]
            if i not in mantidos:
                manter = melhores[grupos.achar(i)]
                dup.writerow([limpo['url'], limpo['site'], resumo[manter][1], resumo[manter][2]])
                s['duplicatas_removidas'] += 1
                continue
            novo_id += 1
            limpo = {'doc_id': novo_id, **limpo}
            s['docs_saida'] += 1
            s['receitas'] += limpo['is_recipe']
            s['chars_limpos'] += tamanho_campos(limpo)
            for k, v in limpo['meta'].items():
                s['meta_' + k] += bool(v)
            for campo in ('descricao', 'ingredientes', 'preparo', 'corpo'):
                s['com_' + campo] += bool(limpo[campo])
            f_out.write(json.dumps(limpo, ensure_ascii=False, separators=(',', ':')) + '\n')
    temporario.unlink()
    tempos['deduplicacao_s'] = time.perf_counter() - t
    tempos['total_s'] = time.perf_counter() - inicio

    total = Counter()
    for s in est.values():
        total.update(s)
    estatisticas = {
        'parametros': {'n_shingle': N_SHINGLE, 'limiar_boilerplate': LIMIAR_BOILERPLATE,
                       'min_docs_boilerplate': MIN_DOCS_BOILERPLATE, 'amostra_por_site': AMOSTRA_POR_SITE},
        'janelas_boilerplate_por_site': {s: len(p) for s, p in padroes.items()},
        'amostra_boilerplate_por_site': dict(n_amostra),
        'por_site': {s: dict(c) for s, c in sorted(est.items())},
        'total': dict(total),
        'tempos': tempos,
    }
    (saida_dir / 'estatisticas_limpeza.json').write_text(
        json.dumps(estatisticas, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'total': dict(total), 'tempos': tempos}, ensure_ascii=False, indent=2))
    return estatisticas


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--entrada', type=Path, default=config.CORPUS_ORIGINAL)
    args = parser.parse_args()
    executar(args.entrada, config.SAIDA)
