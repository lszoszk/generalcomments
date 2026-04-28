#!/usr/bin/env python3
"""
SP metadata backfill — assign Mandate holder, reportType, hrcSession, gaSession.

Phase 2.1 follow-up to the v8 metadata audit. Targets specifically the 88 SP
records (all SR Freedom of Religion or Belief) that have no Mandate holder,
plus four cheap derivations that the build_corpus.py consumer can surface:

  - Mandate holder      (curated year-based map for FoR/B)
  - reportType          (annual / thematic / communications / addendum / country-visit)
  - hrcSession          (parsed from A/HRC/{N}/...)
  - gaSession           (parsed from A/{N}/...)
  - presented           (synthesised when missing: "UNGA {N}th session" or
                         "HRC {N}th session" derived from the signature)

This is idempotent — running it twice produces identical output.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path('/Users/lszoszk/Desktop/GC_Database')
SP_META = ROOT / 'mysite_pythonanywhere' / 'specialprocedures_info.json'

# ---------------------------------------------------------------------------
# Mandate-holder map for SR Freedom of Religion or Belief.
# Year is the year on the report (Adoption Year). Boundary tolerance is fine
# because handovers happened mid-year and we only have ~88 records to assign.
# Source: OHCHR mandate page + UN press releases, double-checked against each
# holder's Wikipedia entry on 28 April 2026.
# ---------------------------------------------------------------------------
FOR_B_HOLDERS = [
    # (year_max, name)  — pick the first row whose year_max >= record year
    (1992, "Angelo Vidal d'Almeida Ribeiro"),
    (2003, "Abdelfattah Amor"),
    (2010, "Asma Jahangir"),
    (2016, "Heiner Bielefeldt"),
    (2022, "Ahmed Shaheed"),
    (9999, "Nazila Ghanea"),
]

def for_b_holder_for_year(year: int | None) -> str:
    if not year:
        return ""
    for y_max, name in FOR_B_HOLDERS:
        if year <= y_max:
            return name
    return FOR_B_HOLDERS[-1][1]


# ---------------------------------------------------------------------------
# Report-type classification. Decision tree (first match wins):
# ---------------------------------------------------------------------------
def classify_report_type(signature: str, name: str) -> str:
    sig = signature.strip()
    nm = (name or '').lower()

    # Communications/cases addenda — characteristic name pattern
    if 'summary of cases transmitted' in nm:
        return 'communications'
    if 'communications transmitted' in nm:
        return 'communications'

    # Country-visit reports — name signals
    if any(k in nm for k in ['mission to ', 'visit to ', 'thematic visit to ',
                              'official visit to ', 'visit by the special rapporteur to ']):
        return 'country-visit'

    # Addenda that are not communications — keep as their parent type but
    # with a "addendum" sub-classification
    if re.search(r'/Add\.\d', sig) or '/Corr.' in sig:
        return 'addendum'

    # By signature pattern
    if sig.startswith('A/HRC/') or sig.startswith('E/CN.4/'):
        return 'thematic'
    if re.match(r'^A/\d{2,3}/\d', sig):
        return 'annual'

    return 'other'


# ---------------------------------------------------------------------------
# Session parsing — pulls the session number out of the signature.
# ---------------------------------------------------------------------------
RE_HRC = re.compile(r'^A/HRC/(\d{1,3})/')
RE_UNGA = re.compile(r'^A/(\d{2,3})/')
RE_CN4 = re.compile(r'^E/CN\.4/(\d{4})/')

def parse_sessions(signature: str) -> tuple[int | None, int | None]:
    """Return (hrcSession, gaSession). Either may be None."""
    sig = signature.strip()
    m = RE_HRC.match(sig)
    if m:
        return int(m.group(1)), None
    m = RE_UNGA.match(sig)
    if m and not sig.startswith('A/HRC/'):
        return None, int(m.group(1))
    return None, None


def synthesize_presented(report_type: str, hrc: int | None, ga: int | None,
                         signature: str, year: int | None) -> str:
    """Build a human-readable 'Presented' string when one is missing."""
    if hrc is not None:
        return f"Human Rights Council, {hrc}{_ord_suffix(hrc)} session"
    if ga is not None:
        return f"General Assembly, {ga}{_ord_suffix(ga)} session"
    if signature.startswith('E/CN.4/'):
        return f"Commission on Human Rights ({year or '—'})"
    return ""


def _ord_suffix(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return 'th'
    return {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def main():
    records = json.loads(SP_META.read_text())
    n_records = len(records)
    n_holder_filled = 0
    n_reporttype_added = 0
    n_session_added = 0
    n_presented_filled = 0

    by_committee_holder = {'before': 0, 'after': 0}

    for r in records:
        committee = r.get('Committee', '').strip()
        signature = r.get('Signature', '').strip()
        name = r.get('Name', '')
        year_raw = r.get('Adoption Year')
        try:
            year = int(year_raw) if year_raw else None
        except (TypeError, ValueError):
            year = None

        # -- 1. Mandate holder backfill (only for SR FoR/B with empty field) --
        existing = r.get('Mandate holder', '').strip()
        if existing:
            by_committee_holder['before'] += 1
        if not existing and committee in (
            'SR Freedom of Religion or Belief',
            'SSR Freedom of Religion or Belief',
        ):
            holder = for_b_holder_for_year(year)
            if holder:
                r['Mandate holder'] = holder
                n_holder_filled += 1

        # -- 2. Report type --
        rt = classify_report_type(signature, name)
        r['reportType'] = rt
        n_reporttype_added += 1

        # -- 3. Sessions --
        hrc, ga = parse_sessions(signature)
        if hrc is not None:
            r['hrcSession'] = hrc
            n_session_added += 1
        if ga is not None:
            r['gaSession'] = ga
            n_session_added += 1

        # -- 4. Synthesize Presented if missing --
        presented = r.get('Presented', '').strip()
        if not presented:
            synth = synthesize_presented(rt, hrc, ga, signature, year)
            if synth:
                r['Presented'] = synth
                n_presented_filled += 1

    by_committee_holder['after'] = sum(1 for r in records if r.get('Mandate holder', '').strip())

    SP_META.write_text(json.dumps(records, ensure_ascii=False, indent=2))

    print(f'SP records processed: {n_records}')
    print(f'  Mandate holder filled:   +{n_holder_filled} (was {by_committee_holder["before"]} → now {by_committee_holder["after"]})')
    print(f'  reportType added:        {n_reporttype_added} (all records)')
    print(f'  Sessions parsed:         {n_session_added}')
    print(f'  Presented synthesized:   +{n_presented_filled}')

    # Distribution of report types
    from collections import Counter
    rts = Counter(r.get('reportType', '?') for r in records)
    print(f'\n  reportType distribution:')
    for t, n in rts.most_common():
        print(f'    {n:3d}  {t}')


if __name__ == '__main__':
    main()
