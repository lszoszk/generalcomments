#!/usr/bin/env python3
"""
Normalise the `optionalProtocolArticlesParsed` field across
docs/jur/documents.json (and its lite mirror) so every entry is a
proper {instrument, article, paragraph?, subparagraph?, raw} object —
matching the shape used by `covenantArticlesParsed` and
`conventionArticlesParsed`.

Background
----------
Audit found 557 bare-string entries across 279 JUR docs:
    'OP1 Art. 2'
    'OP1 Art. 5(2)(b)'
    'OP1 Art. 5(2)(a)'
The dossier renderer expected dicts and printed `Art. undefined` chips
for these. v19.50.1 added a runtime coercion in `formatArt()` that
treats string entries as already-formatted text, so the UI no longer
shows "undefined". This script fixes the underlying data so the
runtime coercion can eventually be removed.

Parser
------
Recognises:
  "OP1 Art. 2"           → {instrument:'OP1', article:'2'}
  "OP1 Art. 5(2)(b)"     → {instrument:'OP1', article:'5',
                            paragraph:'2', subparagraph:'b'}
  "OP2 Art. 1"           → {instrument:'OP2', article:'1'}
  "OP-CEDAW Art. 4"      → {instrument:'OP-CEDAW', article:'4'}
  "Optional Protocol I, art. 5(2)" → similar
Falls back to keeping the raw string if it doesn't parse.

Run
----
    python3 _docs_internal/normalize_op_articles.py            # dry-run
    python3 _docs_internal/normalize_op_articles.py --apply    # write

Idempotent.
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

# Captures: instrument-prefix? + "Art." + article + optional (paragraph)
# (subparagraph) clauses. Common variants:
#   "OP1 Art. 2"
#   "OP1 Art. 5(2)(b)"
#   "OP-CEDAW Art. 4 (1)"
#   "Optional Protocol I, art. 5 (2) (a)"
RE_INSTRUMENT_HEAD = re.compile(
    r"^\s*("
    r"OP\d|OP[-_ ]?CEDAW|OP[-_ ]?CRPD|OP[-_ ]?CRC|"
    r"Optional\s+Protocol\s+(?:I{1,2}|\d+)|"
    r"OP"
    r")\s*",
    re.IGNORECASE,
)
RE_ART = re.compile(
    r"\bArt\.?\s*(\d+)\s*(?:\((\w+)\))?\s*(?:\((\w+)\))?",
    re.IGNORECASE,
)


def parse_one(raw: str) -> dict | None:
    """Return a dict or None (caller falls back to keeping the string)."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None

    instrument = None
    if (m := RE_INSTRUMENT_HEAD.match(s)):
        instrument = _canonical_instrument(m.group(1))
        s = s[m.end():].lstrip(", -")

    art_match = RE_ART.search(s)
    if not art_match:
        return None
    article = art_match.group(1)
    paragraph = art_match.group(2)
    subparagraph = art_match.group(3)
    out: dict = {"raw": raw}
    if instrument:
        out["instrument"] = instrument
    out["article"] = article
    if paragraph:
        out["paragraph"] = paragraph
    if subparagraph:
        out["subparagraph"] = subparagraph
    return out


def _canonical_instrument(s: str) -> str:
    s = s.strip().upper().replace("_", "-").replace(" ", "")
    # "OPTIONALPROTOCOLI" → "OP1"
    if s.startswith("OPTIONALPROTOCOL"):
        rest = s[len("OPTIONALPROTOCOL"):]
        roman = {"I": "1", "II": "2", "III": "3"}
        return "OP" + roman.get(rest, rest)
    return s


def process_file(path: Path, apply: bool) -> tuple[int, int, int]:
    with path.open() as f:
        data = json.load(f)
    docs = data if isinstance(data, list) else data.get("records", [])
    parsed = unparseable = touched_docs = 0
    for d in docs:
        if not isinstance(d, dict):
            continue
        v = d.get("optionalProtocolArticlesParsed")
        if not isinstance(v, list):
            continue
        new_list: list = []
        changed = False
        for entry in v:
            if isinstance(entry, dict):
                new_list.append(entry)
                continue
            obj = parse_one(entry)
            if obj is None:
                new_list.append(entry)
                unparseable += 1
                continue
            new_list.append(obj)
            parsed += 1
            changed = True
        if changed:
            touched_docs += 1
            if apply:
                d["optionalProtocolArticlesParsed"] = new_list
    if touched_docs and apply:
        with path.open("w") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
    return parsed, unparseable, touched_docs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="Write changes back to disk.")
    args = ap.parse_args()

    print(f"Normalising optionalProtocolArticlesParsed (string → object)")
    print(f"  mode: {'APPLY' if args.apply else 'dry-run'}")
    total_parsed = total_unparseable = total_touched = 0
    for p in (JUR_FULL, JUR_LITE):
        n_parsed, n_un, n_docs = process_file(p, args.apply)
        print(f"  {str(p.relative_to(REPO)):<40s}  parsed={n_parsed:>4}  unparseable={n_un:>4}  docs touched={n_docs:>4}")
        total_parsed += n_parsed
        total_unparseable += n_un
        total_touched += n_docs
    print(f"\n  total parsed: {total_parsed}")
    print(f"  total unparseable (kept as string): {total_unparseable}")
    if not args.apply and total_parsed:
        print("\nRe-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
