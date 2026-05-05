#!/usr/bin/env python3
"""Cat F — strip trailing section header(s) glued to paragraph text.

The PDF/DOCX extractor occasionally concatenates a following section
header onto the previous paragraph's body, producing tails like:

    "...rights of the Child.[[fn:5]] B.Objective and scope of …"
    "…in various places.[[fn:43]] III.Constitutive elements of article 4 A.Public or private custodial setting"
    "…to children's rights and needs. C. The right to life, survival and development (art. 6)"

The structural information already lives in the paragraph's `section`
field (correctly populated for the NEXT paragraph), so the bleed in
body text is purely a duplicate. Strip it.

Algorithm:
  1. Define a TRAIL_HEADER regex matching one trailing section header
     at the end of the string (Roman OR single letter, dot, optional
     space, capitalized title, optional `(art. N)` parenthetical).
  2. Loop: keep stripping trailing headers until the text doesn't end
     with one. Handles paragraphs that have TWO bled-in headers
     (e.g. cat-op-gc-1 ¶26 has III. + A. trailing).
  3. Trim trailing whitespace.

Run:
    python3 fix_cat_f.py --corpus /path/to/corpus.json --inplace
    python3 fix_cat_f.py --corpus /path/to/corpus.json --dry-run
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

# Single section header — title chars exclude `.` and `(` so the regex
# stops cleanly at the next header's prefix-dot or at a parenthetical.
# Optional paren trailer (e.g. `(art. 6 of the Convention)`) is allowed.
ONE_HEADER = (
    r'(?:[IVXLCM]{1,4}|[A-Z])'              # Roman (I..XL) or single capital
    r'\.\s*'                                 # required dot, optional space
    r'[A-Z][^.()\n]{2,200}?'                 # capitalized title (lazy)
    r'(?=\s+(?:[IVXLCM]{1,4}|[A-Z])\.\s*[A-Z]|\s*\(|\s*$)'  # stop at: next header / paren / EOS
    r'(?:\s*\([^)]{2,80}\))?'                # optional `(art. N …)` paren trailer
)

# Trailing header chain anchored at end of string. Matches:
#   <sentence-end punct> <optional [[fn:N]]> <ws>
#   <one or more chained headers separated by whitespace>
TRAIL_CHAIN = re.compile(
    r'([.!?;\]])'                    # group 1: keep this punct
    r'(\s*\[\[fn:\d+\]\])?'          # group 2: keep optional fn marker bonded
    r'\s+'                           # ws between sentence and first header
    r'(?:' + ONE_HEADER + r')'       # first header
    r'(?:\s+(?:' + ONE_HEADER + r'))*'  # zero or more additional chained headers
    r'\s*$'                          # to end of string
)


def strip_trailing_headers(text: str) -> tuple[str, int]:
    """Strip the trailing section-header chain at the end of `text`.

    Returns (new_text, n_headers_stripped). Idempotent — running on
    already-clean text returns it unchanged.
    """
    cur = text.rstrip()
    m = TRAIL_CHAIN.search(cur)
    if not m:
        return cur, 0

    # Count how many headers we're stripping (for reporting)
    chain_start = m.start()
    # The chunk we keep is everything BEFORE the chain, plus the punct +
    # optional [[fn:N]] (groups 1+2) bonded to the previous sentence.
    keep_end = m.start() + len(m.group(1)) + (len(m.group(2)) if m.group(2) else 0)
    new_text = cur[:keep_end].rstrip()
    chain_text = cur[keep_end:].strip()

    # Count individual headers in the chain
    n = 0
    pos = 0
    one_header_re = re.compile(ONE_HEADER)
    while pos < len(chain_text):
        hm = one_header_re.match(chain_text, pos)
        if not hm:
            break
        pos = hm.end()
        n += 1
        while pos < len(chain_text) and chain_text[pos].isspace():
            pos += 1

    return new_text, max(n, 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--inplace", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.dry_run and not args.inplace:
        ap.error("--inplace or --dry-run required")

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    fixed_paras = 0
    headers_stripped = 0
    samples = []

    for p in corpus:
        if p.get("type", "gc") != "gc":
            continue
        old = p.get("text") or ""
        if not old:
            continue
        new, n = strip_trailing_headers(old)
        if n > 0:
            fixed_paras += 1
            headers_stripped += n
            if len(samples) < 12:
                samples.append({
                    "id": p.get("id"),
                    "removed_chars": len(old) - len(new),
                    "stripped": old[len(new):].strip(),
                    "tail_before": old[-180:],
                    "tail_after":  new[-180:],
                })
            if not args.dry_run:
                p["text"] = new

    print(f"[Cat-F] {fixed_paras} ¶ stripped of trailing section headers "
          f"({headers_stripped} headers total)")
    for s in samples:
        print(f"\n  --- {s['id']} (-{s['removed_chars']} chars, stripped: {s['stripped'][:80]!r}) ---")
        print(f"    BEFORE tail: ...{s['tail_before']}")
        print(f"    AFTER  tail: ...{s['tail_after']}")

    if not args.dry_run:
        args.corpus.write_text(
            json.dumps(corpus, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"\nwrote {args.corpus}")


if __name__ == "__main__":
    main()
