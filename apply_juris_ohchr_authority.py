#!/usr/bin/env python3
"""Apply safe OHCHR JURIS authority metadata to jurisprudence_info.json.

This script is intentionally conservative:

* it matches only unique JURIS symbols to unique local symbols;
* it always stores JURIS data in separate ``juris*`` fields;
* it fills local fields only when they are currently empty;
* it does not overwrite names, dates, countries or outcomes when local data
  already exists.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_INFO = ROOT / 'mysite_pythonanywhere' / 'jurisprudence_info.json'
DEFAULT_AUTHORITY = Path('/Users/lszoszk/Desktop/AI/HURIDOCS/App/output/juris_ohchr_authority/juris_ohchr_authority.jsonl')
DEFAULT_REPORT = Path('/Users/lszoszk/Desktop/AI/HURIDOCS/App/output/juris_ohchr_authority/juris_ohchr_apply_report.json')


def read_json(path: Path):
    with path.open(encoding='utf-8') as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    with path.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding='utf-8') as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def clean_text(value) -> str:
    if value is None:
        return ''
    return re.sub(r'\s+', ' ', str(value).replace('\xa0', ' ')).strip()


def nonempty(value) -> bool:
    return value not in (None, '', [], {})


def norm_symbol(symbol: str | None) -> str:
    return clean_text(symbol).upper().replace(' ', '')


def clean_list(values) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        values = re.split(r';|\n', values)
    out = []
    for value in values:
        text = clean_text(value)
        if text and text.lower() not in {'no issues found', 'no articles found'}:
            out.append(text)
    return out


def outcome_from_juris(decision_type: str | None) -> str:
    text = clean_text(decision_type).lower()
    if 'inadmiss' in text:
        return 'inadmissible'
    if 'discontinuance' in text or 'discontinued' in text:
        return 'discontinued'
    if 'friendly settlement' in text:
        return 'friendly_settlement'
    if 'admissibility' in text and 'inadmiss' not in text:
        return 'admissibility'
    return ''


def article_field_for_treaty(treaty: str | None) -> str:
    return 'covenantArticles' if clean_text(treaty).upper() == 'CCPR' else 'conventionArticles'


def truthy(value) -> bool:
    return clean_text(value).lower() in {'1', 'true', 'yes', 'y', 'approved', 'apply'}


def apply_reviewed_fixes(docs: list[dict], reviewed_csv: Path) -> dict:
    by_symbol = {norm_symbol(doc.get('symbol')): doc for doc in docs if norm_symbol(doc.get('symbol'))}
    applied = []
    skipped = []
    with reviewed_csv.open(encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not truthy(row.get('approved') or row.get('apply')):
                skipped.append({'reason': 'not_approved', **row})
                continue
            symbol = norm_symbol(row.get('symbol'))
            field = clean_text(row.get('field'))
            new_value = clean_text(row.get('newValue') or row.get('new') or row.get('value'))
            if not symbol or not field or not new_value:
                skipped.append({'reason': 'missing_symbol_field_or_value', **row})
                continue
            doc = by_symbol.get(symbol)
            if not doc:
                skipped.append({'reason': 'symbol_not_found', **row})
                continue
            old_value = doc.get(field)
            doc[field] = new_value
            sources = doc.setdefault('metadataSources', {})
            if not isinstance(sources, dict):
                sources = {}
                doc['metadataSources'] = sources
            sources[field] = 'reviewed_juris_reconciliation'
            applied.append({
                'symbol': doc.get('symbol'),
                'docId': doc.get('docId'),
                'field': field,
                'old': old_value,
                'new': new_value,
            })
    return {
        'reviewedCsv': str(reviewed_csv),
        'appliedReviewedFixes': len(applied),
        'skippedReviewedRows': len(skipped),
        'applied': applied[:50],
        'skippedSample': skipped[:50],
    }


def juris_payload(row: dict) -> dict:
    payload = {
        'jurisCaseId': row.get('jurisCaseId'),
        'jurisUrl': row.get('jurisUrl'),
        'jurisTitle': row.get('title'),
        'jurisDecisionType': row.get('typeOfDecision'),
        'jurisCommunicationNumbers': row.get('communicationNumbers'),
        'jurisSessionNo': row.get('sessionNo'),
        'jurisAuthor': row.get('author'),
        'jurisCountry': row.get('country'),
        'jurisSubmissionDate': row.get('submissionDate'),
        'jurisDecisionDate': row.get('decisionDate'),
        'jurisComment': row.get('comment'),
        'jurisSubstantiveIssues': clean_list(row.get('substantiveIssues')),
        'jurisProceduralIssues': clean_list(row.get('proceduralIssues')),
        'jurisSubstantiveArticles': clean_list(row.get('substantiveArticles')),
        'jurisProceduralArticles': clean_list(row.get('proceduralArticles')),
        'jurisDownloads': row.get('downloads') or {},
        'jurisLastCheckedAt': datetime.now(timezone.utc).date().isoformat(),
    }
    return {k: v for k, v in payload.items() if nonempty(v)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--info', type=Path, default=DEFAULT_INFO)
    parser.add_argument('--authority', type=Path, default=DEFAULT_AUTHORITY)
    parser.add_argument('--report', type=Path, default=DEFAULT_REPORT)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--fix-reviewed', action='store_true', help='Apply only approved rows from --reviewed-csv')
    parser.add_argument('--reviewed-csv', type=Path, help='CSV with columns: approved, symbol, field, newValue')
    args = parser.parse_args()

    docs = read_json(args.info)
    if args.fix_reviewed:
        if not args.reviewed_csv:
            parser.error('--fix-reviewed requires --reviewed-csv')
        report = apply_reviewed_fixes(docs, args.reviewed_csv)
        report['dryRun'] = args.dry_run
        args.report.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.report, report)
        if not args.dry_run:
            write_json(args.info, docs)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    authority = read_jsonl(args.authority)

    local_by_symbol: dict[str, list[dict]] = defaultdict(list)
    for doc in docs:
        symbol = norm_symbol(doc.get('symbol'))
        if symbol:
            local_by_symbol[symbol].append(doc)

    authority_by_symbol: dict[str, list[dict]] = defaultdict(list)
    for row in authority:
        symbol = norm_symbol(row.get('symbol'))
        if symbol:
            authority_by_symbol[symbol].append(row)

    stats = {
        'documents': len(docs),
        'authorityRows': len(authority),
        'uniqueAuthorityMatches': 0,
        'jurisFieldsAdded': 0,
        'fillIfMissingApplied': 0,
        'skippedAuthorityDuplicateSymbols': 0,
        'skippedLocalDuplicateSymbols': 0,
        'dryRun': args.dry_run,
    }
    fills_by_field = defaultdict(int)
    examples = []

    for symbol, auth_rows in authority_by_symbol.items():
        local_rows = local_by_symbol.get(symbol) or []
        if len(auth_rows) != 1:
            if local_rows:
                stats['skippedAuthorityDuplicateSymbols'] += 1
            continue
        if len(local_rows) != 1:
            if len(local_rows) > 1:
                stats['skippedLocalDuplicateSymbols'] += 1
            continue

        doc = local_rows[0]
        juris = auth_rows[0]
        stats['uniqueAuthorityMatches'] += 1

        for key, value in juris_payload(juris).items():
            if doc.get(key) != value:
                doc[key] = value
                stats['jurisFieldsAdded'] += 1

        sources = doc.setdefault('metadataSources', {})
        if not isinstance(sources, dict):
            sources = {}
            doc['metadataSources'] = sources
        sources['jurisAuthority'] = 'OHCHR JURIS casedetails'

        field_fills = {
            'submittedByClean': juris.get('author'),
            'communicationDate': juris.get('submissionDate'),
            'adoptionDate': juris.get('decisionDate'),
            'country': juris.get('country'),
            'stateParty': juris.get('country'),
            'substantiveIssues': clean_list(juris.get('substantiveIssues')),
            'proceduralIssues': clean_list(juris.get('proceduralIssues')),
            'optionalProtocolArticles': ', '.join(clean_list(juris.get('proceduralArticles'))),
            article_field_for_treaty(doc.get('treaty')): ', '.join(clean_list(juris.get('substantiveArticles'))),
        }
        maybe_outcome = outcome_from_juris(juris.get('typeOfDecision'))
        if maybe_outcome:
            field_fills['outcome'] = maybe_outcome

        applied = {}
        for field, value in field_fills.items():
            if nonempty(value) and not nonempty(doc.get(field)):
                doc[field] = value
                stats['fillIfMissingApplied'] += 1
                fills_by_field[field] += 1
                applied[field] = value
                sources[field] = 'ohchr_juris_fill_empty'

        if applied and len(examples) < 20:
            examples.append({
                'symbol': doc.get('symbol'),
                'docId': doc.get('docId'),
                'caseName': doc.get('caseName') or doc.get('name'),
                'fills': applied,
            })

    report = {
        **stats,
        'fillsByField': dict(sorted(fills_by_field.items())),
        'examples': examples,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.report, report)

    if not args.dry_run:
        write_json(args.info, docs)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
