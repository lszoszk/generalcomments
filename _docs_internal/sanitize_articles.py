#!/usr/bin/env python3
"""
Sanitise the articlesCited field across docs/jur/documents.json and the
shipped lite mirror docs/jur/documents-lite.json.

Background
----------
The OHCHR-JURIS ingest used in the v19.47 batch produced two classes of
malformed "articlesCited" values:

  CLASS A — concatenated multi-article references (6 entries, 2 cases).
    Source had something like "art. 3, 19, 4, 50" and the ingest
    stripped commas+spaces:

        ccpr-c-38-d-167-1984  →  Art. 1737, Art. 2730, Art. 761879
        ccpr-c-51-d-421-1990  →  Art. 678,  Art. 3321, Art. 319450

    These are caught by a global ceiling of 99 (no UN core treaty has
    more than CMW art. 93).

  CLASS B — paragraph-merge artefacts. 5 distinct values appearing in
    CCPR cases that look like single article numbers but exceed the
    treaty's article count:

        Art. 95, Art. 85, Art. 65, Art. 61

    Almost certainly Art. 9(5), Art. 8(5), Art. 6(5), Art. 6(1) with
    the parentheses stripped. We can't recover the original token
    without the source PDF, so we drop them as mechanically wrong.
    Caught by the per-treaty ceiling table below.

Class A drops are unambiguous; Class B drops are conservative (some
values look plausible but are impossible for the doc's committee).

Run
----
    python3 _docs_internal/sanitize_articles.py            # dry-run
    python3 _docs_internal/sanitize_articles.py --apply    # write

Idempotent: re-running on already-clean data is a no-op.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
JUR_FULL = REPO / "docs" / "jur" / "documents.json"
JUR_LITE = REPO / "docs" / "jur" / "documents-lite.json"

# Global "no UN core treaty has more than this many articles" ceiling.
# Catches the most outrageous concatenation artefacts (Class A).
GLOBAL_ARTICLE_CEILING = 99

# Per-committee/treaty ceilings. Used for Class B detection (a single
# article number that's well-formed but impossible for this doc's
# committee). Article count taken from the substantive treaty plus its
# Optional Protocol where one is widely cited alongside the main treaty.
# Sources: OHCHR treaty texts, current as of 2024.
TREATY_CEILING = {
    "CCPR":  53,   # ICCPR (OP1 has 14 — folded; cited values like "Art. 5(2)(b)" stay valid)
    "CESCR": 31,   # ICESCR
    "CEDAW": 30,
    "CRC":   54,
    "CRPD":  50,
    "CAT":   33,
    "CMW":   93,
    "CED":   45,
    "CERD":  25,   # also seen as "ICERD"
    "ICERD": 25,
}

LEAD_NUM = re.compile(r"^Art\.\s*(\d+)\s*(\(.*)?$", re.IGNORECASE)


def is_plausible(value: str, committee: str | None = None) -> bool:
    """True iff the value's leading article number is plausible for
    the doc's committee. With no committee context, falls back to the
    global ceiling.

    Values with a parenthesised paragraph/sub-paragraph (e.g.
    "Art. 5(2)(b)") are LEFT ALONE — those are well-formed even when
    the leading number rounds up to a value the bare-number heuristic
    would flag (e.g. "Art. 5" vs "Art. 51"). The Class B bug is
    specifically that parens were stripped, so values WITH parens are
    inherently safe.
    """
    m = LEAD_NUM.match(str(value))
    if not m:
        # Unknown shape — leave alone, don't mask real bugs.
        return True
    has_paren = bool(m.group(2))
    if has_paren:
        return True
    n = int(m.group(1))
    if n > GLOBAL_ARTICLE_CEILING:
        return False
    # Class B: bare-number values exceeding the doc's treaty ceiling.
    ceiling = TREATY_CEILING.get((committee or "").upper())
    if ceiling and n > ceiling:
        return False
    return True


def sanitise_doc(doc: dict) -> tuple[bool, list[str]]:
    """Return (changed, dropped_values). Mutates doc in place."""
    cited = doc.get("articlesCited")
    if not isinstance(cited, list):
        return False, []
    committee = doc.get("committee") or ""
    kept: list[str] = []
    dropped: list[str] = []
    for value in cited:
        (kept if is_plausible(value, committee) else dropped).append(value)
    if not dropped:
        return False, []
    doc["articlesCited"] = kept
    return True, dropped


def process_file(path: Path, apply: bool) -> int:
    if not path.exists():
        print(f"  skip — not found: {path}", file=sys.stderr)
        return 0
    with path.open() as f:
        data = json.load(f)
    docs_iter = data if isinstance(data, list) else data.get("records") or []
    changes = 0
    for doc in docs_iter:
        if not isinstance(doc, dict):
            continue
        changed, dropped = sanitise_doc(doc)
        if changed:
            changes += 1
            print(f"    {doc.get('docId', '?')}: dropped {dropped}")
    if changes and apply:
        with path.open("w") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
    print(f"  {path.name}: {changes} doc(s) cleaned")
    return changes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="Write changes back to disk.")
    args = ap.parse_args()

    print(f"Sanitising articlesCited:")
    print(f"  - global ceiling > {GLOBAL_ARTICLE_CEILING}  (concatenation artefacts)")
    print(f"  - per-treaty ceiling (e.g. CCPR = {TREATY_CEILING['CCPR']})  (paragraph-merge artefacts)")
    print(f"  mode: {'APPLY' if args.apply else 'dry-run'}")
    total = 0
    for p in (JUR_FULL, JUR_LITE):
        print(f"\n  {p.relative_to(REPO)}:")
        total += process_file(p, args.apply)
    print(f"\nTotal docs touched: {total}")
    if not args.apply and total:
        print("Re-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
