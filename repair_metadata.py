#!/usr/bin/env python3
"""
Phase 1 + Phase 2 metadata repair and enrichment.

Phase 1 — fixes existing data quality issues (deterministic, idempotent):
  • Cast all `Adoption Year` values to int.
  • Merge SP `Adoption year` (lowercase) into `Adoption Year` and drop the
    duplicate key.
  • Fix CCPR/C/GC/31 signature typo where the adoption date got concatenated
    into the Signature field.
  • Remove orphan record `CEDAW/C/GC/31/CRC/C/GC/18` (non-revised duplicate
    pointing to a file that doesn't exist; the revised version with a -REV
    suffix is the canonical record).
  • Standardise all `Link` values to the canonical
    https://tbinternet.ohchr.org/.../Download.aspx?symbolno=… form.

Phase 2 — adds new fields that are mechanically derivable:
  • paragraphCount, wordCount, labelCount  (from labelled JSON files)
  • ohchrSymbol                            (extracted from Link query string)
  • firstAddedAt                           (from file mtime)
  • lastVerifiedAt                         (today, ISO date)
  • articles                               (regex from Name; covers obvious
                                            "article N" / "art. N" patterns)
  • status, supersedes, supersededBy       (small curated table)
  • jointWith                              (small curated table — already
                                            single records, just expose the
                                            structured cross-reference)
  • languagesAvailable                     (defaults to UN6, no scrape)

This script is idempotent — running it twice produces the same output.
The user-decided answers from 28 April 2026:
  - topicTags is deferred (logged in TODO_LATER.md, not generated here).
  - Joint GCs stay as single merged records.
  - Abstracts are added in a separate, AI-assisted pass.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from datetime import date
from pathlib import Path

ROOT = Path('/Users/lszoszk/Desktop/GC_Database')
GC_META = ROOT / 'mysite_pythonanywhere' / 'crc_gc_info.json'
SP_META = ROOT / 'mysite_pythonanywhere' / 'specialprocedures_info.json'
GC_LABELED = ROOT / 'json_data_gc_labeled'
SP_LABELED = ROOT / 'json_labeled_v2'
GC_SRC = ROOT / 'mysite_pythonanywhere' / 'json_data'
SP_SRC = ROOT / 'mysite_pythonanywhere' / 'json_data_sp'

TODAY_ISO = date.today().isoformat()
UN_LANGS = ['en', 'fr', 'es', 'ar', 'ru', 'zh']


# ---------------------------------------------------------------------------
# Curated supplementary tables
# ---------------------------------------------------------------------------

# Status / supersession map. Keys are signatures.
# Source: cross-referenced from OHCHR per-committee "general comments" pages
# and from the new GC text itself (e.g. CRC GC24 §1 explicitly replaces GC10).
STATUS_OVERRIDES: dict[str, dict] = {
    # CRC: GC10 on juvenile justice replaced by GC24 in 2019
    'CRC/C/GC/10': {
        'status': 'superseded',
        'supersededBy': 'CRC/C/GC/24',
    },
    'CRC/C/GC/24': {
        'status': 'final',
        'supersedes': 'CRC/C/GC/10',
    },
    # CRC: GC7 (early childhood) was revised in 2006 — same signature with /Rev.1
    'CRC/C/GC/7/Rev.1': {
        'status': 'revised',
    },
    # CEDAW: GR19 (violence against women) was *updated* by GR35, not replaced
    'A/47/38': {  # GR19 — note: this signature is shared with GR20 in same session
        # Cannot uniquely set on shared-signature record; skipping.
    },
    # CEDAW joint: GR31/CRC18 — original (2014) replaced by Rev.1 (2019)
    'CEDAW/C/GC/31/Rev.1–CRC/C/GC/18/Rev.1': {
        'status': 'revised',
    },
    # CAT: GC1 (1997) replaced by GC4 (2017) on same article 3 / 22 ground
    'A/53/44': {
        'status': 'superseded',
        'supersededBy': 'CAT/C/GC/4',
    },
    'CAT/C/GC/4': {
        'status': 'final',
        'supersedes': 'A/53/44',
    },
    # CEDAW: GR25 explicitly elaborates on temporary special measures discussed in GR5
    # Not formally a supersession — leave as final.
}

# Joint General Comment cross-reference table.
# Each entry maps a record (by signature) to the structured `jointWith`
# field — listing the other committee + signature.
JOINT_TABLE: dict[str, list[dict]] = {
    'CRC/C/GC/22, CMW/C/GC/3': [
        {'committee': 'CMW', 'signature': 'CMW/C/GC/3'},
        {'committee': 'CRC', 'signature': 'CRC/C/GC/22'},
    ],
    'CRC/C/GC/23, CMW/C/GC/4': [
        {'committee': 'CMW', 'signature': 'CMW/C/GC/4'},
        {'committee': 'CRC', 'signature': 'CRC/C/GC/23'},
    ],
    'CEDAW/C/GC/31/Rev.1–CRC/C/GC/18/Rev.1': [
        {'committee': 'CEDAW', 'signature': 'CEDAW/C/GC/31/Rev.1'},
        {'committee': 'CRC',   'signature': 'CRC/C/GC/18/Rev.1'},
    ],
    'CMW/C/GC/7–CERD/C/GC/38': [
        {'committee': 'CMW',  'signature': 'CMW/C/GC/7'},
        {'committee': 'CERD', 'signature': 'CERD/C/GC/38'},
    ],
    'CMW/C/GC/8–CERD/C/GC/39': [
        {'committee': 'CMW',  'signature': 'CMW/C/GC/8'},
        {'committee': 'CERD', 'signature': 'CERD/C/GC/39'},
    ],
}


# ---------------------------------------------------------------------------
# Phase 1 fixes
# ---------------------------------------------------------------------------

def cast_year_to_int(record: dict, key: str = 'Adoption Year') -> bool:
    """Cast `record[key]` to int if it's a string. Returns True if changed."""
    v = record.get(key)
    if isinstance(v, str):
        try:
            record[key] = int(v.strip())
            return True
        except (ValueError, TypeError):
            pass
    return False


def merge_lowercase_year(record: dict) -> bool:
    """Merge `Adoption year` (lowercase) into `Adoption Year`. Returns True if changed."""
    lower = record.pop('Adoption year', None)
    if lower is not None and not record.get('Adoption Year'):
        try:
            record['Adoption Year'] = int(lower) if not isinstance(lower, int) else lower
        except (ValueError, TypeError):
            record['Adoption Year'] = lower
        return True
    elif lower is not None:
        # Both keys had a value — prefer the existing 'Adoption Year' and discard lower
        return True
    return False


def fix_ccpr_gc31_typo(record: dict) -> bool:
    """`CCPR/C/21/Rev.1/Add. 1326 May 2004` → `CCPR/C/21/Rev.1/Add. 13`."""
    sig = record.get('Signature', '')
    if sig == 'CCPR/C/21/Rev.1/Add. 1326 May 2004':
        record['Signature'] = 'CCPR/C/21/Rev.1/Add. 13'
        return True
    return False


# Provider-specific link standardisation:
# 1. `https://undocs.org/Home/Mobile?FinalSymbol=X&Language=E&...`
#    → `https://tbinternet.ohchr.org/_layouts/15/treatybodyexternal/Download.aspx?symbolno=X&Lang=en`
# 2. `https://www.ohchr.org/en/documents/general-comments-and-recommendations/...`
#    → use Signature to construct the canonical URL.
# 3. `https://www.refworld.org/...` → use Signature to construct.
def standardise_link(record: dict) -> bool:
    link = record.get('Link', '')
    sig = record.get('Signature', '').strip()
    if not link or 'tbinternet.ohchr.org' in link:
        return False

    # Strategy: rebuild from Signature (the canonical UN identifier).
    # For records with non-unique signatures (`A/48/18`, etc.) we keep the original.
    if sig and not _is_session_report_signature(sig):
        # URL-encode the signature, taking the FIRST signature for joints
        primary_sig = sig.split(',')[0].split('–')[0].split('/Rev')[0].strip()
        encoded = urllib.parse.quote(primary_sig, safe='')
        new_link = (
            f'https://tbinternet.ohchr.org/_layouts/15/treatybodyexternal/'
            f'Download.aspx?symbolno={encoded}&Lang=en'
        )
        record['Link'] = new_link
        return True
    return False


def _is_session_report_signature(sig: str) -> bool:
    """Returns True if signature is a UN session report (A/XX/YY)
    that bundles multiple GCs and shouldn't be used to construct a Download URL."""
    return bool(re.match(r'^A/\d{2,3}/\d{1,3}$', sig)) or sig.startswith('HRI/GEN')


def remove_orphan_records(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Remove records whose File PATH points to a file that doesn't exist
    AND for which a near-duplicate record exists (e.g. -REV variant).
    Returns (kept, dropped)."""
    kept = []
    dropped = []
    existing_files = {p.name for p in GC_SRC.glob('*.json')}
    existing_files |= {p.name for p in GC_LABELED.glob('*.json')}

    # Build a lookup of similar names to detect duplicates
    file_basenames = {Path(r.get('File PATH', '')).name for r in records}

    for r in records:
        bn = Path(r.get('File PATH', '')).name
        if bn in existing_files:
            kept.append(r)
            continue

        # File missing — is there a near-duplicate (same stem prefix) we already keep?
        stem = bn.replace('.json', '')
        siblings = [
            f for f in existing_files
            if stem.replace('Annotated_', '').replace('-Harmful', '') in
               f.replace('Annotated_', '').replace('-Harmful', '').replace('-REV', '')
            and f != bn
        ]
        if siblings:
            print(f'  ✗ DROP orphan: {r.get("Signature","?")} ({bn}) — '
                  f'duplicate of {siblings[0]}')
            dropped.append(r)
        else:
            # Keep records whose files are missing for other reasons
            print(f'  ⚠ KEEP orphan: {r.get("Signature","?")} ({bn}) — no duplicate found')
            kept.append(r)
    return kept, dropped


# ---------------------------------------------------------------------------
# Phase 2 derivations
# ---------------------------------------------------------------------------

def extract_articles_from_name(name: str) -> list[str]:
    """Extract treaty-article references from the GC Name field.

    Handles:
      - 'article N' / 'art. N'
      - 'Article N (M)' / 'Article N(M)'
      - 'Articles N, M' (returns both)
      - parenthetical '(art. N)' / '(article N)'
    Returns a list like ['Art. 6', 'Art. 14(3)'] (deduplicated, order preserved).
    """
    if not name:
        return []
    found: list[str] = []
    # 'article N' or 'art. N' optionally with paragraph
    pat = re.compile(
        r'\b(?:article|art\.?)\s*(\d+(?:\s*\(\s*\d+\s*\)|[a-z]?))',
        re.IGNORECASE,
    )
    for m in pat.finditer(name):
        # Normalise: strip whitespace inside parens, capitalise as Art.
        art = m.group(1)
        art = re.sub(r'\s+', '', art)
        norm = f'Art. {art}'
        if norm not in found:
            found.append(norm)
    return found


def count_paragraphs_words_labels(filename: str) -> tuple[int, int, int]:
    """Open the labelled JSON for a document and return (paragraphs, words,
    labels). Returns (0, 0, 0) if file not found."""
    candidates = [GC_LABELED / filename, SP_LABELED / filename]
    for c in candidates:
        if not c.exists():
            continue
        try:
            data = json.loads(c.read_text())
        except Exception:
            return (0, 0, 0)
        paras = 0
        words = 0
        labels = 0
        for p in data:
            if not isinstance(p, dict):
                continue
            paras += 1
            words += len(p.get('Text', '').split())
            labels += len(p.get('Labels', []))
        return (paras, words, labels)
    return (0, 0, 0)


def file_added_at(filename: str) -> str:
    """Return ISO date of file mtime (proxy for first-added)."""
    for c in [GC_LABELED / filename, SP_LABELED / filename, GC_SRC / filename, SP_SRC / filename]:
        if c.exists():
            ts = c.stat().st_mtime
            from datetime import datetime, timezone
            return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    return TODAY_ISO


def extract_ohchr_symbol(record: dict) -> str | None:
    """Pull the canonical UN doc symbol out of either the Link query string
    or the Signature field.

    Examples:
      Link  ?symbolno=E%2FC.12%2FGC%2F27&Lang=en       → E/C.12/GC/27
      Sig   CEDAW/C/GC/40                              → CEDAW/C/GC/40
    """
    # Link first
    link = record.get('Link', '')
    m = re.search(r'symbolno=([^&]+)', link)
    if m:
        sym = urllib.parse.unquote(m.group(1)).strip()
        if sym:
            return sym
    m = re.search(r'FinalSymbol=([^&]+)', link)
    if m:
        return urllib.parse.unquote(m.group(1)).strip()
    # Fall back to first comma-/dash-split signature
    sig = record.get('Signature', '').strip()
    if sig:
        return sig.split(',')[0].split('–')[0].strip()
    return None


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def repair_gc_metadata():
    print('\n=== GC metadata repair ===')
    records = json.loads(GC_META.read_text())
    n_before = len(records)
    n_year_cast = 0
    n_typo = 0
    n_link = 0

    for r in records:
        if cast_year_to_int(r):
            n_year_cast += 1
        if fix_ccpr_gc31_typo(r):
            n_typo += 1
        if standardise_link(r):
            n_link += 1

    # Drop orphans
    print('\n  Checking for orphan records...')
    records, dropped = remove_orphan_records(records)

    # Phase 2 enrichment
    print('\n  Enriching records...')
    n_enriched = 0
    for r in records:
        bn = Path(r.get('File PATH', '')).name
        paras, words, labels = count_paragraphs_words_labels(bn)
        r['paragraphCount'] = paras
        r['wordCount'] = words
        r['labelCount'] = labels
        r['ohchrSymbol'] = extract_ohchr_symbol(r)
        r['firstAddedAt'] = file_added_at(bn)
        r['lastVerifiedAt'] = TODAY_ISO
        r['articles'] = extract_articles_from_name(r.get('Name', ''))
        r['languagesAvailable'] = UN_LANGS  # default; can be overridden later
        # status defaults
        r['status'] = 'final'
        r['supersedes'] = None
        r['supersededBy'] = None
        r['jointWith'] = []
        # Apply curated overrides
        sig = r.get('Signature', '').strip()
        if sig in STATUS_OVERRIDES:
            for k, v in STATUS_OVERRIDES[sig].items():
                r[k] = v
        if sig in JOINT_TABLE:
            r['jointWith'] = JOINT_TABLE[sig]
        n_enriched += 1

    GC_META.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    print(f'\n  ✓ Wrote {len(records)} records (was {n_before}, dropped {len(dropped)} orphan(s))')
    print(f'    - {n_year_cast} years cast to int')
    print(f'    - {n_typo} signature typo fixed')
    print(f'    - {n_link} links re-standardised to tbinternet')
    print(f'    - {n_enriched} records enriched with new fields')


def repair_sp_metadata():
    print('\n=== SP metadata repair ===')
    records = json.loads(SP_META.read_text())
    n_year_merged = 0
    n_year_cast = 0

    for r in records:
        if merge_lowercase_year(r):
            n_year_merged += 1
        if cast_year_to_int(r):
            n_year_cast += 1

    # Phase 2 enrichment (subset that applies to SP)
    n_enriched = 0
    for r in records:
        bn = Path(r.get('File PATH', '')).name
        paras, words, labels = count_paragraphs_words_labels(bn)
        # SP has the SR_belief_ vs A_ filename mismatch — try suffix match
        if paras == 0:
            stem_suffix = bn.replace('SR_belief_', '')
            paras, words, labels = count_paragraphs_words_labels(stem_suffix)
        r['paragraphCount'] = paras
        r['wordCount'] = words
        r['labelCount'] = labels
        r['ohchrSymbol'] = extract_ohchr_symbol(r)
        r['firstAddedAt'] = file_added_at(bn)
        r['lastVerifiedAt'] = TODAY_ISO
        r['languagesAvailable'] = ['en']  # SP usually English-only
        n_enriched += 1

    SP_META.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    print(f'  ✓ Wrote {len(records)} records')
    print(f'    - {n_year_merged} lowercase year fields merged')
    print(f'    - {n_year_cast} years cast to int')
    print(f'    - {n_enriched} records enriched with new fields')


if __name__ == '__main__':
    repair_gc_metadata()
    repair_sp_metadata()
    print('\n✓ Done. Re-run build_corpus.py to refresh documents.json.')
