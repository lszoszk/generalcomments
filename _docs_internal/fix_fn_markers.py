#!/usr/bin/env python3
"""Repair misplaced [[fn:N]] markers in the UNHRD corpus.

Two known bug patterns from PDF/PyMuPDF extraction:

  Cat A — fn marker SPLITS a word
          e.g.  "Involv[[fn:22]]ing Human Subjects."
                "retu[[fn:2]]rn"
          Fix : join the word, then push the marker to the end of the
                CURRENT clause/sentence (within ~120 chars). If no
                clause boundary in range, place after the joined word.

  Cat B — fn marker after "No." instead of after the GC number
          e.g.  "general comment No.[[fn:8]] 3"
          Fix : move the marker to AFTER the digit.

Usage:

    python3 fix_fn_markers.py \\
        --corpus  /path/to/docs/corpus.json \\
        --inplace          # edit the file in place
    python3 fix_fn_markers.py \\
        --corpus  /path/to/docs/corpus.json \\
        --out     /tmp/corpus_fixed.json   # or write to a different path
    python3 fix_fn_markers.py \\
        --source-dir /path/to/json_data_gc_labeled_v2 \\
        --inplace          # also fix the upstream per-doc source files

Pass `--dry-run` to preview the diff without writing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CAT_A = re.compile(r'(\w{2,})\[\[fn:(\d+)\]\](\w+)', re.IGNORECASE)
CAT_B = re.compile(r'\bNo\.\s*\[\[fn:(\d+)\]\]\s*(\d+)', re.IGNORECASE)
SENT_END = re.compile(r'[.!?](?=\s|$)')

# Stop words / functional words. When the suffix word in a Cat-A match
# is one of these, the bug is "missing space" rather than "split word"
# — the original PDF text has e.g. `privilege⁵⁰ and laws...` and the
# extractor swallowed the space between "privilege" and "and". Fix is
# to insert the space and leave the marker right after the prefix word
# (where it actually belongs in the source).
STOP_WORDS = {
    "a", "an", "and", "or", "but", "of", "to", "by", "in", "at", "on",
    "the", "is", "was", "were", "are", "as", "that", "this", "these",
    "those", "can", "could", "may", "might", "must", "should", "would",
    "will", "its", "it", "be", "been", "being", "with", "if", "from",
    "for", "have", "has", "had", "all", "any", "each", "every", "such",
    "than", "then", "when", "while", "where", "what", "who", "whom",
    "whose", "which", "during", "before", "after", "until", "since",
    "because", "although", "though", "also", "not", "no", "nor", "so",
    "do", "does", "did", "done", "only", "other", "others", "same",
    "their", "they", "he", "she", "his", "her", "my", "our", "your",
    "we", "us", "him", "them", "ours", "yours", "theirs", "into",
    "onto", "upon", "between", "among", "without", "within", "through",
    "throughout", "across", "against", "via", "per", "ie", "eg",
    "however", "moreover", "furthermore", "thus", "therefore", "hence",
    "indeed", "nevertheless", "nonetheless", "above", "below", "over",
    "under",
}


def fix_cat_b(text: str) -> tuple[str, int]:
    """No.[[fn:N]] X  →  No. X[[fn:N]]   — single regex replacement."""
    new, n = CAT_B.subn(lambda m: f"No. {m.group(2)}[[fn:{m.group(1)}]]", text)
    return new, n


def fix_cat_a(text: str) -> tuple[str, int]:
    """Word1[[fn:N]]Word2  →  fix shape depends on what Word2 is.

    Two sub-cases:
      • If Word2 is a STOP_WORDS / functional word (and / or / the / are
        / when / etc.) — the extractor swallowed a space. Insert space,
        keep the marker right after Word1 (where it really belongs in
        the source PDF).
      • Else — Word2 is a syllable / continuation of Word1 (e.g.
        Involv+ing, retu+rn). Join the words and push the marker to
        the nearest sentence end within 120 chars; otherwise just
        place after the joined word.

    Repeats until stable so a single pass handles paragraphs that
    contain multiple split-word markers.
    """
    fixed = text
    total = 0
    while True:
        m = CAT_A.search(fixed)
        if not m:
            break
        prefix, fn_n, suffix = m.group(1), m.group(2), m.group(3)
        marker = f"[[fn:{fn_n}]]"
        before = fixed[:m.start()]
        after  = fixed[m.end():]

        if suffix.lower() in STOP_WORDS:
            # Missing-space sub-case. Insert space, keep marker between.
            fixed = before + prefix + marker + " " + suffix + after
        else:
            # Word-split sub-case. Join + try to push to clause/sentence end.
            joined = prefix + suffix
            head = after.split("\n", 1)[0][:120]
            sm = SENT_END.search(head)
            if sm:
                cut = sm.end()
                fixed = before + joined + after[:cut] + marker + after[cut:]
            else:
                fixed = before + joined + marker + after
        total += 1
    return fixed, total


def fix_paragraph_text(text: str) -> tuple[str, dict]:
    new, count_b = fix_cat_b(text)
    new, count_a = fix_cat_a(new)
    return new, {"cat_a": count_a, "cat_b": count_b}


# ────────────────────────  Corpus.json (paragraph rows)  ────────────────────────

def fix_corpus_file(path: Path, *, dry_run: bool = False, out: Path | None = None) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    samples = []
    totals = {"cat_a": 0, "cat_b": 0, "paragraphs_fixed": 0}
    for p in data:
        if not isinstance(p, dict): continue
        if p.get("type", "gc") != "gc": continue
        old = p.get("text") or ""
        if "[[fn:" not in old: continue
        new, counts = fix_paragraph_text(old)
        if new != old:
            totals["cat_a"] += counts["cat_a"]
            totals["cat_b"] += counts["cat_b"]
            totals["paragraphs_fixed"] += 1
            if len(samples) < 6:
                samples.append({
                    "id": p.get("id"),
                    "before": old[:300],
                    "after":  new[:300],
                    "counts": counts,
                })
            p["text"] = new
    print(f"[corpus] {path.name}: {totals['paragraphs_fixed']} ¶ fixed "
          f"(Cat-A: {totals['cat_a']}, Cat-B: {totals['cat_b']})")
    for s in samples:
        print(f"\n  --- {s['id']} ({s['counts']}) ---")
        print(f"  BEFORE: ...{s['before']}...")
        print(f"  AFTER : ...{s['after']}...")
    if not dry_run:
        target = out or path
        target.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"\n[corpus] wrote {target}")
    return totals


# ──────────────────────  Source v2 per-doc JSONs (Text + Footnotes)  ───────────

def fix_source_dir(directory: Path, *, dry_run: bool = False) -> dict:
    grand = {"files_changed": 0, "cat_a": 0, "cat_b": 0, "paragraphs_fixed": 0}
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list): continue
        changed = 0
        f_a = f_b = 0
        for entry in data:
            if not isinstance(entry, dict): continue
            old = entry.get("Text")
            if not old or "[[fn:" not in old: continue
            new, counts = fix_paragraph_text(old)
            if new != old:
                entry["Text"] = new
                changed += 1
                f_a += counts["cat_a"]
                f_b += counts["cat_b"]
        if changed:
            grand["files_changed"] += 1
            grand["cat_a"] += f_a
            grand["cat_b"] += f_b
            grand["paragraphs_fixed"] += changed
            print(f"[v2] {path.name}: {changed} ¶ fixed "
                  f"(Cat-A: {f_a}, Cat-B: {f_b})")
            if not dry_run:
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
    print(f"\n[v2] grand total: {grand}")
    return grand


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--corpus",      type=Path, help="docs/corpus.json")
    ap.add_argument("--source-dir",  type=Path, help="json_data_gc_labeled_v2/")
    ap.add_argument("--out",         type=Path, help="write to a different file (corpus mode)")
    ap.add_argument("--inplace",     action="store_true", help="edit files in place")
    ap.add_argument("--dry-run",     action="store_true", help="preview only, don't write")
    args = ap.parse_args()

    if not args.corpus and not args.source_dir:
        ap.error("pass --corpus and/or --source-dir")
    if args.corpus and not args.dry_run and not args.inplace and not args.out:
        ap.error("--corpus needs --inplace or --out (or --dry-run for preview)")

    if args.corpus:
        fix_corpus_file(args.corpus, dry_run=args.dry_run, out=args.out if not args.inplace else None)
    if args.source_dir:
        fix_source_dir(args.source_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
