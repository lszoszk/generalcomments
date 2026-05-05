#!/usr/bin/env python3
"""Repair three classes of corpus issues uncovered after fix20.

Cat C — wrong document metadata
        crc-c-gc-23-cmw-c-gc-4 was tagged with the title and year of
        the OTHER joint comment (CRC GC22/CMW GC3). Ground truth is
        in /Users/lszoszk/Downloads/g1734365-2.docx — title "State
        obligations regarding the human rights of children in the
        context of international migration in countries of origin,
        transit, destination and return", adopted 16 November 2017.

Cat D — stray footnote digit after [[fn:N]] marker
        Pattern: "...detention[[fn:5]].4 The Committee..."
        The ".4" is the original PDF footnote number that the
        extractor failed to strip when it inserted the [[fn:5]]
        marker. 36 cases across 4 documents.

Cat E — section header missing space after Roman/letter prefix
        Pattern: "I.Introduction" should be "I. Introduction".
        141 distinct headers — purely cosmetic but affects readability
        of the section breadcrumbs in the dossier and docs reader.

Run:

    python3 fix_corpus_issues.py \\
        --corpus    /path/to/docs/corpus.json \\
        --documents /path/to/docs/documents.json \\
        --inplace

Pass --dry-run for a preview.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


# Cat-C — metadata corrections (manual; one entry per doc).
METADATA_FIXES = {
    "crc-c-gc-23-cmw-c-gc-4": {
        # From g1734365-2.docx (the user-supplied DOCX). Title was the
        # OTHER joint comment's ("general principles"); year was 2019
        # but both joint GCs were adopted on 16 November 2017.
        "name": (
            "Joint general comment No. 4 (2017) of the Committee on the "
            "Protection of the Rights of All Migrant Workers and Members of "
            "Their Families and No. 23 (2017) of the Committee on the Rights "
            "of the Child on State obligations regarding the human rights of "
            "children in the context of international migration in countries "
            "of origin, transit, destination and return"
        ),
        "nameShort": (
            "GC23/GC4: human rights of children in international migration "
            "(countries of origin, transit, destination and return)"
        ),
        "adoptionDate": "16 November 2017",
        "year": 2017,
    },
    "crc-c-gc-22-cmw-c-gc-3": {
        # Sister joint GC adopted same day. Same title-mix-up bug:
        # was "States parties' obligations in particular with respect
        # to countries of transit and destination" (≈ a chunk of the
        # OTHER joint comment's title); year was 2019.
        # Canonical OHCHR title:
        "name": (
            "Joint general comment No. 3 (2017) of the Committee on the "
            "Protection of the Rights of All Migrant Workers and Members of "
            "Their Families and No. 22 (2017) of the Committee on the Rights "
            "of the Child on the general principles regarding the human "
            "rights of children in the context of international migration"
        ),
        "nameShort": (
            "GC22/GC3: general principles re human rights of children in "
            "international migration"
        ),
        "adoptionDate": "16 November 2017",
        "year": 2017,
    },
}

# Cat-D — stray footnote digit. The trailing digit is usually `marker_n - 1`
# (renumbered) but occasionally other small drifts. Match the safe shape:
# `[[fn:N]]` then optional `.` then 1-3 digits then whitespace then a
# capital letter. Then check the digit is close to N (within 5) — that
# avoids false-positives where the trailing digit is actually a year or
# a real number in the prose.
RE_STRAY_DIGIT = re.compile(
    r'\[\[fn:(\d+)\]\](\.?)(\s*)(\d{1,3})(\s+)([A-Z])'
)


def fix_stray_digits(text: str) -> tuple[str, int]:
    """Strip stale fn digits left behind by the extractor.

    Only strips when the trailing number is within ±2 of the marker
    number — i.e. clearly a renumbered fn artifact, not a quoted year
    or paragraph reference.
    """
    count = 0

    def repl(m):
        nonlocal count
        marker_n = int(m.group(1))
        dot      = m.group(2)
        ws_lead  = m.group(3)
        stale_n  = int(m.group(4))
        ws_trail = m.group(5)
        capital  = m.group(6)
        if abs(marker_n - stale_n) <= 2:
            count += 1
            # Keep the period (it's the sentence end) and a single space.
            return f'[[fn:{marker_n}]]{dot} {capital}' if dot else f'[[fn:{marker_n}]] {capital}'
        return m.group(0)

    new = RE_STRAY_DIGIT.sub(repl, text)
    return new, count


# Cat-E — section header no-space. Two sub-patterns:
#   - Roman numeral followed by dot then capital: `II.Legal` → `II. Legal`
#   - Single letter followed by dot then capital:  `B.Article` → `B. Article`
RE_SECTION_FIX_ROMAN  = re.compile(r'\b([IVXLCM]+)\.([A-Z])')
RE_SECTION_FIX_LETTER = re.compile(r'\b([A-Z])\.([A-Z])')


def fix_section_header(s: str) -> str:
    """Insert a space after Roman/letter prefix dots in a section title."""
    s2 = RE_SECTION_FIX_ROMAN.sub(r'\1. \2', s)
    s2 = RE_SECTION_FIX_LETTER.sub(r'\1. \2', s2)
    return s2


# ────────────────────────────  Drivers  ────────────────────────────

def patch_metadata(documents: list, *, dry_run: bool) -> int:
    n = 0
    for d in documents:
        fix = METADATA_FIXES.get(d.get("docId"))
        if not fix: continue
        for k, v in fix.items():
            old = d.get(k)
            if old != v:
                if dry_run:
                    print(f"  [meta] {d['docId']} · {k}: {old!r} → {v!r}")
                else:
                    d[k] = v
                n += 1
    return n


def patch_corpus(corpus: list, *, dry_run: bool) -> dict:
    cnt = {"stray_digits": 0, "sections": 0, "paragraphs_touched": 0}
    sample = []
    for p in corpus:
        if p.get("type", "gc") != "gc": continue
        before_text = p.get("text", "")
        new_text, sd = fix_stray_digits(before_text)
        if new_text != before_text:
            cnt["stray_digits"] += sd
            cnt["paragraphs_touched"] += 1
            if len(sample) < 5:
                # Find the first changed region for the sample
                idx = next(
                    (i for i in range(min(len(before_text), len(new_text)))
                     if before_text[i] != new_text[i]),
                    0,
                )
                sample.append({
                    "id": p.get("id"),
                    "before": before_text[max(0, idx - 30):idx + 50],
                    "after":  new_text[max(0, idx - 30):idx + 50],
                })
        if not dry_run:
            p["text"] = new_text

        # Section-path fix
        sect = p.get("section")
        if isinstance(sect, list):
            new_sect = [fix_section_header(s) for s in sect]
            if new_sect != sect:
                cnt["sections"] += sum(1 for a, b in zip(sect, new_sect) if a != b)
                if not dry_run:
                    p["section"] = new_sect
        elif isinstance(sect, str):
            new_s = fix_section_header(sect)
            if new_s != sect:
                cnt["sections"] += 1
                if not dry_run:
                    p["section"] = new_s

    return {"counts": cnt, "samples": sample}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--corpus",    type=Path, required=True)
    ap.add_argument("--documents", type=Path, required=True)
    ap.add_argument("--inplace",   action="store_true")
    ap.add_argument("--dry-run",   action="store_true")
    args = ap.parse_args()

    if not args.dry_run and not args.inplace:
        ap.error("--inplace or --dry-run required")

    corpus    = json.loads(args.corpus.read_text(encoding="utf-8"))
    documents = json.loads(args.documents.read_text(encoding="utf-8"))

    n_meta = patch_metadata(documents, dry_run=args.dry_run)
    print(f"[Cat-C metadata] {n_meta} field(s) updated")

    out = patch_corpus(corpus, dry_run=args.dry_run)
    cnt = out["counts"]
    print(f"[Cat-D stray digits] {cnt['stray_digits']} stripped "
          f"({cnt['paragraphs_touched']} ¶ touched)")
    for s in out["samples"]:
        print(f"  {s['id']}: ...{s['before']!r}... → ...{s['after']!r}...")
    print(f"[Cat-E section spaces] {cnt['sections']} fixed across all paragraphs")

    if not args.dry_run:
        args.corpus.write_text(
            json.dumps(corpus, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        args.documents.write_text(
            json.dumps(documents, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"\nwrote {args.corpus}")
        print(f"wrote {args.documents}")


if __name__ == "__main__":
    main()
