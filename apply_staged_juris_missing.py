#!/usr/bin/env python3
"""Append reviewed staged missing jurisprudence records to the local dataset.

The staging folder is produced by:
  /Users/lszoszk/Desktop/AI/HURIDOCS/App/pipeline/stage_juris_missing_ingest.py

Only records listed in staged_jurisprudence_info_ready.json are applied.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_INFO = ROOT / 'mysite_pythonanywhere' / 'jurisprudence_info.json'
DEFAULT_STAGE = Path('/Users/lszoszk/Desktop/AI/HURIDOCS/App/output/juris_ohchr_missing_sources/CCPR/staged_ingest')
DEFAULT_REPORT = Path('/Users/lszoszk/Desktop/AI/HURIDOCS/App/output/juris_ohchr_missing_sources/CCPR/apply_staged_report.json')


def read_json(path: Path):
    with path.open(encoding='utf-8') as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    with path.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--info', type=Path, default=DEFAULT_INFO)
    ap.add_argument('--stage', type=Path, default=DEFAULT_STAGE)
    ap.add_argument('--report', type=Path, default=DEFAULT_REPORT)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--replace-if-better', action='store_true',
                    help='Replace an existing record only when staged text is substantially fuller.')
    args = ap.parse_args()

    docs = read_json(args.info)
    staged = read_json(args.stage / 'staged_jurisprudence_info_ready.json')
    by_doc_id = {doc.get('docId'): doc for doc in docs}
    by_symbol = {doc.get('symbol'): doc for doc in docs}

    added = []
    replaced = []
    skipped = []
    for row in staged:
        doc_id = row.get('docId')
        symbol = row.get('symbol')
        if doc_id in by_doc_id:
            existing = by_doc_id[doc_id]
            old_paras = int(existing.get('paragraphCount') or 0)
            new_paras = int(row.get('paragraphCount') or 0)
            old_words = int(existing.get('wordCount') or 0)
            new_words = int(row.get('wordCount') or 0)
            better = new_paras >= max(old_paras + 10, int(old_paras * 1.35)) or new_words >= max(old_words + 1000, int(old_words * 1.35))
            if args.replace_if_better and better:
                src = args.stage / row['sourceFile']
                dst = ROOT / row['sourceFile']
                if not src.exists():
                    skipped.append({'docId': doc_id, 'symbol': symbol, 'reason': f'missing_paragraph_json:{src}'})
                    continue
                replacement = dict(row)
                if existing.get('firstAddedAt'):
                    replacement['firstAddedAt'] = existing.get('firstAddedAt')
                replacement['replacedFrom'] = {
                    'paragraphCount': old_paras,
                    'wordCount': old_words,
                    'name': existing.get('name') or '',
                    'jurisCaseId': existing.get('jurisCaseId') or '',
                }
                replaced.append(replacement)
                if not args.dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    docs[docs.index(existing)] = replacement
                    by_doc_id[doc_id] = replacement
                    by_symbol[symbol] = replacement
                continue
            skipped.append({'docId': doc_id, 'symbol': symbol, 'reason': 'docId_exists'})
            continue
        if symbol in by_symbol:
            skipped.append({'docId': doc_id, 'symbol': symbol, 'reason': 'symbol_exists'})
            continue
        src = args.stage / row['sourceFile']
        dst = ROOT / row['sourceFile']
        if not src.exists():
            skipped.append({'docId': doc_id, 'symbol': symbol, 'reason': f'missing_paragraph_json:{src}'})
            continue
        added.append(row)
        if not args.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            docs.append(row)
            by_doc_id[doc_id] = row
            by_symbol[symbol] = row

    if not args.dry_run:
        docs.sort(key=lambda d: (d.get('treaty') or '', d.get('year') or 0, d.get('symbol') or ''))
        write_json(args.info, docs)

    report = {
        'stage': str(args.stage),
        'inputReadyRows': len(staged),
        'addedRows': len(added),
        'replacedRows': len(replaced),
        'skippedRows': len(skipped),
        'dryRun': args.dry_run,
        'replaceIfBetter': args.replace_if_better,
        'added': [{'docId': r.get('docId'), 'symbol': r.get('symbol'), 'title': r.get('title')} for r in added],
        'replaced': [
            {
                'docId': r.get('docId'),
                'symbol': r.get('symbol'),
                'title': r.get('title'),
                'fromParagraphs': r.get('replacedFrom', {}).get('paragraphCount'),
                'toParagraphs': r.get('paragraphCount'),
            }
            for r in replaced
        ],
        'skipped': skipped,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
