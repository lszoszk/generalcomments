#!/usr/bin/env python3
"""
Strip "English Title" placeholder values from caseName / caseNameDisplay
across docs/jur/documents.json and docs/jur/documents-lite.json.

Background
----------
18 recent CCPR session-142 records leaked through with the literal
string "English Title" in `caseName` and `caseNameDisplay`. The
upstream extractor uses that as a "no real title found" placeholder
and was supposed to replace it before serialisation; in this batch
the replacement step was skipped.

The runtime label fallback chain (publicDocTitle / formatDocHeadline)
already handles missing case-name values by falling back to
`nameShort` → `name` → `symbol` → `docId`, all of which are populated
correctly. So the right fix is to NULL these placeholders out instead
of trying to recover the missing data — the UI will then render a
proper "<symbol> · <country>" headline rather than the literal
"English Title".

Run
----
    python3 _docs_internal/sanitize_titles.py            # dry-run
    python3 _docs_internal/sanitize_titles.py --apply    # write

Idempotent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
JUR_FULL = REPO / "docs" / "jur" / "documents.json"
JUR_LITE = REPO / "docs" / "jur" / "documents-lite.json"

PLACEHOLDER = "English Title"
FIELDS = ("caseName", "caseNameDisplay", "name", "nameShort", "title")


def sanitise_doc(doc: dict) -> tuple[bool, list[str]]:
    """Return (changed, fields_cleaned). Mutates doc in place."""
    cleaned: list[str] = []
    for f in FIELDS:
        v = doc.get(f)
        if isinstance(v, str) and v.strip() == PLACEHOLDER:
            doc[f] = None
            cleaned.append(f)
    return bool(cleaned), cleaned


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
        changed, cleaned = sanitise_doc(doc)
        if changed:
            changes += 1
            print(f"    {doc.get('docId', '?')}: nulled {cleaned}")
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

    print(f'Sanitising "English Title" placeholders in {", ".join(FIELDS)}')
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
