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

# Trailing section header. Anchored to end of string ($). Matches:
#   <punctuation or marker><whitespace><Roman or single letter>.<title>(<parenthetical>)?<eos>
# - Roman is 1..4 of [IVXLCM] (covers I..XL).
# - Letter is single A..Z.
# - The title is capitalized first char + lowercase/space/dash mix; no period
#   except the optional `(art.N)` parenthetical handled separately.
# - The dot after the prefix may have NO trailing space (extractor bug) or one space.
TRAIL_HEADER = re.compile(
    r"""
    [.!?;\]]                       # end of last sentence (period/!/?/;/]])
    \s*                            # optional whitespace
    (?:\[\[fn:\d+\]\])?            # optional [[fn:N]] right after the punct
    \s+                            # at least one whitespace
    (?P<prefix>[IVXLCM]{1,4}|[A-Z]) # Roman or single capital letter
    \.                             # required dot
    \s*                            # optional space (extractor sometimes drops it)
    (?P<title>[A-Z][^.\n]{6,200}?) # title content; no periods, 6-200 chars
    (?P<paren>\s*\([^)]{2,40}\))?  # optional `(art. N)` style trailer
    \s*$                           # end of string
    """,
    re.VERBOSE,
)


def strip_trailing_headers(text: str) -> tuple[str, int]:
    """Iteratively strip trailing section headers. Returns (new, count)."""
    n = 0
    cur = text.rstrip()
    while True:
        m = TRAIL_HEADER.search(cur)
        if not m:
            break
        # Remove the matched header chunk, but KEEP the punctuation that
        # ended the previous sentence (it's the FIRST char of the match).
        cur = cur[: m.start() + 1].rstrip()
        n += 1
    return cur, n


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
