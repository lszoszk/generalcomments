#!/usr/bin/env python3
"""
Re-split the 40 under-extracted General Comment / General Recommendation
docs in docs/corpus.json.

Background
----------
Audit found 40 GC documents with ≤3 paragraphs total — entire document
text squashed into 1-2 flat paragraphs (sometimes the same text
duplicated as both `isPreamble=true` and `¶1`). Affects:
  - 19 CEDAW GRs (GR2-GR21, with GR19 being a structural outlier)
  - 11 CERD GRs (early ones from the `a-XX-18` series + `annotated-cerd-*`)
  -  1 CCPR GC1
  -  4 HRI compilation entries
  - plus a-37-18 / a-45-81 etc.

Strategy
--------
Most of these flat paragraphs ALREADY contain the structure — gerund
clauses for the preamble ("Bearing in mind…", "Recalling…", "Affirming…"),
followed by an operative verb ("Recommends that States parties:",
"Decides…", "Calls upon…"), followed by lettered items "(a)…(b)…(c)…".

We split using:
  1. If the text has explicit `\n` newlines (some `a-XX-18` docs do),
     each non-empty line is a candidate segment.
  2. Otherwise, find the operative-verb boundary (", Recommends",
     ", Decides", etc.) and split there. Anything before the verb +
     the verb's lead-in (up to the colon) becomes the preamble; the
     post-colon text is the body.
  3. The body, if it has lettered items "(a) … (b) … (c) …", splits
     into one paragraph per item.

Pure-prose docs with no operative-verb anchor + no newlines stay as a
SINGLE paragraph (no `isPreamble`) — the duplicate-isPreamble + ¶1
copy is collapsed.

GR19 (annotated-cedaw-gr19-violence) is intentionally LEFT ALONE on
the user's instruction — the user confirmed GR19 has no preamble.

Run
----
    python3 _docs_internal/resplit_gc_paragraphs.py            # dry-run summary
    python3 _docs_internal/resplit_gc_paragraphs.py --apply    # write
    python3 _docs_internal/resplit_gc_paragraphs.py --apply --doc <docId>
        # apply to a single doc only (useful for spot-checking)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "docs" / "corpus.json"

# Docs to re-split. List from audit. Excludes annotated-cedaw-gr19-violence
# per user instruction (no preamble; current 24-paragraph split is fine).
TARGETS: set[str] = {
    # CEDAW GRs (19 docs, GR2-GR21 except GR19)
    "annotated-cedaw-gr2-reporting",
    "annotated-cedaw-gr3-campaigns-edu",
    "annotated-cedaw-gr4-reservations",
    "annotated-cedaw-gr5-tsm1",
    "annotated-cedaw-gr6-national-machinery",
    "annotated-cedaw-gr7-resources",
    "annotated-cedaw-gr8-art-8",
    "annotated-cedaw-gr9-statisticaldata",
    "annotated-cedaw-gr10-tenth-anniversary",
    "annotated-cedaw-gr11-technical-advisory-services",
    "annotated-cedaw-gr12-vaw",
    "annotated-cedaw-gr13-remuneration",
    "annotated-cedaw-gr14-circumcision",
    "annotated-cedaw-gr15-aids",
    "annotated-cedaw-gr16-unpaid-women-workers",
    "annotated-cedaw-gr17-measurement",
    "annotated-cedaw-gr18-disabled",
    "annotated-cedaw-gr20-reservations",
    # CERD annotated GRs
    "annotated-cerd-gr1-obligations-art-4",
    "annotated-cerd-gr2-obligations",
    "annotated-cerd-gr3-reporting",
    "annotated-cerd-gr11-non-citizens",
    "annotated-cerd-gr13-training",
    "annotated-cerd-gr14-non-discrimination",
    "annotated-cerd-gr22-refugee",
    "annotated-cerd-gr26-article6",
    # CERD a-XX-18 series (annual report-style entries)
    "a-32-18",
    "a-37-18",
    "a-40-18",
    "a-45-18",
    "a-45-81",
    "a-46-18",
    "a-49-18",
    "a-90-18",
    "a-41-38",  # CEDAW
    # CCPR GC1
    "annotated-ccpr-gc1-reporting-obligation",
    # HRI compilation entries (CCPR GC3-GC6)
    "hri-gen-1-rev-9-vol-i-p-174",
    "hri-gen-1-rev-9-vol-i-p-176",
    "hri-gen-1-rev-9-vol-i-p-178",
    "hri-gen-1-rev-9-vol-i-p-182",
}

# Operative-verb anchor — typically preceded by ", " in a flat-text doc
# and followed by an object phrase + ":" introducing a list of items.
# Matched only when capitalised at the start of a clause (after ", ").
OPERATIVE_RE = re.compile(
    r",\s+("
    r"Recommends|Decides|Adopts|Calls upon|Urges|Requests|Invites|"
    r"Considers|Reaffirms|Reminds|Welcomes|Notes|Declares|Expresses|"
    r"Encourages"
    r")\b"
)

# Lettered or roman-numeral list-item marker, with optional whitespace.
# Look-ahead `(?=[A-Z"“])` distinguishes a true list item ("(a) Encourage…")
# from an inline article reference ("article 4 (a) and (b) of the Convention").
# Real list items always start with a capital letter or an opening quote;
# inline references are followed by lowercase ("and", "of"), a numeral, or
# punctuation. This single check eliminates the GR1-style false-positive
# without losing any real list-item match.
ITEM_RE = re.compile(r"\(\s*([a-z]{1,3}|[ivxIVX]{1,4})\s*\)\s+(?=[A-Z\"“])")

# Top-level numbered item: "1. " / "2. " etc., either at the start of
# the body OR following one of the typical end-of-clause punctuators
# (";", "."). Look-ahead requires a capital letter to avoid matching
# "article 18.", "ratio 3.5", etc. The captured `(\d+)` is sequence-
# checked at split time so a stray inline number ("decision 3.") doesn't
# anchor a split unless the surrounding sequence is plausible (1, 2, 3…).
NUM_ITEM_RE = re.compile(
    r"(?:(?<=^)|(?<=[\s;.]))(\d{1,2})\.\s+(?=[A-Z])"
)


def split_text(text: str) -> list[tuple[str, bool]]:
    """Return list of (text, is_preamble). Empty list = "leave alone"."""
    text = (text or "").strip()
    if not text:
        return []

    # Strategy 1: explicit newlines (≥2 of them)
    if text.count("\n") >= 2:
        segs = [s.strip() for s in text.split("\n") if s.strip()]
        return _categorise_segments(segs)

    # Strategy 2: find operative-verb anchor
    m = OPERATIVE_RE.search(text)
    if m:
        # Preamble = text up to the operative
        pre = text[: m.start()].strip().rstrip(",").strip()
        operative_block = text[m.start() + 2 :].strip()  # drop the leading ", "
        # Find ":" within the operative block (the lead-in to items)
        colon_idx = operative_block.find(":")
        if colon_idx > 0 and colon_idx < 200:
            # preamble + lead-in
            preamble_full = (pre + ", " + operative_block[: colon_idx + 1]).strip()
            items_block = operative_block[colon_idx + 1 :].strip()
            return [(preamble_full, True)] + _split_items(items_block)
        # No colon: preamble + body as 2 paras (preamble flag on first)
        return [(pre, True), (operative_block, False)]

    # Strategy 3: numbered-item fallback for docs whose operative
    # verbs ARE the numbered items themselves (CERD-style: "The
    # Committee… Alarmed by …, Convinced …, 1. Considers …,
    # 2. Urges …, 3. Requests …" — no separate "Recommends:" lead).
    # Treat everything before the first plausible "1." as the
    # preamble.
    num_matches = list(NUM_ITEM_RE.finditer(text))
    nums = [int(m.group(1)) for m in num_matches]
    if len(num_matches) >= 2 and _is_plausible_sequence(nums):
        head = text[: num_matches[0].start()].strip().rstrip(",").rstrip(":").strip()
        out = []
        if head:
            out.append((head, True))
        for i, mm in enumerate(num_matches):
            end = num_matches[i + 1].start() if i + 1 < len(num_matches) else len(text)
            piece = text[mm.start():end].strip()
            if piece:
                out.append((piece, False))
        return out

    # Strategy 4: lettered-item fallback. Some docs use past-tense or
    # otherwise-unmatched operative wording ("The Committee recommended
    # that … States parties should: (a) … (b) …"), so we still want to
    # split on the items. Treat everything before the first item as
    # preamble (even though it lacks the canonical structure).
    item_matches = list(ITEM_RE.finditer(text))
    if len(item_matches) >= 2:
        head = text[: item_matches[0].start()].strip().rstrip(",").rstrip(":").strip() + ":"
        items = []
        for i, mm in enumerate(item_matches):
            end = item_matches[i + 1].start() if i + 1 < len(item_matches) else len(text)
            piece = text[mm.start():end].strip()
            if piece:
                items.append((piece, False))
        return [(head, True)] + items

    # Strategy 4: pure prose, no anchor — single paragraph.
    # If it starts with "The Committee" / a gerund, mark as preamble
    # (for the CEDAW GR3-style preamble-only docs); otherwise leave flag off.
    low = text.lstrip(",").strip().lower()
    if low.startswith(("the committee", "bearing in mind", "recalling",
                       "considering", "noting", "affirming", "reaffirming",
                       "having")):
        return [(text, True)]
    return [(text, False)]


def _split_items(items_text: str) -> list[tuple[str, bool]]:
    """Split the body text into item paragraphs.

    NUMBERED items (1., 2., 3., …) take precedence over lettered ones
    when present, because UN docs nest lettered items as SUB-items of
    numbered ones (e.g. CEDAW GR6: "1. Establish … to: (a) Advise…;
    (b) Monitor…; (c) Help formulate…; 2. Take …"). Splitting on the
    lettered markers shreds item 1 across three "paragraphs" and
    buries items 2-4 inside item (c).

    A numbered split only fires when the captured numbers form a
    plausible sequence (1, 2, 3, …). Lone matches or wild jumps fall
    through to the lettered path.
    """
    items_text = items_text.strip()
    if not items_text:
        return []

    # Numbered first — but only if the sequence is sane.
    num_matches = list(NUM_ITEM_RE.finditer(items_text))
    nums = [int(m.group(1)) for m in num_matches]
    if len(num_matches) >= 2 and _is_plausible_sequence(nums):
        out = []
        head = items_text[: num_matches[0].start()].strip()
        if head:
            out.append((head, False))
        for i, m in enumerate(num_matches):
            end = num_matches[i + 1].start() if i + 1 < len(num_matches) else len(items_text)
            piece = items_text[m.start():end].strip()
            if piece:
                out.append((piece, False))
        return out

    # Lettered items
    matches = list(ITEM_RE.finditer(items_text))
    if matches:
        out = []
        head = items_text[: matches[0].start()].strip()
        if head:
            out.append((head, False))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(items_text)
            piece = items_text[m.start():end].strip()
            if piece:
                out.append((piece, False))
        return out

    # No structured items: keep the whole body as one paragraph
    return [(items_text, False)]


def _is_plausible_sequence(nums: list[int]) -> bool:
    """True if `nums` looks like a real list outline (1, 2, 3, …): starts
    with 1 or 2, every step is +1 or +0 (allowing repeats from inline
    references that slipped past the regex), max value bounded so an
    inline citation like "decision 17." can't anchor a wrong split."""
    if not nums or max(nums) > 30 or nums[0] not in (1, 2):
        return False
    prev = nums[0]
    for n in nums[1:]:
        if n - prev not in (0, 1):
            return False
        prev = n
    return True


def _categorise_segments(segs: list[str]) -> list[tuple[str, bool]]:
    """For docs with newline-separated segments: identify which are preamble
    (gerund-leading) vs body (operative-verb-leading)."""
    GERUNDS = (
        "the committee", "bearing in mind", "recalling", "affirming",
        "considering", "noting", "aware", "concerned", "convinced",
        "observing", "mindful", "reaffirming", "taking note", "having",
        "recognizing", "recognising", "desiring", "emphasizing",
        "emphasising", "underlining", "alarmed", "deeply", "expressing",
        "guided", "guided by", "endorsing",
    )
    OPERATIVE = (
        "considers", "recommends", "urges", "calls upon", "reminds",
        "requests", "decides", "adopts", "declares", "invites",
        "welcomes", "expresses", "reaffirms", "encourages",
    )

    preamble_segs: list[str] = []
    body_segs: list[str] = []
    seen_operative = False
    for seg in segs:
        low = seg.lstrip(",").strip().lower()
        if not seen_operative:
            if low.startswith(OPERATIVE):
                seen_operative = True
                # Operative line: keep the lead-in (verb + object up to colon)
                # in the preamble. Anything after ":" goes to body.
                if ":" in seg:
                    head, tail = seg.split(":", 1)
                    preamble_segs.append(head.strip() + ":")
                    if tail.strip():
                        # If tail is a lettered/numbered item, peel it out;
                        # otherwise keep as one body segment.
                        body_segs.extend(s for s, _ in _split_items(tail.strip()))
                else:
                    body_segs.append(seg)
            else:
                preamble_segs.append(seg)
        else:
            # In body: split lettered items if they appear inline
            sub = _split_items(seg)
            if sub:
                body_segs.extend(s for s, _ in sub)
            else:
                body_segs.append(seg)

    out: list[tuple[str, bool]] = []
    if preamble_segs:
        # Join preamble segs with ", " (matches CEDAW house style)
        joined = preamble_segs[0]
        for s in preamble_segs[1:]:
            sep = ", " if not s.startswith(",") else " "
            joined = joined.rstrip() + sep + s.lstrip()
        out.append((joined, True))
    for s in body_segs:
        if s.strip():
            out.append((s.strip(), False))
    return out


def _norm_ws(s: str) -> str:
    """Whitespace-normalised view for duplicate detection."""
    return re.sub(r"\s+", " ", (s or "")).strip()


def _is_broken(ordered: list[dict]) -> tuple[bool, dict | None]:
    """Decide whether `ordered` paragraphs are the "broken" pattern that
    needs re-splitting, and if so return the source paragraph (the one
    holding the full doc text).

    Patterns considered broken:
      - 1 paragraph total (a flat unsplit doc).
      - 2+ paragraphs where one paragraph's normalised text contains
        every other paragraph's normalised text (HF source emitted both
        a preamble and a "full doc including preamble" copy).
      - 2 paragraphs where the longer is much bigger (≥2.5x) than the
        shorter AND starts with the shorter's first 30+ chars (the HF
        source occasionally shipped a slightly-truncated preamble in
        pos=1 — characters dropped between two adjacent words — so
        strict substring matching fails. Length-ratio + prefix-match
        catches these).
      - 2+ paragraphs that are exact duplicates after normalisation.

    Distinct multi-paragraph docs (a-32-18: "Requests…" + "Invites…",
    a-46-18: 3 distinct operative paragraphs, etc.) are LEFT ALONE.
    """
    if not ordered:
        return False, None
    if len(ordered) == 1:
        return True, ordered[0]
    norm_texts = [_norm_ws(p.get("text", "")) for p in ordered]
    n = len(ordered)
    # Find a paragraph that contains every other paragraph's text.
    for i in range(n):
        if all(
            norm_texts[i] == norm_texts[j] or norm_texts[j] in norm_texts[i]
            for j in range(n) if j != i
        ):
            return True, ordered[i]
    # 2-paragraph length-ratio heuristic with prefix match
    if n == 2:
        ts = sorted(zip(norm_texts, ordered), key=lambda x: len(x[0]))
        short, longer = ts[0], ts[1]
        if (len(short[0]) >= 30 and len(longer[0]) >= 2.5 * len(short[0])
                and longer[0].startswith(short[0][:30])):
            return True, longer[1]
    # All-pairs equal? (rare degenerate case)
    if len(set(norm_texts)) == 1:
        return True, max(ordered, key=lambda p: len((p.get("text") or "")))
    return False, None


def rebuild_paragraphs(doc_id: str, original: list[dict]) -> list[dict]:
    """Build a fresh list of paragraph records for the doc.

    Three behaviours:
      1. The doc is "broken" (1 paragraph, or one paragraph contains
         all others) — re-split the dominant paragraph using split_text.
      2. The doc has multiple distinct paragraphs but at least ONE of
         them packs an operative-verb + lettered/numbered list inline
         ("…recommended that … should: (a)… (b)… (c)…") — split THAT
         paragraph with _split_items, leave the others alone.
      3. Otherwise — return as-is.
    """
    if not original:
        return []
    ordered = sorted(original, key=lambda p: p.get("idx") or p.get("n") or 0)
    broken, source = _is_broken(ordered)
    if broken:
        template = {
            k: v for k, v in source.items()
            if k not in ("id", "n", "idx", "text", "isPreamble")
        }
        splits = split_text(source.get("text", ""))
        return _materialise(doc_id, template, splits)

    # Per-paragraph fallback: split any paragraph that has a clear
    # ":(a) …(b) …(c) …" or ": 1. … 2. …" inline list — but ONLY when
    # the paragraph itself isn't already a numbered top-level item.
    # Skip paragraphs starting with "N." (those are already split-as-a-
    # numbered-item; their lettered sub-items must stay inline). This
    # also keeps the script idempotent: a second pass over already-fixed
    # data is a no-op.
    NUM_PREFIX_RE = re.compile(r"^\d{1,2}\.\s+[A-Z]")
    expanded: list[tuple[str, bool]] = []
    changed = False
    for p in ordered:
        text = (p.get("text") or "").strip()
        is_pre = p.get("isPreamble") is True
        if NUM_PREFIX_RE.match(text):
            expanded.append((text, is_pre))
            continue
        if (": (a)" in text or ": (i)" in text or ":(a)" in text
                or re.search(r":\s*1\.\s+[A-Z]", text)):
            sub = split_text(text)
            if len(sub) > 1:
                expanded.extend(sub)
                changed = True
                continue
        expanded.append((text, is_pre))
    if not changed:
        return original
    template = {
        k: v for k, v in ordered[0].items()
        if k not in ("id", "n", "idx", "text", "isPreamble")
    }
    return _materialise(doc_id, template, expanded)


def _materialise(doc_id: str, template: dict, splits: list[tuple[str, bool]]) -> list[dict]:
    """Build paragraph records from (text, is_preamble) tuples."""
    out: list[dict] = []
    for i, (text, is_pre) in enumerate(splits, start=1):
        rec = dict(template)
        # Stable id scheme: <docId>-<NNNN>, 1-indexed.
        rec["id"] = f"{doc_id}-{i:04d}"
        rec["n"] = 0 if is_pre else i - sum(1 for x in out if x.get("isPreamble"))
        rec["idx"] = i
        rec["text"] = text
        if is_pre:
            rec["isPreamble"] = True
        else:
            # Drop the field entirely when False — matches the convention
            # in the rest of the corpus (only preamble paragraphs carry the flag).
            rec.pop("isPreamble", None)
        out.append(rec)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="Write changes back to disk.")
    ap.add_argument("--doc", help="Limit to a single docId (for spot-checking).")
    args = ap.parse_args()

    print(f"Re-splitting under-extracted GC docs in {CORPUS.relative_to(REPO)}")
    print(f"  mode: {'APPLY' if args.apply else 'dry-run'}")
    if args.doc:
        print(f"  scope: only {args.doc}")
    print()

    with CORPUS.open() as f:
        corpus = json.load(f)

    target_set = {args.doc} if args.doc else TARGETS
    by_doc: dict[str, list[dict]] = {}
    other: list[dict] = []
    for p in corpus:
        if p.get("docId") in target_set:
            by_doc.setdefault(p["docId"], []).append(p)
        else:
            other.append(p)

    summary = []
    rebuilt: list[dict] = []
    for doc_id in sorted(by_doc):
        before = by_doc[doc_id]
        after = rebuild_paragraphs(doc_id, before)
        summary.append((doc_id, len(before), len(after)))
        rebuilt.extend(after)

    print(f"  {'docId':<54s}  before  after")
    for d, b, a in summary:
        print(f"  {d:<54s}  {b:>6d}  {a:>5d}")
    print()
    print(f"  Total: {len(by_doc)} docs · {sum(b for _, b, _ in summary)} → {sum(a for _, _, a in summary)} paragraphs")

    if args.apply:
        # Preserve original ordering — concatenate `other` (unchanged) + rebuilt.
        # The frontend doesn't depend on physical ordering within corpus.json
        # (it sorts by docId + idx), so this is safe.
        new_corpus = other + rebuilt
        with CORPUS.open("w") as f:
            json.dump(new_corpus, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        print(f"\n  ✅ wrote {len(new_corpus):,} paragraphs to {CORPUS.relative_to(REPO)}")
    else:
        print("\n  Re-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
