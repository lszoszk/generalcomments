#!/usr/bin/env python3
"""Refresh jurisprudence paragraph JSON with DOCX footnotes, preserving catalog metadata.

This is intentionally narrower than ``ingest_jurisprudence.py``:

* reads the current ``mysite_pythonanywhere/jurisprudence_info.json``;
* re-extracts paragraph JSON only for DOCX-backed cases;
* keeps enriched Tier-1 metadata such as case names, state party, articles,
  confidence flags, and Minnesota/front-matter provenance;
* optionally updates paragraph/word/label counts in the Tier-1 catalog.

Use ``--dry-run`` first. Only run ``--apply`` after checking the count-change
audit, because the newer extractor also skips some old session-header rows
that previously looked like paragraphs.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from ingest_jurisprudence import (
    OUT_INFO,
    OUT_DIR_PARAGRAPHS,
    choose_english_entry,
    extract_docx_paragraphs,
    label_paragraph,
    load_manifest_index,
    manifest_file_path,
)


def read_json(path: Path):
    return json.loads(path.read_text())


def paragraph_stats(paragraphs: list[dict]) -> dict:
    labels = Counter()
    labelled = 0
    footnote_paragraphs = 0
    footnotes = 0
    for p in paragraphs:
        p_labels = label_paragraph(p.get('Text') or '')
        p['Labels'] = p_labels
        if p_labels:
            labelled += 1
            labels.update(p_labels)
        fns = p.get('Footnotes') or []
        if fns:
            footnote_paragraphs += 1
            footnotes += len(fns)
    return {
        'paragraphCount': len(paragraphs),
        'wordCount': sum(len((p.get('Text') or '').split()) for p in paragraphs),
        'labelCount': labelled,
        'caseLabels': sorted(labels),
        'footnoteParagraphCount': footnote_paragraphs,
        'footnoteCount': footnotes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--treaty', help='Restrict to one treaty body, e.g. CEDAW')
    ap.add_argument('--limit', type=int, help='Cap processed DOCX cases')
    ap.add_argument('--doc-id', action='append', default=[], help='Process one docId; repeatable')
    ap.add_argument('--apply', action='store_true', help='Write paragraph JSON and update Tier-1 counts')
    ap.add_argument('--dry-run', action='store_true', help='Print audit without writing')
    ap.add_argument('--allow-count-changes', action='store_true',
                    help='Also write cases whose re-extracted paragraph count differs from the current JSON')
    args = ap.parse_args()

    if args.apply == args.dry_run:
        ap.error('Choose exactly one of --dry-run or --apply')

    docs = read_json(OUT_INFO)
    manifest = load_manifest_index()
    selected_ids = set(args.doc_id or [])
    treaty = (args.treaty or '').upper()

    candidates = []
    for doc in docs:
        if selected_ids and doc.get('docId') not in selected_ids:
            continue
        if treaty and (doc.get('treaty') or '').upper() != treaty:
            continue
        if (doc.get('sourceFormat') or '').lower() != 'docx':
            continue
        candidates.append(doc)
    if args.limit:
        candidates = candidates[:args.limit]

    print(f'Refreshing DOCX footnotes: {len(candidates)} candidate case(s); apply={args.apply}')

    by_doc_id = {d['docId']: d for d in docs}
    processed = 0
    skipped = 0
    changed_counts = []
    skipped_count_changes = 0
    with_footnotes = 0
    total_footnotes = 0
    written = 0
    written_footnote_paragraphs = 0
    written_footnotes = 0

    for i, doc in enumerate(candidates, 1):
        entries = manifest.get(doc.get('symbol') or '', [])
        chosen = choose_english_entry(entries)
        if not chosen or (chosen.get('format') or '').lower() != 'docx':
            skipped += 1
            continue
        raw_path = manifest_file_path(chosen)
        if not raw_path or not raw_path.exists():
            skipped += 1
            continue

        try:
            paragraphs = extract_docx_paragraphs(raw_path)
        except Exception as exc:
            print(f'  [warn] {doc["docId"]}: {exc}')
            skipped += 1
            continue
        if not paragraphs:
            skipped += 1
            continue

        stats = paragraph_stats(paragraphs)
        processed += 1
        with_footnotes += stats['footnoteParagraphCount']
        total_footnotes += stats['footnoteCount']

        old_count = int(doc.get('paragraphCount') or 0)
        count_changed = old_count != stats['paragraphCount']
        if count_changed:
            changed_counts.append({
                'docId': doc['docId'],
                'symbol': doc.get('symbol'),
                'old': old_count,
                'new': stats['paragraphCount'],
                'delta': stats['paragraphCount'] - old_count,
            })
            if args.apply and not args.allow_count_changes:
                skipped_count_changes += 1
                continue

        if args.apply:
            out_path = OUT_DIR_PARAGRAPHS / f'{doc["docId"]}.json'
            out_path.write_text(json.dumps(paragraphs, ensure_ascii=False, indent=2) + '\n')
            target = by_doc_id[doc['docId']]
            for key in ('paragraphCount', 'wordCount', 'labelCount', 'caseLabels'):
                target[key] = stats[key]
            written += 1
            written_footnote_paragraphs += stats['footnoteParagraphCount']
            written_footnotes += stats['footnoteCount']

        if i % 250 == 0 or i == len(candidates):
            print(f'  [{i:4d}/{len(candidates)}] processed={processed} skipped={skipped} '
                  f'fn_paras={with_footnotes} footnotes={total_footnotes}')

    if args.apply:
        OUT_INFO.write_text(json.dumps(list(by_doc_id.values()), ensure_ascii=False, indent=2) + '\n')

    print('\n=== Footnote refresh summary ===')
    print(f'  Processed DOCX:      {processed}')
    print(f'  Skipped:             {skipped}')
    print(f'  Footnote paragraphs: {with_footnotes}')
    print(f'  Footnotes:           {total_footnotes}')
    if args.apply:
        print(f'  Written DOCX:        {written}')
        print(f'  Written fn paras:    {written_footnote_paragraphs}')
        print(f'  Written footnotes:   {written_footnotes}')
    print(f'  Count changes:       {len(changed_counts)}')
    if args.apply and not args.allow_count_changes:
        print(f'  Skipped count diffs: {skipped_count_changes}')
    for row in changed_counts[:30]:
        print(f'    {row["docId"]}: {row["old"]} -> {row["new"]} ({row["delta"]:+d})')
    if len(changed_counts) > 30:
        print(f'    ... {len(changed_counts) - 30} more')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
