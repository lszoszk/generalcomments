#!/usr/bin/env python3
"""
Normalise the `adoptionDate` field across docs/jur/documents.json (and
its lite mirror) to ISO 8601 (YYYY-MM-DD where possible, YYYY-MM for
month-only, YYYY for year-only).

Background
----------
Audit found 3,024 of 3,176 JUR docs carrying prose dates like
"25 October 2010" — the OHCHR JURIS HTML extractor preserved the
human-readable form. The frontend's year-range slider and date-sort
fall back to the integer `adoptionYear` field for these, but any
date-arithmetic feature (and the dossier "Adopted" line) reads the
prose value verbatim.

Strategy
--------
  - "DD Month YYYY" / "Month DD, YYYY" / "DD. Month YYYY" → YYYY-MM-DD
  - "Month YYYY"                                          → YYYY-MM
  - "YYYY"                                                → YYYY (kept)
  - already ISO YYYY-MM-DD                                → kept
  - Empty / unparseable noise (":", "200", "under article…") → None,
    falls back to `adoptionYear` in the UI.

Run
----
    python3 _docs_internal/normalize_adoption_date.py            # dry-run
    python3 _docs_internal/normalize_adoption_date.py --apply    # write

Idempotent. Safe on data that already mixes ISO + prose values.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
JUR_FULL = REPO / "docs" / "jur" / "documents.json"
JUR_LITE = REPO / "docs" / "jur" / "documents-lite.json"

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    # short forms occasionally observed
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sept": 9, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Strip leading noise: "...", "~", whitespace, leading periods.
LEADING_NOISE = re.compile(r"^[\s.~…]+")
# "DD Month YYYY" or "DD. Month YYYY" or "DD-Month-YYYY". The
# day↔month and month↔year separators are optional — some records
# have lost the whitespace ("31October 2007", "27 July2022"). Anchor
# is non-greedy so we leave room for trailing-junk capture below.
RE_DMY = re.compile(
    r"^(\d{1,2})\.?\s*[-–\s]?\s*([A-Za-z]+)\.?\s*[-–\s]?\s*(\d{4})(?!\d)"
)
# "Month DD, YYYY"
RE_MDY = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2}),?\s*(\d{4})(?!\d)")
# "Month YYYY"
RE_MY = re.compile(r"^([A-Za-z]+)\.?\s+(\d{4})(?!\d)")
# "YYYY-MM-DD"
RE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
# "YYYY-MM"
RE_ISO_MO = re.compile(r"^(\d{4})-(\d{2})$")
# bare year
RE_YEAR = re.compile(r"^(\d{4})$")


def normalise(raw) -> str | None:
    """Return canonical date string or None if unrecoverable."""
    if not raw:
        return None
    s = str(raw).strip()
    s = LEADING_NOISE.sub("", s).strip()
    if not s:
        return None

    if (m := RE_ISO.match(s)):
        return s
    if (m := RE_ISO_MO.match(s)):
        return s
    if (m := RE_DMY.match(s)):
        d, mo_name, y = m.group(1), m.group(2).lower(), m.group(3)
        mo = MONTHS.get(mo_name)
        if mo:
            return f"{int(y):04d}-{mo:02d}-{int(d):02d}"
    if (m := RE_MDY.match(s)):
        mo_name, d, y = m.group(1).lower(), m.group(2), m.group(3)
        mo = MONTHS.get(mo_name)
        if mo:
            return f"{int(y):04d}-{mo:02d}-{int(d):02d}"
    if (m := RE_MY.match(s)):
        mo_name, y = m.group(1).lower(), m.group(2)
        mo = MONTHS.get(mo_name)
        if mo:
            return f"{int(y):04d}-{mo:02d}"
    if (m := RE_YEAR.match(s)):
        return s
    return None


def process_file(path: Path, apply: bool, stats: Counter) -> int:
    if not path.exists():
        print(f"  skip — not found: {path}", file=sys.stderr)
        return 0
    with path.open() as f:
        data = json.load(f)
    rows = data if isinstance(data, list) else data.get("records", [])
    changed = 0
    for d in rows:
        if not isinstance(d, dict):
            continue
        raw = d.get("adoptionDate")
        if not raw:
            stats["(none)"] += 1
            continue
        norm = normalise(raw)
        if norm is None:
            stats["unrecoverable"] += 1
            # Wipe the noise — UI falls back to `adoptionYear`.
            if d.get("adoptionDate") is not None:
                changed += 1
                if apply:
                    d["adoptionDate"] = None
            continue
        if norm == str(raw).strip():
            stats["already-iso"] += 1
            continue
        stats["normalised"] += 1
        changed += 1
        if apply:
            d["adoptionDate"] = norm
    if changed and apply:
        with path.open("w") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="Write changes back to disk.")
    args = ap.parse_args()

    print(f"Normalising adoptionDate to ISO 8601")
    print(f"  mode: {'APPLY' if args.apply else 'dry-run'}")
    stats = Counter()
    total_changed = 0
    for p in (JUR_FULL, JUR_LITE):
        n = process_file(p, args.apply, stats)
        print(f"  {str(p.relative_to(REPO)):<40s}  {n:>5d} record(s) touched")
        total_changed += n
    print()
    for k, n in sorted(stats.items()):
        print(f"  {k:<20s} {n:>5d}")
    if not args.apply and total_changed:
        print("\nRe-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
