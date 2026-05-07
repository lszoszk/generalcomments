#!/usr/bin/env python3
"""
Detect cross-doc text contamination in docs/corpus.json.

Background
----------
The HF dataset that seeds the GC corpus carries a handful of records
whose text was wrongly copied from a SIBLING document during
extraction (e.g. CEDAW GR9 "statisticaldata" carries GR10
"tenth-anniversary" content as one of its paragraphs). These are
real data-quality issues, not splitter bugs — the affected docs need
re-extraction from the authoritative OHCHR source PDF before the
in-app text can match the document title.

Heuristic: take a 200-char fingerprint from the middle of each doc's
longest paragraph (offset 100 → skips the boilerplate "The Committee
on…" prefix). If that fingerprint appears verbatim in any OTHER
doc's text, flag the pair.

Run
----
    python3 _docs_internal/audit_cross_doc_contamination.py

Read-only audit. Produces a markdown report at
_docs_internal/CONTAMINATION-REPORT.md when invoked with --write.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "docs" / "corpus.json"
REPORT = REPO / "_docs_internal" / "CONTAMINATION-REPORT.md"

FP_OFFSET = 100
FP_LENGTH = 200


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true",
                    help="Write a markdown report to _docs_internal/CONTAMINATION-REPORT.md")
    args = ap.parse_args()

    with CORPUS.open() as f:
        corpus = json.load(f)

    by_doc: dict[str, list[str]] = defaultdict(list)
    for p in corpus:
        if p.get("type") == "gc":
            by_doc[p["docId"]].append(norm(p.get("text", "")))

    concat_by_doc = {d: " ".join(ps) for d, ps in by_doc.items()}
    fingerprints: dict[str, str] = {}
    for d, paras in by_doc.items():
        if not paras:
            continue
        longest = max(paras, key=len)
        if len(longest) < FP_OFFSET + FP_LENGTH:
            continue
        fingerprints[d] = longest[FP_OFFSET : FP_OFFSET + FP_LENGTH]

    contamination = []
    for d_src, fp in fingerprints.items():
        for d_target, text in concat_by_doc.items():
            if d_src == d_target:
                continue
            if fp in text:
                contamination.append((d_src, d_target))

    # De-duplicate undirected pairs
    seen_pair = set()
    pairs = []
    for a, b in contamination:
        key = tuple(sorted([a, b]))
        if key in seen_pair:
            continue
        seen_pair.add(key)
        pairs.append(key)

    print(f"Cross-doc contamination pairs found: {len(pairs)}")
    for a, b in sorted(pairs):
        print(f"  {a}  ↔  {b}")

    if args.write:
        lines = [
            "# Cross-doc text contamination",
            "",
            "Detected by `_docs_internal/audit_cross_doc_contamination.py`.",
            "Each pair below shares ≥200 contiguous characters of paragraph text.",
            "These need re-extraction from the authoritative OHCHR source PDFs in",
            "the next ingest batch — the splitter cannot fix them from corpus.json",
            "alone because the wrong-doc text is already serialised.",
            "",
            f"Pairs found: **{len(pairs)}**",
            "",
            "| Doc A | Doc B |",
            "| --- | --- |",
        ]
        for a, b in sorted(pairs):
            lines.append(f"| `{a}` | `{b}` |")
        lines.append("")
        lines.append("## How to fix")
        lines.append("")
        lines.append(
            "For each affected doc, re-extract paragraph text from the OHCHR "
            "PDF (link is on each `documents.json` record), drop the bogus "
            "paragraph(s), and re-run `_docs_internal/resplit_gc_paragraphs.py` "
            "to re-derive preamble + items. The dossier metadata fields "
            "(`name`, `signature`, `committee` etc.) are correct — only the "
            "paragraph body needs replacing."
        )
        REPORT.write_text("\n".join(lines))
        print(f"\nWrote report → {REPORT.relative_to(REPO)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
