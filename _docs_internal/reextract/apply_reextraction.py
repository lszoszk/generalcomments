#!/usr/bin/env python3
"""
Apply re-extracted source text to the 9 contaminated CEDAW + CERD docs
in docs/corpus.json.

Pipeline
--------
For each doc:
  1. Read the cleaned source from _docs_internal/reextract/texts/<docId>.txt
     (already extracted from the OHCHR PDF/DOC by the fetch step).
  2. Strip boilerplate (CEDAW "IV. GENERAL RECOMMENDATIONS ADOPTED BY…"
     header, session marker, title line, footnote refs, trailing
     " PAGE \\* MERGEFORMAT" Word artefacts).
  3. Collapse the body into a single flat paragraph string with
     whitespace normalised.
  4. Hand off to the existing `_docs_internal/resplit_gc_paragraphs`
     splitter (operative-verb anchor + numbered/lettered items).
  5. Replace the doc's paragraphs in corpus.json with the new ones.

The existing paragraph IDs are reissued as <docId>-NNNN so any
pre-existing bookmarks/permalinks referencing the OLD IDs (which were
contaminated) silently fall through — those bookmarks were pointing at
wrong-doc text anyway, so silent fall-through is the correct behaviour.

Run
----
    python3 _docs_internal/reextract/apply_reextraction.py            # dry-run
    python3 _docs_internal/reextract/apply_reextraction.py --apply    # write
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
CORPUS = REPO / "docs" / "corpus.json"
TEXT_DIR = Path(__file__).resolve().parent / "texts"

# Make split_text + _materialise importable from the resplit script.
sys.path.insert(0, str(REPO / "_docs_internal"))
from resplit_gc_paragraphs import split_text, _materialise  # type: ignore

TARGETS = [
    "annotated-cedaw-gr2-reporting",
    "annotated-cedaw-gr3-campaigns-edu",
    "annotated-cedaw-gr4-reservations",
    "annotated-cedaw-gr8-art-8",          # carried GR9 text (cascade-discovered after GR9 fix)
    "annotated-cedaw-gr9-statisticaldata",
    "annotated-cedaw-gr10-tenth-anniversary",
    "annotated-cerd-gr16-article9",
    "annotated-cerd-gr17-national-institutions",
    "a-41-38",
    "a-49-18",
]

# Lines we always strip from CEDAW PDF dumps. CASE-SENSITIVE — the
# boilerplate header is shouted in ALL CAPS ("THE COMMITTEE ON THE
# ELIMINATION OF / DISCRIMINATION AGAINST WOMEN"), while the legitimate
# preamble lead is mixed case ("The Committee on the Elimination of
# Discrimination against Women,"). A case-insensitive match would
# strip the latter too and the preamble would lose its subject.
CEDAW_HEADER_RE = re.compile(
    r"^\s*IV\.\s*GENERAL RECOMMENDATIONS ADOPTED BY\s*$|"
    r"^\s*THE COMMITTEE ON THE ELIMINATION OF\s*$|"
    r"^\s*DISCRIMINATION AGAINST WOMEN\s*$"
)
SESSION_LINE_RE = re.compile(
    r"^\s*[A-Za-z\-]+(?:\s+[A-Za-z\-]+)*\s+session\s+\(\d{4}\)\*+\s*$",
    re.IGNORECASE,
)
TITLE_LINE_RE = re.compile(
    r"^\s*General [Rr]ecommendation\s+(?:No\.|XVII|XVIII|XVI|[IVXLC]+)",
)
# Footnote / Word artefacts at the end of the file.
FOOTER_NOISE_RE = re.compile(
    r"^\*+\s*$|"
    r"^\s*\*+\s*Contained in document\s+\S+\.?\s*$|"
    r"^\s*Contained in document\s+\S+\.?\s*$|"
    r"^\s*PAGE\s*\\?\*?\s*MERGEFORMAT.*$|"
    r"^\s*\d+\s*$",   # bare page numbers
    re.IGNORECASE,
)


def clean_source(text: str) -> str:
    """Return the operative body — preamble + items — as a single
    whitespace-normalised string."""
    # CERD .doc → .txt conversions emit Unicode LINE SEPARATOR ( )
    # for in-paragraph soft breaks, so a wrapped title line like
    # "General recommendation XVIII on the establishment of an
    # international tribunal to prosecute crimes against humanity"
    # gets split into two by .splitlines() and only the first half
    # matches the title-line filter. Normalise to regular newlines so
    # the WHOLE wrapped title is one line for matching, and downstream
    # paragraph joining isn't fooled by stray separators.
    text = (text.replace(" ", " ")
                .replace(" ", " ")
                .replace(" ", " "))
    body_lines: list[str] = []
    in_title = False  # title can wrap to a continuation line — consume both
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            in_title = False  # blank line ends the title block
            continue
        if CEDAW_HEADER_RE.match(line):
            continue
        if SESSION_LINE_RE.match(line):
            continue
        if TITLE_LINE_RE.match(line):
            in_title = True
            continue
        if in_title:
            # Title continuation: indented mixed-case line that doesn't
            # start the operative content (no leading "The Committee",
            # gerund, or numbered/lettered marker). Drop it.
            stripped = line.lstrip()
            if stripped.startswith(("The Committee", "Bearing in mind",
                                    "Recalling", "Considering", "Noting",
                                    "Affirming", "Reaffirming", "Having",
                                    "Convinced", "Alarmed", "Aware",
                                    "Recommends", "1.", "(a)")):
                in_title = False
                # fall through to record as body
            else:
                continue
        if FOOTER_NOISE_RE.match(line):
            continue
        # Tab-leading CERD lines come straight from the .doc dump.
        line = line.replace("\t", " ")
        body_lines.append(line.strip())
    flat = " ".join(body_lines)
    # Collapse multi-space and curly-quote/dash variants into the
    # forms our splitter expects.
    flat = re.sub(r"\s{2,}", " ", flat).strip()
    return flat


def apply_to_corpus(corpus: list[dict], doc_id: str, source_text: str) -> tuple[list[dict], int, int]:
    """Replace every paragraph for `doc_id` with re-split versions of
    `source_text`. Returns (new_corpus, n_before, n_after)."""
    olds = [p for p in corpus if p.get("docId") == doc_id]
    others = [p for p in corpus if p.get("docId") != doc_id]
    template_src = olds[0] if olds else {"docId": doc_id, "type": "gc"}
    template = {
        k: v for k, v in template_src.items()
        if k not in ("id", "n", "idx", "text", "isPreamble")
    }
    template["docId"] = doc_id
    splits = split_text(source_text)
    new = _materialise(doc_id, template, splits) if splits else []
    return others + new, len(olds), len(new)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="Write changes back to disk.")
    args = ap.parse_args()

    print(f"Re-extracting {len(TARGETS)} contaminated GC docs from OHCHR sources")
    print(f"  mode: {'APPLY' if args.apply else 'dry-run'}")

    with CORPUS.open() as f:
        corpus = json.load(f)

    summary = []
    new_corpus = corpus
    for doc_id in TARGETS:
        src = TEXT_DIR / f"{doc_id}.txt"
        if not src.exists():
            print(f"  ✗ {doc_id}: missing source text"); continue
        clean = clean_source(src.read_text())
        new_corpus, before, after = apply_to_corpus(new_corpus, doc_id, clean)
        summary.append((doc_id, before, after, len(clean)))

    print(f"\n  {'docId':<54}  before  after  src-chars")
    for d, b, a, c in summary:
        print(f"  {d:<54}  {b:>6}  {a:>5}  {c:>6}")
    total_before = sum(b for _, b, _, _ in summary)
    total_after = sum(a for _, _, a, _ in summary)
    print(f"\n  Total: {total_before} → {total_after} paragraphs across {len(TARGETS)} docs")

    if args.apply:
        with CORPUS.open("w") as f:
            json.dump(new_corpus, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        print(f"\n  ✅ wrote {len(new_corpus):,} paragraphs to {CORPUS.relative_to(REPO)}")
    else:
        print("\n  Re-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
