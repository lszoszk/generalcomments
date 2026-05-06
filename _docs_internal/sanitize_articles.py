#!/usr/bin/env python3
"""
Sanitise the articlesCited field across docs/jur/documents.json and the
shipped lite mirror docs/jur/documents-lite.json.

Background
----------
The OHCHR-JURIS ingest used in the v19.47 batch produced 6 malformed
"articlesCited" entries across 2 CCPR cases:

    ccpr-c-38-d-167-1984  →  Art. 1737, Art. 2730, Art. 761879
    ccpr-c-51-d-421-1990  →  Art. 678,  Art. 3321, Art. 319450

These are concatenations of multiple article references that survived
comma-and-space stripping during ingest (e.g. the source had "art. 3,
19, 4, 50" → "319450"). They surface in the search-view "Article
cited" filter and the dossier "Articles cited" chip strip.

We can't recover the original token boundaries, so the safest fix is
to drop any entry whose leading article number exceeds the maximum
article in any UN core treaty (CMW art. 93). Anything > 99 is therefore
mechanically wrong.

Run
----
    python3 _docs_internal/sanitize_articles.py --apply

Without --apply, prints a dry-run summary and exits.

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

ARTICLE_NUM_MAX = 99
LEAD_NUM = re.compile(r"^Art\.\s*(\d+)", re.IGNORECASE)


def is_plausible(value: str) -> bool:
    m = LEAD_NUM.match(str(value))
    if not m:
        # Unknown shape — leave alone, don't mask real bugs.
        return True
    return int(m.group(1)) <= ARTICLE_NUM_MAX


def sanitise_doc(doc: dict) -> tuple[bool, list[str]]:
    """Return (changed, dropped_values). Mutates doc in place."""
    cited = doc.get("articlesCited")
    if not isinstance(cited, list):
        return False, []
    kept: list[str] = []
    dropped: list[str] = []
    for value in cited:
        (kept if is_plausible(value) else dropped).append(value)
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

    print(f"Sanitising articlesCited (drop entries with leading num > {ARTICLE_NUM_MAX})")
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
