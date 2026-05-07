#!/usr/bin/env python3
"""
Read _docs_internal/sp-headings/sections.json (produced by
extract_sp_sections.py) and stitch the section data onto every SP
paragraph in docs/corpus.json.

Section field shape
-------------------
A paragraph's `section` is an array (path) — the document reader's
section-rollup heading code already supports nested arrays
(e.g. ["I. Overview", "B. Letters of allegation"]).

For TOC-source docs (paragraph ranges):
  paragraph N falls in section X if X.n_start ≤ N ≤ X.n_end.
  We emit a single-element path: [f"{X.roman}. {X.title}"].

For inline-source docs:
  Sections are sequential by n_start. Each section's range runs from
  its n_start up to (next_section.n_start - 1). Lettered sections
  nest under the most recent roman. We track the active roman so a
  lettered "A. ..." gets path ["I. Roman title", "A. Letter title"].

Run
---
    python3 _docs_internal/sp-headings/apply_sp_sections.py            # dry-run
    python3 _docs_internal/sp-headings/apply_sp_sections.py --apply    # write

Idempotent — re-running on already-stitched data overwrites with the
same values. (Bookmarks / permalinks key off paragraph ID, not
section path, so no UX impact from re-runs.)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
CORPUS = REPO / "docs" / "corpus.json"
SECTIONS = REPO / "_docs_internal" / "sp-headings" / "sections.json"


def expand_inline_ranges(sections: list[dict]) -> list[dict]:
    """Compute n_end for each inline section by looking at the next
    section's n_start. Returns a copy of `sections` with n_end filled."""
    out = []
    for i, s in enumerate(sections):
        n_start = s.get("n_start")
        if n_start is None:
            continue
        # Find the next section with a strictly larger n_start.
        n_end = None
        for j in range(i + 1, len(sections)):
            ns = sections[j].get("n_start")
            if ns is not None and ns > n_start:
                n_end = ns - 1
                break
        out.append({**s, "n_end": n_end if n_end is not None else 9999})
    return out


def build_para_to_path(sections: list[dict], source: str) -> dict[int, list[str]]:
    """Return {paragraph_n: [section path strings]}. Roman sections
    become 1-element paths; lettered sub-sections nest under the
    active roman to form a 2-element path."""
    out: dict[int, list[str]] = {}
    if source == "toc":
        for s in sections:
            label = f"{s['roman']}. {s['title']}"
            for n in range(s.get("n_start", 0), (s.get("n_end") or 0) + 1):
                out[n] = [label]
        return out

    # inline
    sections = expand_inline_ranges(sections)
    active_roman: str | None = None
    for s in sections:
        n_start = s.get("n_start")
        n_end = s.get("n_end") or 9999
        if "roman" in s:
            active_roman = f"{s['roman']}. {s['title']}"
            label_path = [active_roman]
        else:
            letter_label = f"{s['letter']}. {s['title']}"
            label_path = [active_roman, letter_label] if active_roman else [letter_label]
        for n in range(n_start, n_end + 1):
            out[n] = label_path
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="Write changes back to disk.")
    args = ap.parse_args()

    print(f"Stitching SP section labels onto {CORPUS.relative_to(REPO)}")
    print(f"  mode: {'APPLY' if args.apply else 'dry-run'}")

    if not SECTIONS.exists():
        print(f"  ✗ {SECTIONS.relative_to(REPO)} not found — run extract_sp_sections.py first.", file=sys.stderr)
        return 1

    sec_data = json.loads(SECTIONS.read_text())
    print(f"  source records: {len(sec_data)} SP docs with detected sections")

    with CORPUS.open() as f:
        corpus = json.load(f)

    changed_docs = 0
    changed_paras = 0
    for doc_id, info in sec_data.items():
        para_to_path = build_para_to_path(info["sections"], info["source"])
        if not para_to_path:
            continue
        touched_in_doc = 0
        for p in corpus:
            if p.get("docId") != doc_id:
                continue
            n = p.get("n")
            if n is None or n not in para_to_path:
                continue
            new_path = para_to_path[n]
            if p.get("section") == new_path:
                continue
            if args.apply:
                p["section"] = new_path
            touched_in_doc += 1
        if touched_in_doc:
            changed_docs += 1
            changed_paras += touched_in_doc

    print(f"\n  docs touched:        {changed_docs}")
    print(f"  paragraphs touched:  {changed_paras:,}")

    if args.apply:
        with CORPUS.open("w") as f:
            json.dump(corpus, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        print(f"\n  ✅ wrote {len(corpus):,} paragraphs to {CORPUS.relative_to(REPO)}")
    else:
        print("\n  Re-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
