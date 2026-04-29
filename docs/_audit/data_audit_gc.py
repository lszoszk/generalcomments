#!/usr/bin/env python3
"""
Data quality audit for the General Comments dataset.

Reads:
  generalcomments-repo/docs/documents.json       (all docs; we filter type=gc)
  generalcomments-repo/docs/corpus.json          (all paragraphs; we filter type=gc)

Output:
  Markdown report on stdout. Severity levels:
    CRIT  — broken referential integrity, render-killing data
    WARN  — quality issues that affect search/UX but don't crash
    INFO  — observations, distributional surprises, metadata gaps

The audit catches the bug classes that actually trip up legal research:
  • missing required fields
  • encoding artefacts (mojibake, double-UTF8, HTML leakage)
  • paragraph-numbering gaps + orphan paragraphs
  • broken cross-refs (supersededBy, jointWith)
  • paragraph count mismatches (metadata says N, corpus has M)
  • duplicate text (same paragraph copy-pasted)
  • text shape (too-short = header noise, too-long = missing split)
  • label coverage + spelling drift
  • sentence-end + bracket-balance heuristics
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
# Try a few locations so the script works whether it lives in the repo
# (docs/_audit/) or next to a sibling generalcomments-repo/ checkout.
_candidates = [
    ROOT.parent,                                  # docs/_audit/.. → docs/  → in-repo
    ROOT.parent / 'generalcomments-repo' / 'docs',  # GC_Database layout
    ROOT.parent.parent / 'generalcomments-repo' / 'docs',
]
for _c in _candidates:
    if (_c / 'documents.json').exists():
        DOCS = _c / 'documents.json'
        CORPUS = _c / 'corpus.json'
        break
else:
    raise FileNotFoundError('documents.json not found in any expected location')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
SEV_ICON = {'CRIT': '🔴', 'WARN': '🟡', 'INFO': '🟢'}

def section(title):
    print(f"\n## {title}\n")

def emit(rows, sev='INFO', limit=15):
    """Print a deduped, optionally truncated list of finding rows."""
    if not rows:
        print(f"  {SEV_ICON[sev]} OK · 0 findings")
        return
    print(f"  {SEV_ICON[sev]} {len(rows)} findings")
    for r in rows[:limit]:
        print(f"      · {r}")
    if len(rows) > limit:
        print(f"      … and {len(rows) - limit} more")


def load() -> tuple[list[dict], list[dict]]:
    docs = json.loads(DOCS.read_text())
    paras = json.loads(CORPUS.read_text())
    return [d for d in docs if d.get('type') == 'gc'], \
           [p for p in paras if p.get('type') == 'gc']


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
# Common mojibake fragments — UTF-8 bytes interpreted as Latin-1 then re-encoded.
# Examples: â€™ (right single quote), Ã© (e-acute), Â  (NBSP).
_MOJIBAKE = re.compile(r'[ÂÃ][\x80-\xBF]|â€[\x80-\xBF]|Â\xA0')
# HTML / XML tags + entities.  Excludes <mark> (used in snippets, not source).
_HTML_TAG = re.compile(r'<(?!mark\b|/mark\b)/?[a-z]+[^>]*>', re.IGNORECASE)
_HTML_ENT = re.compile(r'&(?:amp|lt|gt|quot|apos|nbsp|#\d+|#x[0-9a-f]+);', re.IGNORECASE)
# Multiple consecutive whitespace characters (any kind).
_REPEATED_WS = re.compile(r'\s{3,}')
# A paragraph that is JUST a list/section marker, not real prose.
_BARE_MARKER = re.compile(r'^\s*[\(\[]?[a-z0-9ivx]{1,4}[\)\.\]:]\s*$', re.IGNORECASE)
# Footnote markers stuck to the end of words ("torture7" instead of "torture7.")
_TRAILING_FOOTNOTE = re.compile(r'[a-z]\d{1,3}\b')
# Sentences typically end with one of these:
_SENTENCE_END = re.compile(r'[.!?:;”"\)\]]\s*$')
# Common UN doc symbol patterns (sanity-check signature column)
_SIGNATURE_OK = re.compile(
    r'^([A-Z]{1,6}/(C/)?(GC|GR)/[A-Z0-9./-]+|A/\d+/\d+|E/[CN]/[A-Z0-9./-]+|HRI/GEN/[A-Z0-9./-]+|CEDAW/\d+/WP[/.][A-Z0-9./-]+)$',
    re.IGNORECASE,
)
# Plausible adoption-date formats — one of:
#   "21 Nov 1997"   "26 April 2018"   "1997"   "Nov 1997"   "2008-09-10"
_DATE_OK = re.compile(
    r'^(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{4})$'
)


# ---------------------------------------------------------------------------
# Audits
# ---------------------------------------------------------------------------
def audit_required_fields(docs):
    section("1 · Document required-field coverage")
    required = ['docId', 'name', 'signature', 'year', 'committee', 'link', 'paragraphCount']
    missing = []
    for d in docs:
        miss = [f for f in required if not d.get(f)]
        if miss:
            missing.append(f"{d.get('docId', '?')} → missing {miss}")
    emit(missing, sev='CRIT' if missing else 'INFO')


def audit_year_range(docs):
    section("2 · Year plausibility")
    out_of_range = []
    for d in docs:
        y = d.get('year')
        if not isinstance(y, int) or y < 1965 or y > 2026:
            out_of_range.append(f"{d['docId']} year={y!r}")
    emit(out_of_range, sev='WARN')


def audit_signatures(docs):
    section("3 · Signature format")
    odd = []
    seen = Counter()
    for d in docs:
        sig = (d.get('signature') or '').strip()
        seen[sig] += 1
        if not sig:
            continue
        if not _SIGNATURE_OK.match(sig):
            odd.append(f"{d['docId']} sig={sig!r}")
    dupes = [s for s, n in seen.items() if n > 1 and s]
    if dupes:
        odd.append(f"DUP signatures across docs: {dupes[:5]}")
    emit(odd, sev='WARN')


def audit_adoption_date(docs):
    section("4 · adoptionDate format")
    odd = []
    for d in docs:
        v = (d.get('adoptionDate') or '').strip()
        if not v:
            odd.append(f"{d['docId']}: empty adoptionDate")
            continue
        if not _DATE_OK.match(v):
            odd.append(f"{d['docId']}: adoptionDate={v!r}")
    emit(odd, sev='WARN', limit=20)


def audit_doc_id_uniqueness(docs):
    section("5 · docId / signature uniqueness")
    by_id = Counter(d['docId'] for d in docs if d.get('docId'))
    by_sig = Counter(d['signature'] for d in docs if d.get('signature'))
    findings = []
    for k, n in by_id.items():
        if n > 1:
            findings.append(f"docId {k!r} appears {n}×")
    sig_dups = [(k, n) for k, n in by_sig.items() if n > 1]
    for k, n in sig_dups:
        ids = sorted(d['docId'] for d in docs if d.get('signature') == k)
        findings.append(f"signature {k!r} shared by docs={ids}")
    emit(findings, sev='CRIT' if any('docId' in f for f in findings) else 'WARN')


def audit_committee_values(docs):
    section("6 · Committee values")
    known = {
        'CAT', 'CAT-OP', 'CCPR', 'CEDAW', 'CED', 'CERD', 'CESCR', 'CMW', 'CRC', 'CRPD',
    }
    odd = []
    for d in docs:
        c = (d.get('committee') or '').strip()
        if c and c not in known:
            odd.append(f"{d['docId']}: committee={c!r}")
        cs = d.get('committees') or []
        for x in cs:
            if x not in known:
                odd.append(f"{d['docId']}: committees has {x!r}")
    emit(odd, sev='WARN')


def audit_supersession(docs):
    section("7 · Supersession + joint-with referential integrity")
    # 'supersededBy' / 'supersedes' / 'jointWith' values must reference
    # either an existing docId, the canonical signature, or one of the
    # alternativeSignatures (joint docs publish under two committee
    # signatures, only one of which lands in the primary `signature`
    # field — the other is stashed under `alternativeSignatures`).
    by_id = {d['docId'] for d in docs}
    by_sig = {d.get('signature') for d in docs if d.get('signature')}
    for d in docs:
        for s in d.get('alternativeSignatures') or []:
            by_sig.add(s)
    findings = []
    for d in docs:
        for f in ('supersededBy', 'supersedes', 'jointWith'):
            v = d.get(f)
            if not v: continue
            vs = v if isinstance(v, list) else [v]
            for x in vs:
                # `jointWith` sometimes carries an object {docId, role, …};
                # accept whatever has a recognisable docId/signature inside.
                if isinstance(x, dict):
                    x = x.get('docId') or x.get('signature') or ''
                if not isinstance(x, str):
                    findings.append(f"{d['docId']}.{f} contains non-string {type(x).__name__}")
                    continue
                if x and x not in by_id and x not in by_sig:
                    findings.append(f"{d['docId']}.{f}={x!r} → no matching doc")
        if d.get('status') == 'superseded' and not d.get('supersededBy'):
            findings.append(f"{d['docId']}: status=superseded but supersededBy missing")
    emit(findings, sev='CRIT')


def audit_paragraph_count_mismatch(docs, paras):
    section("8 · paragraphCount vs actual paragraph count")
    actual = Counter(p['docId'] for p in paras)
    findings = []
    for d in docs:
        declared = d.get('paragraphCount')
        real = actual[d['docId']]
        if declared is None:
            findings.append(f"{d['docId']}: paragraphCount missing (actual={real})")
        elif declared != real:
            findings.append(f"{d['docId']}: declared={declared} vs actual={real}")
    emit(findings, sev='WARN')


def audit_orphan_paragraphs_and_docs(docs, paras):
    section("9 · Orphan paragraphs + docs without paragraphs")
    by_id = {d['docId'] for d in docs}
    counts = Counter(p['docId'] for p in paras)
    orphan = []
    for p in paras:
        if p['docId'] not in by_id:
            orphan.append(f"para {p['id']}: docId={p['docId']!r} not in documents")
    findings = list(set(orphan))
    no_paras = [d['docId'] for d in docs if counts.get(d['docId'], 0) == 0]
    for x in no_paras:
        findings.append(f"doc {x}: 0 paragraphs in corpus")
    emit(findings, sev='CRIT')


def audit_paragraph_text(paras):
    section("10 · Paragraph text quality")
    findings = defaultdict(list)
    for p in paras:
        t = (p.get('text') or '')
        n = len(t.strip())
        if n == 0:
            findings['empty'].append(p['id'])
            continue
        if n < 20:
            findings['too_short'].append(f"{p['id']} ({n} chars: {t.strip()[:40]!r})")
        if n > 5000:
            findings['too_long'].append(f"{p['id']} ({n} chars)")
        if _MOJIBAKE.search(t):
            findings['mojibake'].append(f"{p['id']}: {t[:100]!r}")
        if _HTML_TAG.search(t):
            findings['html_tag'].append(f"{p['id']}: {t[:100]!r}")
        if _HTML_ENT.search(t):
            findings['html_entity'].append(f"{p['id']}: {t[:100]!r}")
        if _REPEATED_WS.search(t):
            findings['triple_space'].append(p['id'])
        if _BARE_MARKER.match(t.strip()):
            findings['bare_marker'].append(f"{p['id']}: text={t.strip()!r}")
        # Sentence-end heuristic only on paras > 60 chars (skip short titles)
        if n >= 60 and not _SENTENCE_END.search(t.rstrip()):
            findings['no_terminator'].append(f"{p['id']}: …{t.rstrip()[-40:]!r}")
    for k, sev in [
        ('empty', 'CRIT'),
        ('mojibake', 'CRIT'),
        ('html_tag', 'CRIT'),
        ('orphan_doc_id', 'CRIT'),
        ('html_entity', 'WARN'),
        ('triple_space', 'INFO'),
        ('bare_marker', 'WARN'),
        ('no_terminator', 'INFO'),
        ('too_short', 'WARN'),
        ('too_long', 'WARN'),
    ]:
        if k in findings:
            print(f"\n  ### {k} ({len(findings[k])})")
            emit(findings[k], sev=sev, limit=12)


def audit_paragraph_numbering(paras):
    section("11 · Paragraph numbering — gaps + duplicates within a doc")
    by_doc = defaultdict(list)
    for p in paras:
        by_doc[p['docId']].append(p)
    findings = []
    for doc_id, items in by_doc.items():
        items.sort(key=lambda x: x.get('idx') or 0)
        idx_seq = [p.get('idx') for p in items]
        # idx must be unique and monotonic
        if len(set(idx_seq)) != len(idx_seq):
            dupes = [i for i, c in Counter(idx_seq).items() if c > 1]
            findings.append(f"{doc_id}: idx duplicates {dupes[:5]}")
        # idx should be 1..N contiguous
        if idx_seq and idx_seq != list(range(1, len(idx_seq) + 1)):
            gaps = [(idx_seq[i-1], idx_seq[i]) for i in range(1, len(idx_seq)) if idx_seq[i] - idx_seq[i-1] != 1][:3]
            findings.append(f"{doc_id}: idx not 1..{len(idx_seq)} (gaps {gaps})")
    emit(findings, sev='WARN')


def audit_duplicate_text(paras):
    section("12 · Duplicate paragraph bodies (same text in same doc)")
    by_doc_text = defaultdict(list)
    for p in paras:
        t = (p.get('text') or '').strip()
        if not t or len(t) < 30:
            continue
        by_doc_text[(p['docId'], t)].append(p['id'])
    findings = []
    for (doc, t), ids in by_doc_text.items():
        if len(ids) > 1:
            findings.append(f"{doc}: {len(ids)} copies — ids={ids[:3]} text={t[:60]!r}…")
    emit(findings, sev='WARN', limit=20)


def audit_label_coverage(docs, paras):
    section("13 · Label coverage + spelling drift")
    label_count = Counter()
    para_with_label = 0
    for p in paras:
        labels = p.get('labels') or []
        if labels:
            para_with_label += 1
        for l in labels:
            label_count[l] += 1
    pct = 100 * para_with_label / max(len(paras), 1)
    print(f"  paragraphs with ≥1 label: {para_with_label}/{len(paras)} ({pct:.1f}%)")
    print(f"  unique labels: {len(label_count)}")
    print()
    print(f"  ### Top 20 labels")
    for l, c in label_count.most_common(20):
        print(f"      · {l:36s} {c:>5}")
    # Singletons or rare labels — possible misspellings
    rare = [l for l, c in label_count.items() if c <= 2]
    if rare:
        print(f"\n  ### Singletons / very rare ({len(rare)})")
        for l in rare[:20]:
            print(f"      · {l!r} ({label_count[l]})")
    # Cross-check: doc-declared labelCount vs sum of per-paragraph labels
    section("14 · doc.labelCount vs sum of per-paragraph labels")
    discrepancies = []
    by_doc_count = Counter()
    for p in paras:
        by_doc_count[p['docId']] += len(p.get('labels') or [])
    for d in docs:
        declared = d.get('labelCount')
        actual = by_doc_count[d['docId']]
        if declared is None:
            discrepancies.append(f"{d['docId']}: labelCount missing (actual={actual})")
        elif declared != actual:
            discrepancies.append(f"{d['docId']}: declared={declared} vs actual={actual}")
    emit(discrepancies, sev='WARN')


def audit_word_count(docs, paras):
    section("15 · doc.wordCount vs sum of para word counts")
    by_doc = defaultdict(int)
    for p in paras:
        by_doc[p['docId']] += len((p.get('text') or '').split())
    findings = []
    for d in docs:
        declared = d.get('wordCount')
        actual = by_doc[d['docId']]
        if declared is None:
            findings.append(f"{d['docId']}: wordCount missing (actual={actual})")
            continue
        # Allow ±1 % drift (counting whitespace/em-dashes differently is fine)
        if abs(declared - actual) / max(declared, 1) > 0.01 and abs(declared - actual) > 5:
            findings.append(f"{d['docId']}: declared={declared} vs actual={actual} (drift {abs(declared-actual)})")
    emit(findings, sev='WARN', limit=20)


def audit_links(docs):
    section("16 · Document links — shape only (no fetch)")
    findings = []
    for d in docs:
        link = (d.get('link') or '').strip()
        if not link:
            findings.append(f"{d['docId']}: link missing")
            continue
        if not link.startswith(('http://', 'https://')):
            findings.append(f"{d['docId']}: link not http(s) — {link!r}")
        if 'undocs.org' in link:
            # fine, but flagged as it's a redirect host
            pass
    emit(findings, sev='WARN')


def audit_languages(docs):
    section("17 · languagesAvailable distribution")
    pat = Counter()
    for d in docs:
        langs = tuple(sorted(d.get('languagesAvailable') or []))
        pat[langs] += 1
    print(f"  unique language sets: {len(pat)}")
    for langs, c in pat.most_common(8):
        print(f"      · {langs!r:50s} {c:>4}")


def audit_status_distribution(docs):
    section("18 · Status field distribution")
    pat = Counter()
    for d in docs:
        pat[d.get('status') or '(none)'] += 1
    for k, v in pat.most_common():
        print(f"      · {k:20s} {v}")


def audit_text_length_distribution(paras):
    section("19 · Paragraph length distribution (chars)")
    lens = [len(p.get('text') or '') for p in paras]
    if not lens: return
    print(f"  count    : {len(lens)}")
    print(f"  min      : {min(lens)}")
    print(f"  median   : {statistics.median(lens):.0f}")
    print(f"  mean     : {statistics.mean(lens):.0f}")
    print(f"  p95      : {sorted(lens)[int(len(lens) * 0.95)]}")
    print(f"  p99      : {sorted(lens)[int(len(lens) * 0.99)]}")
    print(f"  max      : {max(lens)}")


def audit_committee_distribution(docs, paras):
    section("20 · Committee distribution")
    docs_by = Counter(d.get('committee') for d in docs)
    paras_by = Counter(p.get('committee') for p in paras)
    print(f"  {'committee':14s} {'#docs':>6} {'#paras':>8} {'avg ¶/doc':>10}")
    for k in sorted(set(docs_by) | set(paras_by)):
        nd = docs_by.get(k, 0)
        np = paras_by.get(k, 0)
        avg = np / max(nd, 1)
        print(f"  {str(k):14s} {nd:>6} {np:>8} {avg:>10.1f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("# General Comments — data quality audit")
    print(f"_(generated by data_audit_gc.py)_\n")
    docs, paras = load()
    print(f"**Scope:** {len(docs)} documents · {len(paras)} paragraphs (type=gc)\n")
    audit_required_fields(docs)
    audit_year_range(docs)
    audit_signatures(docs)
    audit_adoption_date(docs)
    audit_doc_id_uniqueness(docs)
    audit_committee_values(docs)
    audit_supersession(docs)
    audit_paragraph_count_mismatch(docs, paras)
    audit_orphan_paragraphs_and_docs(docs, paras)
    audit_paragraph_text(paras)
    audit_paragraph_numbering(paras)
    audit_duplicate_text(paras)
    audit_label_coverage(docs, paras)
    audit_word_count(docs, paras)
    audit_links(docs)
    audit_languages(docs)
    audit_status_distribution(docs)
    audit_text_length_distribution(paras)
    audit_committee_distribution(docs, paras)
    print("\n---\n_End of audit._\n")


if __name__ == '__main__':
    main()
