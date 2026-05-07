#!/usr/bin/env python3
"""
Extract section structure from Special Procedures (SP) report PDFs and
emit a per-doc mapping that the apply step can stitch into corpus.json.

Why
---
SP paragraphs in docs/corpus.json have NO `section` field today (0 of
18,740 paragraphs carry one), so the document reader can't show its
section-rollup heading on SP reports. The PDFs do have the structure
— either as a paragraph-range TOC (older docs, A/HRC/...x format)
or inline section headings between paragraphs (modern A/N/N format).
This script tries both.

Pipeline
--------
For each SP doc in docs/documents.json:
  1. Look up the doc's symbol (signature/ohchrSymbol).
  2. Fetch the English PDF from documents.un.org/api/symbol/access.
  3. Run pdftotext -layout to get plain text.
  4. Try the dotted-leader TOC parser (pre-2010 layout):
        I.   INTRODUCTION ……..   1 - 18    3
     If ≥ 2 sections detected, use those.
  5. Otherwise fall back to inline-heading detection:
        - line starts with N+ leading spaces and matches "(I+|A-Z).  Title"
        - track current paragraph number from lines starting "<digit>." or
          "<digit>.<digit>"
        - heading attaches to the FIRST paragraph that follows it
  6. Emit {docId: {sections: [...], source: 'toc'|'inline', n_paras: N}}

Output
------
_docs_internal/sp-headings/sections.json — to be consumed by
apply_sp_sections.py.

Run
---
    python3 _docs_internal/sp-headings/extract_sp_sections.py
        # processes the entire 173-doc set, ~10 minutes (most time
        # is the PDF download from documents.un.org)
    python3 _docs_internal/sp-headings/extract_sp_sections.py --doc <docId>
        # spot-check a single doc
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import ssl
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DOCS_JSON = REPO / "docs" / "documents.json"
PDF_DIR = REPO / "_docs_internal" / "sp-headings" / "pdfs"
OUT_JSON = REPO / "_docs_internal" / "sp-headings" / "sections.json"
PDF_DIR.mkdir(parents=True, exist_ok=True)

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
HEADERS = {"User-Agent": "Mozilla/5.0 UNHRD-research"}

# Older format: TOC entries with dotted leaders + paragraph ranges.
TOC_RE = re.compile(
    r'(?:^|\n)\s*([IVXLCDM]+)\.\s+(.+?)\.{2,}\s*(\d+)\s*-\s*(\d+)\s+\d+',
    re.DOTALL,
)

# Modern format: inline section heading inside the body. Line that
# starts with "<roman>." (top-level) or "<single-letter>." (sub).
# pdftotext -layout preserves indents — body paragraphs use much more
# leading whitespace than headings, which sit closer to the left
# margin. We allow 1+ space after the period (older docs use double
# space, modern UN docs sometimes a single space).
# Title text starts with capital and runs at least 3 chars.
INLINE_ROMAN_RE = re.compile(r'^\s{1,16}([IVXLCDM]{1,5})\.\s+([A-Z][A-Za-z][^.]{2,200})\s*$')
# Lettered sub-headings need a wider gap (≥2 spaces) between letter
# and title — otherwise "R. Scott Appleby" (an author initial) reads
# as a heading. Genuine UN sub-headings always have generous tab-width
# gaps; abbreviated names use a single space.
INLINE_LETTER_RE = re.compile(r'^\s{2,20}([A-Z])\.\s{2,}([A-Z][A-Za-z][^.]{2,200})\s*$')

# TOC entries have a dotted leader ("……") between title and page
# number. Body headings do not. Used to disambiguate body vs TOC
# roman/letter lines that the heading regexes ALSO match.
DOTTED_LEADER_RE = re.compile(r'\.{3,}\s*\d')

# Body paragraph number marker: "<digits>." at start of an indented
# line, followed by a space and at least one non-space char.
PARA_NUM_RE = re.compile(r'^\s+(\d{1,3})\.\s+\S')

# End-of-body markers: appendix/annex headings, "Notes" (footnote section).
# When we hit one of these, stop processing inline headings — annex
# content has its own numbering that confuses the parser.
END_OF_BODY_RE = re.compile(
    r'^\s*(Annex(es)?|Notes|Appendix|Bibliography|References|Endnotes)\s*[A-Z\d]?\s*$',
    re.IGNORECASE,
)


def fetch_pdf(symbol: str, dest: Path, force: bool = False) -> bool:
    """Download the English PDF if not already cached. Returns True on success."""
    if not force and dest.exists() and dest.stat().st_size > 1024:
        return True
    url = f"https://documents.un.org/api/symbol/access?s={symbol}&l=en&t=pdf"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
            data = r.read()
    except Exception as e:
        print(f"  ✗ fetch failed for {symbol}: {e}", file=sys.stderr)
        return False
    if data[:5] != b"%PDF-":
        print(f"  ✗ {symbol}: not a PDF (got {data[:8]!r})", file=sys.stderr)
        return False
    dest.write_bytes(data)
    return True


def pdf_to_text(pdf: Path) -> str:
    return subprocess.check_output(
        ["pdftotext", "-layout", str(pdf), "-"],
        stderr=subprocess.DEVNULL,
    ).decode(errors="replace")


def parse_toc(text: str) -> list[dict] | None:
    """Older A/N/N format with dotted-leader TOC. Returns a list of
    {roman, title, n_start, n_end} dicts, or None if the pattern doesn't
    match enough sections."""
    matches = list(TOC_RE.finditer(text))
    if len(matches) < 2:
        return None
    out = []
    for m in matches:
        roman = m.group(1)
        title = re.sub(r"\s+", " ", m.group(2)).strip().rstrip(".")
        out.append({
            "roman": roman,
            "title": title,
            "n_start": int(m.group(3)),
            "n_end": int(m.group(4)),
        })
    return out


def parse_inline(text: str) -> list[dict] | None:
    """Modern A/N/N (post-2010) format. Walk the body, attach each detected
    heading to the FIRST paragraph number that appears after it. Returns
    a list of {roman, letter?, title, n_start}.

    Defenses:
      - Skip the Contents/TOC region until we see the first body paragraph
        (a "1. <text>" line not preceded by another heading-shaped line).
      - Stop when we hit "Annex"/"Notes" / sudden paragraph-number reset
        (annex content has independent numbering).
      - Detect roman headings with 1+ space after the period (modern docs
        use single space; older ones use double).
    """
    headings: list[dict] = []
    pending: list[dict] = []
    seen_first_para = False
    last_n = 0
    in_toc = True
    # State for I/V/X disambiguation. Single-letter candidates can be
    # EITHER a roman ("I" = 1) or a letter sub-section ("I" follows H
    # in the alphabet). Track the last seen letter sub in the current
    # roman block; if the candidate is the alphabet-next of it, treat
    # as letter, otherwise default to roman.
    last_letter: str | None = None
    raw_lines = text.splitlines()
    # Pre-extract non-blank lines + their indices so the heading-vs-TOC
    # check can peek at the next non-blank line cheaply.
    non_blank_idx = [i for i, l in enumerate(raw_lines) if l.strip()]

    def _next_nonblank(i):
        for j in non_blank_idx:
            if j > i:
                return raw_lines[j].rstrip()
        return ""

    for line_idx, raw in enumerate(raw_lines):
        line = raw.rstrip()
        if not line.strip():
            continue
        if END_OF_BODY_RE.match(line) and seen_first_para:
            break
        # Body para markers: "<n>. <text>" with leading whitespace
        nm = PARA_NUM_RE.match(line)
        if nm:
            n = int(nm.group(1))
            # Bail if the numbering resets (¶1 or earlier) AFTER we've
            # been past ¶10 — that's an annex / footnote reset.
            if seen_first_para and last_n > 10 and n < 5:
                break
            if not seen_first_para and n != 1:
                continue
            if seen_first_para and n - last_n > 30:
                continue
            seen_first_para = True
            in_toc = False
            last_n = n
            for h in pending:
                h["n_start"] = n
                headings.append(h)
            pending = []
            continue
        # TOC heading lines (with dotted leaders + page numbers) →
        # we're still in the TOC region, ignore. A heading WITHOUT
        # dotted leaders is a body heading — exit TOC mode.
        # Wrapped TOC entries are tricky: their first physical line
        # has no dotted leaders (those land on the continuation line).
        # So also peek at the next non-blank line — if IT carries the
        # leaders, we're still in the TOC.
        rm = INLINE_ROMAN_RE.match(line)
        if rm:
            if DOTTED_LEADER_RE.search(line) or DOTTED_LEADER_RE.search(_next_nonblank(line_idx)):
                continue   # TOC entry (single- or wrapped-line)
            in_toc = False
            candidate = rm.group(1)
            title = re.sub(r"\s+", " ", rm.group(2)).strip().rstrip(".")
            # Single-letter candidates (I, V, X) might actually be the
            # alphabet-next letter sub-section of an in-progress roman
            # block. Disambiguate: if last_letter is set and candidate
            # == chr(last_letter + 1), classify as letter.
            if (len(candidate) == 1 and last_letter
                    and candidate == chr(ord(last_letter) + 1)):
                last_letter = candidate
                pending.append({"letter": candidate, "title": title})
            else:
                last_letter = None  # entering a new roman block
                pending.append({"roman": candidate, "title": title})
            continue
        lm = INLINE_LETTER_RE.match(line)
        if lm:
            if DOTTED_LEADER_RE.search(line) or DOTTED_LEADER_RE.search(_next_nonblank(line_idx)):
                continue
            in_toc = False
            letter = lm.group(1)
            title = re.sub(r"\s+", " ", lm.group(2)).strip().rstrip(".")
            last_letter = letter
            pending.append({"letter": letter, "title": title})
            continue
    if len(headings) < 2:
        return None
    return headings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--doc", help="Limit to a single docId")
    ap.add_argument("--no-fetch", action="store_true",
                    help="Use cached PDFs only; skip network fetch")
    args = ap.parse_args()

    with DOCS_JSON.open() as f:
        docs = json.load(f)
    sp_docs = [d for d in docs if d.get("type") == "sp"]
    if args.doc:
        sp_docs = [d for d in sp_docs if d["docId"] == args.doc]
    print(f"Processing {len(sp_docs)} SP docs")

    out: dict = {}
    if OUT_JSON.exists():
        try:
            out = json.loads(OUT_JSON.read_text())
        except Exception:
            out = {}

    n_toc = n_inline = n_none = 0
    for i, d in enumerate(sp_docs, start=1):
        doc_id = d["docId"]
        symbol = d.get("signature") or d.get("ohchrSymbol") or doc_id
        pdf = PDF_DIR / f"{doc_id}.pdf"
        if not args.no_fetch:
            if not fetch_pdf(symbol, pdf):
                n_none += 1
                continue
            time.sleep(0.4)         # gentle on UN's CDN
        if not pdf.exists():
            n_none += 1
            continue
        try:
            text = pdf_to_text(pdf)
        except Exception as e:
            print(f"  ✗ {doc_id}: pdftotext failed: {e}", file=sys.stderr)
            n_none += 1
            continue

        sections = parse_toc(text)
        source = "toc"
        if not sections:
            sections = parse_inline(text)
            source = "inline" if sections else None

        if sections:
            out[doc_id] = {"source": source, "sections": sections}
            if source == "toc":
                n_toc += 1
            else:
                n_inline += 1
        else:
            n_none += 1

        if i % 10 == 0 or args.doc:
            sec_n = len(sections) if sections else 0
            print(f"  [{i:>3}/{len(sp_docs)}] {doc_id:<35s}  source={source!s:<7}  sections={sec_n}")

    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"\nResult:")
    print(f"  TOC parser hits:    {n_toc}")
    print(f"  inline parser hits: {n_inline}")
    print(f"  no sections found:  {n_none}")
    print(f"  → {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
