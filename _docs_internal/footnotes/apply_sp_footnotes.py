#!/usr/bin/env python3
"""Stitch SP footnote data (from extract_sp_footnotes.py) onto
docs/corpus.json.

WHY THIS IS A SEPARATE SCRIPT
-----------------------------
Same architecture as apply_sp_sections.py:
  • extract_sp_footnotes.py is the slow, network-bound, side-effecting
    side (download docx, walk OOXML, write footnotes.json).
  • apply_sp_footnotes.py is the fast, idempotent, deterministic side
    that mutates docs/corpus.json from the cached JSON.

INPUT
-----
_docs_internal/footnotes/footnotes.json:

    { "<docId>": { "source": "docx", "signature": "...",
                   "paragraphs": { "<n>": {
                     "inline_text": "1. The mandate...[[fn:1]]...",
                     "footnotes": [{"n": 1, "text": "..."}, ...]
                   } } }, ... }

OUTPUT
------
For each paragraph row p in docs/corpus.json that matches by docId+n:

    p["text"]      ← merged in [[fn:N]] markers from inline_text,
                     KEEPING the existing corpus text body where possible
                     (corpus has gone through re-extraction; we trust it).
    p["footnotes"] ← list of {n, text} objects from the docx walk.

MARKER MERGE STRATEGY
---------------------
The corpus paragraph text is the canonical body (it came from
re-extraction or the original .docx walk). The docx-derived
inline_text contains the same words PLUS [[fn:N]] markers at exact
Word-recorded positions. We:

  1. Tokenize both into a sequence of word-tokens.
  2. Walk the corpus tokens and the docx tokens in lockstep, copying
     [[fn:N]] tokens into the corpus side at the same word offset.
  3. If the alignment is high-confidence (≥85% of words match),
     write the merged text.
  4. Otherwise, attach `footnotes` array but leave `text` unchanged
     — readers tolerate orphan footnote entries (Lesson L4).

USAGE
-----
    python3 _docs_internal/footnotes/apply_sp_footnotes.py            # dry run
    python3 _docs_internal/footnotes/apply_sp_footnotes.py --apply    # write
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent.parent
CORPUS = REPO / "docs" / "corpus.json"
FOOTNOTES_JSON = REPO / "_docs_internal" / "footnotes" / "footnotes.json"

WORD = re.compile(r"\w+", re.UNICODE)
FN_TOKEN = re.compile(r"\[\[fn:(\d+)\]\]")


def tokenize_with_markers(text: str) -> list[tuple[str, str]]:
    """Tokenize a string into [(kind, value), ...] where kind is one of:
      'word'   — alphanumeric run (lowercased for comparison)
      'fn'     — [[fn:N]] marker
    Whitespace and punctuation are dropped from the comparison stream
    so trivial differences don't kill the alignment."""
    tokens: list[tuple[str, str]] = []
    i = 0
    while i < len(text):
        m_fn = FN_TOKEN.match(text, i)
        if m_fn:
            tokens.append(("fn", m_fn.group(0)))
            i = m_fn.end()
            continue
        m_w = WORD.match(text, i)
        if m_w:
            tokens.append(("word", m_w.group(0).lower()))
            i = m_w.end()
            continue
        i += 1
    return tokens


def merge_markers_into_text(
    corpus_text: str, docx_text: str, *, min_overlap: float = 0.85
) -> tuple[Optional[str], dict]:
    """Project [[fn:N]] markers from docx_text onto corpus_text.

    Returns (merged_text_or_None, info). When alignment is below
    min_overlap on the matched word run, returns (None, info) so the
    caller falls back to attaching footnotes-as-array only."""
    docx_tokens = tokenize_with_markers(docx_text)
    corpus_words = [m.group(0) for m in WORD.finditer(corpus_text)]
    if not corpus_words or not docx_tokens:
        return None, {"reason": "empty_tokens"}

    # Walk docx tokens, matching word tokens against corpus_words[ci].
    # When we hit an 'fn' token, remember "after corpus word index ci".
    docx_words = [t[1] for t in docx_tokens if t[0] == "word"]
    n_match = sum(1 for a, b in zip(docx_words, [w.lower() for w in corpus_words]) if a == b)
    overlap = n_match / max(len(docx_words), len(corpus_words))
    if overlap < min_overlap:
        return None, {"reason": "low_overlap", "overlap": round(overlap, 3),
                      "docx_words": len(docx_words), "corpus_words": len(corpus_words)}

    # Build marker → corpus-word-index list (word index = N means "after Nth word").
    markers_by_word_idx: list[tuple[int, str]] = []
    ci = 0
    for kind, val in docx_tokens:
        if kind == "word":
            ci += 1
        else:  # fn
            markers_by_word_idx.append((ci, val))

    # Now rebuild corpus_text with markers inserted after the
    # corresponding word position.
    # Walk corpus_text character-by-character, counting WORD spans.
    out_parts: list[str] = []
    pos = 0
    word_count = 0
    pending = list(markers_by_word_idx)  # consumed in order
    for m in WORD.finditer(corpus_text):
        out_parts.append(corpus_text[pos:m.end()])
        pos = m.end()
        word_count += 1
        # Insert any markers that target this word-count.
        while pending and pending[0][0] == word_count:
            out_parts.append(pending.pop(0)[1])
    out_parts.append(corpus_text[pos:])
    # Any remaining markers (target word index past corpus end) — stick at the end.
    for _, marker in pending:
        out_parts.append(marker)
    merged = "".join(out_parts)
    return merged, {"reason": "ok", "overlap": round(overlap, 3),
                    "markers": len(markers_by_word_idx)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="Write changes back to docs/corpus.json.")
    ap.add_argument("--doc", help="Process only this docId.")
    ap.add_argument("--min-overlap", type=float, default=0.85,
                    help="Minimum word overlap to write merged text "
                         "(default 0.85). Below this, attach footnotes "
                         "array only — leave text untouched.")
    args = ap.parse_args()

    if not FOOTNOTES_JSON.exists():
        print(f"  ✗ {FOOTNOTES_JSON.relative_to(REPO)} not found — "
              f"run extract_sp_footnotes.py first.", file=sys.stderr)
        return 1

    sec = json.loads(FOOTNOTES_JSON.read_text())
    print(f"Stitching footnotes from {FOOTNOTES_JSON.relative_to(REPO)}")
    print(f"  source records: {len(sec)} docs")
    print(f"  mode: {'APPLY' if args.apply else 'dry-run'}")
    print()

    with CORPUS.open() as f:
        corpus = json.load(f)

    target_docs = list(sec.keys())
    if args.doc:
        target_docs = [args.doc] if args.doc in sec else []

    changed_paras = 0
    set_text = 0
    set_array_only = 0
    skipped_low_overlap = 0
    extras_aligned = 0
    extras_orphaned = 0
    docs_touched = 0

    # Pre-build a docId → [paragraphs sorted by n] index for extras alignment.
    by_doc: dict[str, list[dict]] = {}
    for p in corpus:
        did = p.get("docId")
        if did:
            by_doc.setdefault(did, []).append(p)

    def _first_words(s: str, k: int = 12) -> str:
        return " ".join(WORD.findall((s or "").lower())[:k])

    for doc_id in target_docs:
        info = sec[doc_id]
        para_data = info.get("paragraphs", {})
        extras = info.get("extras", []) or []
        if not para_data and not extras:
            continue
        touched = 0
        # ── Phase 1: numbered-prefix matches (high precision)
        for p in by_doc.get(doc_id, []):
            n = p.get("n")
            if n is None:
                continue
            entry = para_data.get(str(n))
            if not entry:
                continue
            corpus_text = p.get("text") or ""
            docx_text = entry.get("inline_text") or ""
            footnotes = entry.get("footnotes") or []

            merged, mi = merge_markers_into_text(
                corpus_text, docx_text, min_overlap=args.min_overlap,
            )

            existing_fn = p.get("footnotes") or []
            new_fn = footnotes
            existing_text = p.get("text")

            wrote_text = False
            wrote_array = False

            if merged is not None and "[[fn:" in merged:
                if existing_text != merged:
                    if args.apply:
                        p["text"] = merged
                    wrote_text = True
                    set_text += 1
            elif merged is None:
                skipped_low_overlap += 1

            if existing_fn != new_fn:
                if args.apply:
                    p["footnotes"] = new_fn
                wrote_array = True
                if not wrote_text:
                    set_array_only += 1

            if wrote_text or wrote_array:
                touched += 1

        # ── Phase 2: extras (Word-list-numbered ¶s) by content prefix.
        # Match each extra to the corpus ¶ in this docId whose first 12
        # words best agree with the extra's first 12 words. Skip extras
        # whose target ¶ already received markers in phase 1, and skip
        # corpus ¶s that already have markers/footnotes assigned this
        # run (no double-attachment).
        if extras:
            corpus_paras = by_doc.get(doc_id, [])
            # Build {prefix → [paragraphs]} for fast best-match lookup.
            prefixes: dict[str, list[dict]] = {}
            for p in corpus_paras:
                fw = _first_words(p.get("text") or "")
                if fw:
                    prefixes.setdefault(fw, []).append(p)
            for extra in extras:
                target_prefix = _first_words(extra.get("inline_text") or "")
                if not target_prefix:
                    extras_orphaned += 1
                    continue
                # Strip the leading "1." / numbering token from extra prefix
                # — corpus has "n. <body>" while extras body lacks it.
                # Take the longest sub-prefix that matches a corpus ¶.
                cands = prefixes.get(target_prefix)
                if not cands:
                    # Try matching corpus prefix WITHOUT corpus's leading number.
                    # Corpus first words include the integer; drop it from the
                    # corpus side to compare bodies.
                    matches = []
                    for p in corpus_paras:
                        ctext = p.get("text") or ""
                        # Strip leading "N. " prefix from corpus text for compare.
                        cm = re.match(r"^\s*\d+\.\s*", ctext)
                        body_prefix = _first_words(ctext[cm.end():] if cm else ctext, k=10)
                        ext_prefix = " ".join(target_prefix.split()[:10])
                        if body_prefix and ext_prefix and body_prefix == ext_prefix:
                            matches.append(p)
                    cands = matches
                if not cands:
                    extras_orphaned += 1
                    continue
                # Pick the one without existing footnotes (avoid clobber).
                cand = next((p for p in cands if not p.get("footnotes")), cands[0])
                if cand.get("footnotes"):
                    extras_orphaned += 1
                    continue
                merged, mi = merge_markers_into_text(
                    cand.get("text") or "", extra.get("inline_text") or "",
                    min_overlap=args.min_overlap,
                )
                wrote_text = wrote_array = False
                if merged is not None and "[[fn:" in merged:
                    if cand.get("text") != merged:
                        if args.apply:
                            cand["text"] = merged
                        wrote_text = True
                        set_text += 1
                if (cand.get("footnotes") or []) != extra["footnotes"]:
                    if args.apply:
                        cand["footnotes"] = extra["footnotes"]
                    wrote_array = True
                    if not wrote_text:
                        set_array_only += 1
                if wrote_text or wrote_array:
                    touched += 1
                    extras_aligned += 1
                else:
                    extras_orphaned += 1

        if touched:
            docs_touched += 1
            changed_paras += touched

    print(f"  docs touched:                   {docs_touched}")
    print(f"  paragraphs touched:             {changed_paras:,}")
    print(f"  text + array updated:           {set_text:,}")
    print(f"  array only (low overlap text):  {set_array_only:,}")
    print(f"  ¶s skipped (overlap < {args.min_overlap:g}):     {skipped_low_overlap:,}")
    print(f"  extras aligned via prefix:      {extras_aligned:,}")
    print(f"  extras orphaned (no match):     {extras_orphaned:,}")

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
