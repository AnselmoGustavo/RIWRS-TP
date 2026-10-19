"""Unifica JSONL de duas coletas ZIP, sem banco e sem acessar os sites."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile


def records(path):
    with ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if '/collected/' not in '/' + name or not name.endswith('.jsonl'):
                continue
            with archive.open(name) as stream:
                for line_no, line in enumerate(stream, 1):
                    if line.strip():
                        yield name, line_no, json.loads(line)


def score(doc):
    try:
        date = datetime.fromisoformat(doc.get('fetched_at', '').replace('Z', '+00:00'))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        stamp = date.timestamp()
    except (ValueError, TypeError, AttributeError):
        stamp = float('-inf')
    completeness = sum(bool(doc.get(k)) for k in ('title', 'text', 'ingredients', 'instructions', 'recipe_data'))
    return stamp, completeness, len(doc.get('text') or '')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def unify(inputs, output):
    output.mkdir(parents=True, exist_ok=False)
    winners, input_counts, file_counts = {}, Counter(), Counter()
    read_count = 0
    # Guarda só os localizadores dos vencedores, sem carregar o corpus inteiro na RAM.
    for source, path in enumerate(inputs):
        for name, line, doc in records(path):
            if not isinstance(doc, dict) or not isinstance(doc.get('url'), str) or not doc['url'].strip():
                raise ValueError(f'Registro sem URL válida: {path.name}:{name}:{line}')
            url = doc['url'].strip()
            rank = score(doc)
            candidate = (source, name, line)
            prior = winners.get(url)
            if prior is None or rank > prior[0]:
                winners[url] = (rank, candidate)
            read_count += 1
            input_counts[path.name] += 1
            file_counts[(path.name, name)] += 1
    locations = {value[1] for value in winners.values()}
    retained, discarded = Counter(), Counter()
    corpus_path = output / 'corpus.jsonl'
    with corpus_path.open('w', encoding='utf-8', newline='\n') as corpus, (output / 'duplicatas_removidas.csv').open('w', encoding='utf-8-sig', newline='') as audit:
        writer = csv.writer(audit)
        writer.writerow(['url', 'zip_removido', 'arquivo_removido', 'linha_removida', 'zip_mantido', 'arquivo_mantido', 'linha_mantida'])
        doc_id = 0
        for source, path in enumerate(inputs):
            for name, line, doc in records(path):
                url = doc['url'].strip()
                loc = (source, name, line)
                if loc not in locations:
                    winner = winners[url][1]
                    writer.writerow([url, path.name, name, line, inputs[winner[0]].name, winner[1], winner[2]])
                    discarded[(path.name, doc.get('site', 'desconhecido'))] += 1
                    continue
                doc_id += 1
                doc['doc_id'] = doc_id
                doc['url'] = url
                doc['provenance'] = {'source_zip': path.name, 'source_member': name, 'source_line': line}
                # Os campos originais são preservados; não inventamos ingredientes ausentes.
                corpus.write(json.dumps(doc, ensure_ascii=False, separators=(',', ':')) + '\n')
                retained[(path.name, doc.get('site', 'desconhecido'))] += 1
    with (output / 'inventario_fontes.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['zip_origem', 'site', 'registros_lidos', 'registros_mantidos', 'duplicatas_url_removidas'])
        for key in sorted(set(retained) | set(discarded)):
            writer.writerow([*key, retained[key] + discarded[key], retained[key], discarded[key]])
    reports = output / 'relatorios_originais'
    for i, path in enumerate(inputs, 1):
        folder = reports / f'coleta_{i}'
        folder.mkdir(parents=True)
        with ZipFile(path) as archive:
            for name in archive.namelist():
                if '/.venv/' not in '/' + name and Path(name).name in ('summary.json', 'metrics.csv', 'config_execucao.json', 'tabela_overleaf.tex'):
                    # Entradas de ZIP nunca são usadas como caminho de extração.
                    destination = folder / Path(name).name
                    if destination.exists():
                        raise ValueError('Mais de uma execução no ZIP: separe-as antes de unificar.')
                    destination.write_bytes(archive.read(name))
    manifest = {
        'schema_version': 1,
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'input_records': read_count,
        'retained_records': len(winners),
        'removed_duplicate_url_records': read_count - len(winners),
        'deduplication_key': 'url original após strip(); comparação exata, sensível a caminho e query',
        'selection_rule': 'fetched_at mais recente; desempate por campos preenchidos, tamanho do texto e primeira ocorrência',
        'content_deduplication_applied': False,
        'recipe_reclassification_applied': False,
        'sources': [{'file': path.name, 'sha256': digest(path), 'records_read': input_counts[path.name]} for path in inputs],
        'member_counts': [{'zip': key[0], 'member': key[1], 'records': count} for key, count in sorted(file_counts.items())],
        'corpus': {'file': 'corpus.jsonl', 'size_bytes': corpus_path.stat().st_size, 'sha256': digest(corpus_path)},
        'counts_are_from_jsonl': True,
    }
    (output / 'manifesto.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zips', nargs='+', type=Path)
    parser.add_argument('--saida', type=Path, required=True, help='Nova pasta que ainda não existe')
    args = parser.parse_args()
    unify(args.zips, args.saida)
