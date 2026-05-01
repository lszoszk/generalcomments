#!/usr/bin/env python3
"""
Build static jurisprudence artefacts for the website.

This is intentionally parallel to build_corpus.py: GC/SP keep their existing
eager-loaded corpus, while jurisprudence is published under docs/jur/ as
metadata + lazy paragraph shards.

Inputs:
  mysite_pythonanywhere/jurisprudence_info.json
  json_jurisprudence/<docId>.json

Outputs:
  docs/jur/documents.json
  docs/jur/facets.json
  docs/jur/manifest.json
  docs/jur/shards/<shardId>.json

Usage:
  python3 build_jurisprudence_shards.py --treaty CRPD
  python3 build_jurisprudence_shards.py --all
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_INFO = ROOT / 'mysite_pythonanywhere' / 'jurisprudence_info.json'
DEFAULT_OUT = ROOT / 'docs' / 'jur'
PLACEHOLDER_TITLES = {
    'english title',
}


def read_json(path: Path):
    with path.open(encoding='utf-8') as f:
        return json.load(f)


def write_json(path: Path, data, *, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        if pretty:
            json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            json.dump(data, f, ensure_ascii=False, separators=(',', ':'))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


def paragraph_number(raw: str):
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s[:-1] if s.endswith('.') else s
    return s


def compact_document(doc: dict) -> dict:
    """Keep Tier-1 fields useful to the browser; drop body-only bookkeeping."""
    keys = [
        'docId', 'type', 'name', 'nameShort', 'signature', 'committee',
        'committees', 'treaty', 'symbol', 'country', 'year', 'title',
        'communicationYear', 'adoptionYear', 'outcome', 'submittedDate',
        'adoptionDate', 'languages', 'link', 'sourceFile', 'sourceFormat',
        'shardId', 'paragraphCount', 'wordCount', 'labelCount',
        'caseLabels', 'articlesCited', 'ocrStatus', 'ocrMeanConf',
        'ocrLowConfRatio', 'ocrPageCount', 'ocrWordCount', 'ocrWarnings',
        'originalName', 'originalTitle', 'nameSource', 'nameConfidence',
        'caseName', 'caseNameSource', 'caseNameConfidence',
        'submittedBy', 'submittedByClean', 'representation',
        'allegedVictims', 'stateParty', 'communicationDate',
        'documentReferences', 'subjectMatter', 'proceduralIssues',
        'substantiveIssues', 'covenantArticles', 'conventionArticles',
        'optionalProtocolArticles', 'covenantArticlesParsed',
        'conventionArticlesParsed', 'optionalProtocolArticlesParsed',
        'rulesReferenced', 'interimMeasuresMentioned',
        'metadataConfidence', 'metadataSources', 'externalNameAuthority',
        'jurisCaseId', 'jurisUrl', 'jurisTitle', 'jurisDecisionType',
        'jurisCommunicationNumbers', 'jurisSessionNo', 'jurisAuthor',
        'jurisCountry', 'jurisSubmissionDate', 'jurisDecisionDate',
        'jurisComment', 'jurisSubstantiveIssues', 'jurisProceduralIssues',
        'jurisSubstantiveArticles', 'jurisProceduralArticles',
        'jurisDownloads', 'jurisLastCheckedAt',
        'firstAddedAt', 'lastVerifiedAt',
    ]
    return {k: doc[k] for k in keys if k in doc and doc[k] not in (None, '', [])}


def is_placeholder_title(value: str | None) -> bool:
    return (value or '').strip().lower() in PLACEHOLDER_TITLES


def fallback_case_title(doc: dict) -> str:
    parts = [doc.get('symbol') or doc.get('signature') or doc.get('docId')]
    if doc.get('country'):
        parts.append(doc['country'])
    return ' · '.join(str(p) for p in parts if p)


def public_title(doc: dict) -> str:
    for key in ('caseName', 'title', 'nameShort', 'name'):
        value = doc.get(key)
        if value and not is_placeholder_title(value):
            return value
    return fallback_case_title(doc)


def lite_document(doc: dict) -> dict:
    """Browser-facing Tier-1 document metadata.

    The full documents.json keeps authority/download metadata for data work.
    The site loads this light version at boot so General Comments do not pay
    an 18 MB jurisprudence tax before the user opens JUR.
    """
    keys = [
        'docId', 'type', 'name', 'nameShort', 'signature', 'committee',
        'committees', 'treaty', 'symbol', 'country', 'year', 'title',
        'communicationYear', 'adoptionYear', 'outcome', 'submittedDate',
        'adoptionDate', 'languages', 'link', 'sourceFile', 'sourceFormat',
        'shardId', 'paragraphCount', 'wordCount', 'labelCount', 'caseLabels',
        'articlesCited', 'ocrStatus', 'ocrMeanConf', 'ocrLowConfRatio',
        'nameConfidence', 'caseName', 'caseNameSource', 'caseNameConfidence',
        'submittedBy', 'submittedByClean', 'representation', 'allegedVictims',
        'stateParty', 'communicationDate', 'documentReferences',
        'subjectMatter', 'proceduralIssues', 'substantiveIssues',
        'covenantArticles', 'conventionArticles', 'optionalProtocolArticles',
        'covenantArticlesParsed', 'conventionArticlesParsed',
        'optionalProtocolArticlesParsed', 'rulesReferenced',
        'interimMeasuresMentioned', 'metadataConfidence', 'jurisCaseId',
        'jurisUrl', 'jurisTitle', 'jurisDecisionType',
        'jurisCommunicationNumbers', 'jurisSessionNo', 'jurisAuthor',
        'jurisCountry', 'jurisSubmissionDate', 'jurisDecisionDate',
        'jurisSubstantiveIssues', 'jurisProceduralIssues',
        'jurisSubstantiveArticles', 'jurisProceduralArticles',
        'firstAddedAt', 'lastVerifiedAt',
    ]
    out = {k: doc[k] for k in keys if k in doc and doc[k] not in (None, '', [])}
    title = public_title(doc)
    out['name'] = title
    out['nameShort'] = title
    out['title'] = title
    out['caseName'] = title
    if any(is_placeholder_title(doc.get(k)) for k in ('name', 'nameShort', 'title', 'caseName')):
        out['placeholderTitleReplaced'] = True
    return out


# ---------------------------------------------------------------------------
# Article extraction — pulls treaty articles cited in the case body. The case
# header (which we drop during ingestion) usually lists them as
# "Articles of the Convention: 1, 5, 15 and 17"; the body then references
# them as "article X of the Convention" / "articles X, Y of the Convention".
# We return them in order of first appearance (matters for "principal" articles
# being first in the dossier card).
# ---------------------------------------------------------------------------
import re as _re_articles

_ART_LIST = _re_articles.compile(
    r'\barticles?\s+([\d\s,()\.&]+?(?:\s+(?:and|or)\s+\d+(?:\s*\(\d+\))?)?)\s+of\s+the\s+(?:Convention|Optional\s+Protocol)',
    _re_articles.IGNORECASE,
)
_ART_NUM = _re_articles.compile(r'\d+(?:\s*\(\s*\d+\s*\))?(?:\s*\(\s*[a-z]\s*\))?', _re_articles.IGNORECASE)


def extract_articles_cited(paragraphs: list[dict]) -> list[str]:
    """Extract distinct treaty articles cited, in order of first appearance.

    Two passes:
      • First the early paragraphs (the case introduction usually summarises
        which articles are at issue) — these become the "principal" entries.
      • Then a second pass over the full body picks up any others mentioned
        in operative paragraphs.

    Returns a list like ``['Art. 5', 'Art. 15', 'Art. 17', 'Art. 12(3)']``.
    Capped at 12 entries to keep the dossier card readable; the underlying
    JSON still has the full mentions in the body text.
    """
    if not paragraphs:
        return []
    intro_text = '\n'.join(p.get('text', '') for p in paragraphs[:5])
    body_text = '\n'.join(p.get('text', '') for p in paragraphs)
    found: list[str] = []
    seen: set[str] = set()
    for txt in (intro_text, body_text):
        for m in _ART_LIST.finditer(txt):
            chunk = m.group(1)
            for n in _ART_NUM.findall(chunk):
                key = _re_articles.sub(r'\s+', '', n)
                if key not in seen:
                    seen.add(key)
                    found.append(f'Art. {key}')
                    if len(found) >= 12:
                        return found
    return found


def build_facets(documents: list[dict], paragraphs: list[dict]) -> dict:
    treaties = Counter()
    outcomes = Counter()
    countries = Counter()
    years = Counter()
    labels = Counter()
    formats = Counter()

    for doc in documents:
        if doc.get('treaty'):
            treaties[doc['treaty']] += 1
        if doc.get('outcome'):
            outcomes[doc['outcome']] += 1
        if doc.get('country'):
            countries[doc['country']] += 1
        if doc.get('year') is not None:
            years[int(doc['year'])] += 1
        if doc.get('sourceFormat'):
            formats[doc['sourceFormat']] += 1

    for para in paragraphs:
        for label in para.get('labels') or []:
            labels[label] += 1

    return {
        'treaties': [{'value': k, 'count': v} for k, v in treaties.most_common()],
        'outcomes': [{'value': k, 'count': v} for k, v in outcomes.most_common()],
        'countries': [{'value': k, 'count': v} for k, v in countries.most_common()],
        'labels': [{'value': k, 'count': v} for k, v in labels.most_common()],
        'formats': [{'value': k, 'count': v} for k, v in formats.most_common()],
        'years': {
            'min': min(years) if years else None,
            'max': max(years) if years else None,
            'histogram': [{'year': y, 'count': years[y]} for y in sorted(years)],
        },
    }


def load_paragraphs(doc: dict) -> list[dict]:
    src = ROOT / doc['sourceFile']
    items = read_json(src)
    if not isinstance(items, list):
        raise ValueError(f'{src} is not a paragraph list')

    rows = []
    for idx, item in enumerate(items, 1):
        text = (item.get('Text') or '').strip()
        if not text:
            continue
        labels = [x for x in (item.get('Labels') or []) if isinstance(x, str)]
        section = (item.get('Section') or '').strip()
        original_id = item.get('ID')
        original_source_id = item.get('OriginalID')
        rows.append({
            'id': f'{doc["docId"]}-{idx:04d}',
            'docId': doc['docId'],
            'idx': idx,
            'n': paragraph_number(original_id),
            'paragraphId': original_id,
            'originalParagraphId': original_source_id,
            'rawParagraphId': item.get('RawID'),
            'idCorrection': item.get('IdCorrection'),
            'generatedParagraphId': item.get('GeneratedID'),
            'generatedIdReason': item.get('GeneratedIDReason'),
            'namespace': item.get('Namespace'),
            'section': section or None,
            'text': re.sub(r'\s+', ' ', text),
            'footnotes': item.get('Footnotes') or item.get('footnotes') or [],
            'labels': labels,
            'sourceFormat': item.get('SourceFormat') or doc.get('sourceFormat'),
            'ocrStatus': item.get('OcrStatus') or doc.get('ocrStatus'),
            'ocrMeanConf': item.get('OcrMeanConf') or doc.get('ocrMeanConf'),
            'ocrLowConfRatio': item.get('OcrLowConfRatio') or doc.get('ocrLowConfRatio'),
            'type': 'jur',
            'treaty': doc.get('treaty'),
            'country': doc.get('country'),
            'year': doc.get('year'),
            'outcome': doc.get('outcome'),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--info', type=Path, default=DEFAULT_INFO)
    ap.add_argument('--out', type=Path, default=DEFAULT_OUT)
    ap.add_argument('--treaty', help='Restrict to one treaty body, e.g. CRPD')
    ap.add_argument('--all', action='store_true', help='Build every treaty present in jurisprudence_info.json')
    ap.add_argument('--pretty', action='store_true', help='Pretty-print shard JSON for inspection')
    args = ap.parse_args()

    if not args.all and not args.treaty:
        ap.error('choose --treaty CRPD for the pilot or --all for the full build')

    docs = read_json(args.info)
    if args.treaty:
        docs = [d for d in docs if (d.get('treaty') or '').upper() == args.treaty.upper()]
    docs = [compact_document(d) for d in docs]
    docs.sort(key=lambda d: (d.get('treaty') or '', d.get('year') or 0, d.get('symbol') or ''))

    shard_paragraphs: dict[str, list[dict]] = defaultdict(list)
    shard_docs: dict[str, list[str]] = defaultdict(list)
    all_paragraphs = []
    diagnostics = []

    for doc in docs:
        try:
            paragraphs = load_paragraphs(doc)
        except Exception as exc:
            diagnostics.append(f'{doc.get("symbol", doc.get("docId"))}: {exc}')
            paragraphs = []
        shard_id = doc.get('shardId') or f'jur_{doc.get("treaty", "unknown")}'
        doc['shardId'] = shard_id
        doc['paragraphCount'] = len(paragraphs)
        doc['wordCount'] = sum(len(p['text'].split()) for p in paragraphs)
        doc['labelCount'] = sum(len(p['labels']) for p in paragraphs)
        doc['articlesCited'] = extract_articles_cited(paragraphs)
        shard_docs[shard_id].append(doc['docId'])
        shard_paragraphs[shard_id].extend(paragraphs)
        all_paragraphs.extend(paragraphs)

    out = args.out
    shard_out = out / 'shards'
    if shard_out.exists():
        for old_shard in shard_out.glob('*.json'):
            old_shard.unlink()
    write_json(out / 'documents.json', docs, pretty=args.pretty)
    docs_lite = [lite_document(d) for d in docs]
    write_json(out / 'documents-lite.json', docs_lite, pretty=args.pretty)
    facets = build_facets(docs, all_paragraphs)
    write_json(out / 'facets.json', facets, pretty=True)

    built_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    shard_files = {}
    for shard_id, paragraphs in sorted(shard_paragraphs.items()):
        shard_doc_ids = sorted(shard_docs[shard_id])
        shard_payload = {
            'shardId': shard_id,
            'builtAt': built_at,
            'documentCount': len(shard_doc_ids),
            'paragraphCount': len(paragraphs),
            'documents': shard_doc_ids,
            'paragraphs': paragraphs,
        }
        shard_path = shard_out / f'{shard_id}.json'
        write_json(shard_path, shard_payload, pretty=args.pretty)
        shard_files[f'shards/{shard_id}.json'] = {
            'sha': sha256_file(shard_path),
            'bytes': shard_path.stat().st_size,
            'documents': len(shard_doc_ids),
            'paragraphs': len(paragraphs),
        }

    manifest = {
        'version': built_at.split('T')[0].replace('-', ''),
        'builtAt': built_at,
        'scope': args.treaty.upper() if args.treaty else 'all',
        'counts': {
            'documents': len(docs),
            'paragraphs': len(all_paragraphs),
            'shards': len(shard_files),
            'treaties': len(facets['treaties']),
            'countries': len(facets['countries']),
            'labels': len(facets['labels']),
            'yearRange': [facets['years']['min'], facets['years']['max']],
        },
        'files': {
            'documents.json': {
                'sha': sha256_file(out / 'documents.json'),
                'bytes': (out / 'documents.json').stat().st_size,
            },
            'documents-lite.json': {
                'sha': sha256_file(out / 'documents-lite.json'),
                'bytes': (out / 'documents-lite.json').stat().st_size,
            },
            'facets.json': {
                'sha': sha256_file(out / 'facets.json'),
                'bytes': (out / 'facets.json').stat().st_size,
            },
            **shard_files,
        },
        'schema': {
            'document': ['docId', 'type', 'treaty', 'symbol', 'country', 'year', 'communicationYear?', 'adoptionYear?', 'title', 'outcome', 'adoptionDate?', 'languages', 'link', 'sourceFile', 'sourceFormat', 'shardId', 'paragraphCount', 'wordCount', 'labelCount', 'caseLabels'],
            'paragraph': ['id', 'docId', 'idx', 'n', 'paragraphId', 'originalParagraphId?', 'rawParagraphId?', 'idCorrection?', 'generatedParagraphId?', 'generatedIdReason?', 'namespace?', 'section', 'text', 'footnotes?', 'labels', 'sourceFormat?', 'ocrStatus?', 'ocrMeanConf?', 'ocrLowConfRatio?', 'type', 'treaty', 'country', 'year', 'outcome'],
        },
        'diagnostics': diagnostics,
    }
    write_json(out / 'manifest.json', manifest, pretty=True)

    print(f'Jurisprudence build: {manifest["scope"]}')
    print(f'  documents:  {len(docs)}')
    print(f'  paragraphs: {len(all_paragraphs)}')
    print(f'  shards:     {len(shard_files)}')
    print(f'  out:        {out}')
    if diagnostics:
        print(f'  diagnostics: {len(diagnostics)}')
        for line in diagnostics[:10]:
            print(f'    - {line}')
    return 0 if not diagnostics else 2


if __name__ == '__main__':
    raise SystemExit(main())
