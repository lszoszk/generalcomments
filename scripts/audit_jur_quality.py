#!/usr/bin/env python3
"""Corpus-wide label-continuity and garbage scan of UNHRDB jurisprudence.

Read-only. Reads the published build artefacts (docs/jur/documents.json and
docs/jur/shards/*.json), which are what build_db.py loads into the API, and
writes a JSON report. Optionally checks a random sample of documents against
the live API to confirm the artefacts match what is served.

The continuity rule is the one in vclt-interpreter/stage_b/check_continuity.py,
extended so that a restart at "1" after an operative paragraph is reported as
a separate part (two-part decisions, unnamespaced opinions) instead of a
cascade of repeats.

Usage:
    python3 audit_jur_quality.py --repo ../generalcomments-repo --out report.json
    python3 audit_jur_quality.py --repo ... --out ... --verify-api 40
"""
from __future__ import annotations

import argparse
import json
import random
import re
import ssl
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

API = 'https://150.254.115.204/unhrdb-api/api'

MAIN_LABEL = re.compile(r'\d+(?:\.\d+)?')
MONTHS = r'(?:january|february|march|april|may|june|july|august|september|october|november|december)'

# B: garbage
TSV_ROW = re.compile(r'(?:\b-?\d+(?:\.\d+)?[\t ]+){9,}-?\d+\.\d{3,6}\b')
PAGE_NO = re.compile(r'(?:^|\s)-\s?\d{1,4}\s?-(?=\s|$)')
OCR_TOKEN = re.compile(
    r'[A-Za-z][~¥£|][A-Za-z:]'            # obliga~:ion, arti~~e
    r'|\b[A-Z]{2}[a-z]{3,}\b'              # SUbjected
    r'|\b[a-z]+[01][a-z]+\b'               # rtic1e
    r'|\b\d+~\d+\b'                        # 8~5
)
HEADING_TAIL = re.compile(
    r'[.!?”"\])]\s+((?:the\s+)?(?:facts\s+as\s+(?:submitted|presented)\s+by\s+the\s+authors?|'
    r'examination\s+of\s+the\s+merits|consideration\s+of\s+(?:admissibility|the\s+merits)|'
    r'issues\s+and\s+proceedings\s+before\s+the\s+committee|the\s+complaint|'
    r'(?:the\s+)?state\s+party[’\']?s\s+(?:observations|submissions?)[^.]{0,80}|'
    r'(?:the\s+)?author[’\']?s\s+(?:comments|observations)[^.]{0,80}|'
    r'committee[’\']?s\s+decision\s+on\s+admissibility))\s*:?\s*$',
    re.IGNORECASE,
)
ENDNOTE_TAIL = re.compile(r'(?:\]|\.)\s+(?:Notes?\s+\d|Notes\b|APPENDIX\b|Appendix\b|\*\s*/|-\*-)')
TERMINAL = tuple('.;:!?)]"”’\'*')


def check(labels: list[str]) -> list[str]:
    """check_continuity.check, unchanged apart from taking clean labels."""
    issues, seen, major, minor = [], set(), 0, 0
    for lab in labels:
        m = re.fullmatch(r'(\d+)(?:\.(\d+))?', lab)
        if not m:
            issues.append(f'odd label {lab!r}')
            continue
        if lab in seen:
            issues.append(f'repeat {lab}')
            continue
        seen.add(lab)
        a, b = int(m.group(1)), m.group(2)
        if b is None:
            if a != major + 1:
                issues.append(f'out of sequence {lab} after {major}.{minor}' if minor else f'out of sequence {lab} after {major}')
                continue
            major, minor = a, 0
        else:
            b = int(b)
            if a == major and b == minor + 1:
                minor = b
            elif a == major + 1 and b == 1:
                major, minor = a, 1
            elif a > major:
                issues.append(f'gap before {lab} (last {major}.{minor})')
                major, minor = a, b
            elif a == major and b > minor + 1:
                issues.append(f'gap {major}.{minor + 1}-{a}.{b - 1}')
                minor = b
            else:
                issues.append(f'out of sequence {lab} after {major}.{minor}')
    if labels and '.' in labels[-1]:
        issues.append(f'no operative paragraph at the end (last label {labels[-1]})')
    return issues


def split_parts(labels: list[str]) -> list[list[str]]:
    """Split a main-body label run where numbering restarts at 1 / 1.1."""
    parts, cur = [], []
    for lab in labels:
        if cur and lab in ('1', '1.1') and len(cur) >= 3:
            parts.append(cur)
            cur = []
        cur.append(lab)
    if cur:
        parts.append(cur)
    return parts


def missing_labels(labels: list[str]) -> list[str]:
    """Labels a gap implies, e.g. 6.3 -> 6.5 gives 6.4."""
    out, prev = [], None
    for lab in labels:
        m = re.fullmatch(r'(\d+)(?:\.(\d+))?', lab)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2)) if m.group(2) else None
        if prev:
            pa, pb = prev
            if b is not None and pb is not None and a == pa and b > pb + 1:
                out += [f'{a}.{k}' for k in range(pb + 1, b)]
            elif b is not None and a == pa + 1 and b > 1:
                out += [f'{a}.{k}' for k in range(1, b)]
            elif b is None and pb is None and a > pa + 1:
                out += [str(k) for k in range(pa + 1, a)]
        prev = (a, b)
    return out


def scan_doc(doc: dict, paras: list[dict]) -> dict:
    flags: dict[str, list] = defaultdict(list)
    ns = [(p.get('n') or '') for p in paras]
    main = [(i, n) for i, n in enumerate(ns) if MAIN_LABEL.fullmatch(n) and not paras[i].get('namespace')]
    main_labels = [n for _, n in main]

    # ---- C: labels / structure
    unlabelled = sum(1 for n in ns if not n)
    if unlabelled:
        flags['C_unlabelled_records'].append(unlabelled)
    if main:
        i0, first = main[0]
        t0 = paras[i0]['text'].strip().lower()
        if first not in ('1', '1.1') and (re.match(MONTHS, t0) or re.match(r'^[–-]\s*\d', t0) or int(first.split('.')[0]) > 3):
            flags['C_header_record_as_paragraph'].append(first)
    parts = split_parts(main_labels)
    if len(parts) > 1:
        flags['C_numbering_restarts'].append(len(parts))
    issues = []
    for part in parts:
        issues += check(part)
    gaps = [x for x in issues if x.startswith('gap')]
    seq = [x for x in issues if x.startswith(('out of sequence', 'repeat', 'odd'))]
    if seq:
        flags['C_out_of_sequence_or_repeat'] += seq
    op_labels = [n for n in ns if n.startswith('OP')]
    op_numeric = [n for n in op_labels if re.fullmatch(r'OP\d+-\d+(?:\.\d+)?', n)]
    for k, c in Counter(op_labels).items():
        if c > 1:
            flags['C_opinion_label_repeated'].append(k)
    for prefix, grp in _group(op_numeric).items():
        nums = [int(x.split('-')[1].split('.')[0]) for x in grp]
        if nums and (nums[0] > 3 or any(b < a for a, b in zip(nums, nums[1:]))):
            flags['C_opinion_numbering_odd'].append(prefix)
    # Opinion text without an OP namespace
    for i, p in enumerate(paras):
        if p.get('namespace'):
            continue
        t = p['text']
        if re.search(r'\b(?:individual|separate|dissenting|concurring)\s+opinion\s+(?:of|by)\s+(?:Mr|Ms|Mrs|Sir|Committee member)', t[:200], re.IGNORECASE):
            flags['C_opinion_not_namespaced'].append(ns[i] or f'idx{i}')

    # ---- A: missing / truncated / merged
    if gaps:
        flags['A_label_gap'] += gaps
    miss = []
    for part in parts:
        miss += missing_labels(part)
    texts = [p['text'] for p in paras]
    for lab in miss:
        if '.' not in lab:
            continue
        pat = re.compile(r'[.;:”"\]]\s+' + re.escape(lab).replace(r'\.', r'\s?[.~,]\s?') + r'\.?\s+[A-Z“"(]')
        for i, t in enumerate(texts):
            if pat.search(t[1:]):
                flags['A_missing_label_found_inside_other_paragraph'].append(f'{lab} in {ns[i] or i}')
                break
    for i, p in enumerate(paras):
        t = p['text'].rstrip()
        if not t or p.get('namespace') or not ns[i]:
            continue
        nxt = paras[i + 1]['text'].lstrip() if i + 1 < len(paras) else ''
        core = PAGE_NO.sub('', t).rstrip()
        if re.search(r'[.;:!?”"’)\]]\s?\d{1,3}$|\.,$', core):
            flags['B_stray_footnote_number_at_end'].append(ns[i])
        elif not core.endswith(TERMINAL) and len(core) > 60:
            flags['A_ends_mid_sentence'].append(ns[i])
        if re.search(r'\b(?:article|articles|paragraph|paragraphs|rule|section|No\.|art\.)$', t, re.IGNORECASE):
            flags['A_ends_on_reference_word'].append(ns[i])
    for i, n in enumerate(ns):
        if MAIN_LABEL.fullmatch(n) and '.' not in n and i > 0 and int(n) >= 15:
            prev = paras[i - 1]['text'].rstrip()
            if re.search(r'\b(?:article|articles|paragraph|paragraphs|rule)$', prev, re.IGNORECASE):
                flags['A_reference_number_split_into_record'].append(f'{ns[i-1]}|{n}')

    # ---- B: garbage
    for i, t in enumerate(texts):
        lab = ns[i] or f'idx{i}'
        if TSV_ROW.search(t):
            flags['B_tesseract_tsv_leak'].append(lab)
        if PAGE_NO.search(t):
            flags['B_page_number_in_text'].append(lab)
        if HEADING_TAIL.search(t[-160:]):
            flags['B_heading_appended'].append(lab)
        if ENDNOTE_TAIL.search(t) and i >= len(texts) - 3:
            flags['B_endnotes_or_appendix_appended'].append(lab)
    tokens = sum(len(t.split()) for t in texts) or 1
    noise = sum(len(OCR_TOKEN.findall(t)) for t in texts)
    rate = noise / tokens * 1000
    if rate >= 1.0:
        flags['B_ocr_noise_per_1000_tokens'].append(round(rate, 2))

    return {k: v for k, v in flags.items() if v}


def _group(labels):
    g = defaultdict(list)
    for x in labels:
        g[x.split('-')[0]].append(x)
    return g


def comm_key(doc):
    """Communication number from the symbol: .../D/903/1999 -> 903."""
    m = re.search(r'/D/(\d+)[/-]', doc.get('symbol') or '')
    return (doc.get('treaty'), m.group(1)) if m else None


def verify_api(sample, by_doc):
    ctx = ssl._create_unverified_context()
    mism = []
    for doc_id in sample:
        with urllib.request.urlopen(f'{API}/document/{doc_id}', timeout=60, context=ctx) as r:
            api = json.loads(r.read())
        a = [(p['n'], p['text']) for p in api['paragraphs']]
        b = [(p.get('n'), p['text']) for p in by_doc[doc_id]]
        if a != b:
            mism.append(doc_id)
    return mism


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--verify-api', type=int, default=0)
    args = ap.parse_args()

    docs = {d['docId']: d for d in json.loads((args.repo / 'docs/jur/documents.json').read_text())}
    by_doc = defaultdict(list)
    for f in sorted((args.repo / 'docs/jur/shards').glob('*.json')):
        for p in json.loads(f.read_text())['paragraphs']:
            by_doc[p['docId']].append(p)
    for v in by_doc.values():
        v.sort(key=lambda p: p['idx'])

    report, per_class_docs, per_class_hits = {}, Counter(), Counter()
    by_format = defaultdict(Counter)
    for doc_id, d in docs.items():
        paras = by_doc.get(doc_id, [])
        flags = scan_doc(d, paras)
        if flags:
            report[doc_id] = {'symbol': d.get('symbol'), 'sourceFormat': d.get('sourceFormat'), 'flags': flags}
        for k, v in flags.items():
            per_class_docs[k] += 1
            per_class_hits[k] += len(v)
            by_format[k][d.get('sourceFormat')] += 1

    # C5: several records for one communication
    groups = defaultdict(list)
    for d in docs.values():
        k = comm_key(d)
        if k:
            groups[k].append(d['docId'])
    multi = {f'{k[0]} {k[1]}': v for k, v in groups.items() if len(v) > 1}

    summary = {
        'documents': len(docs),
        'paragraphs': sum(len(v) for v in by_doc.values()),
        'documents_with_any_flag': len(report),
        'by_flag': {k: {'documents': per_class_docs[k], 'hits': per_class_hits[k], 'by_format': dict(by_format[k])}
                    for k in sorted(per_class_docs)},
        'C_several_records_same_communication': {'groups': len(multi), 'records': sum(len(v) for v in multi.values())},
        'format_totals': dict(Counter(d.get('sourceFormat') for d in docs.values())),
    }
    if args.verify_api:
        random.seed(20261006)
        sample = random.sample(sorted(docs), args.verify_api)
        summary['api_verification'] = {'sampled': len(sample), 'mismatched': verify_api(sample, by_doc)}
    args.out.write_text(json.dumps({'summary': summary, 'same_communication': multi, 'documents': report},
                                   ensure_ascii=False, indent=1))
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()
