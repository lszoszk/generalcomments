#!/usr/bin/env python3
"""Rebuild Special Procedures paragraph text, footnotes and headings from the DOCX.

The SP corpus was cut out of PDFs with PyMuPDF, and three kinds of damage
followed it into the reader (A/HRC/58/58 shows all three):

  1. Unnumbered blocks between two numbered paragraphs were dropped — block
     quotes, list items after a colon — so ¶1 ends "…notes that:" and the quote
     it introduces is gone.
  2. Headings that wrap onto a second line were stored as their first line
     ("A. Human Rights Council resolution 51/3 on neurotechnology and human"),
     unnumbered sub-headings ("Human dignity") were lost, and whole levels
     went missing (section IV of A/HRC/58/58).
  3. Footnote numbers were flattened into the prose ("Advisory Committee4
     concluded") or stripped, and their text never attached.

UN Documents serves the same reports as Word files, where all of this is
structure: heading styles (HChG / H1G / H23G …), numbered paragraphs typed as
"N.<tab>", and w:footnoteReference at the exact position of every note. This
script rebuilds each corpus paragraph from the DOCX paragraph with the same
number, together with the unnumbered blocks that follow it up to the next
numbered paragraph or heading (a table or box in between stays with it, one
line per row). Blocks are joined with "\\n", which the reader honours
(white-space: pre-line), so list items and quotes sit on their own lines.

id-stable: paragraph id / idx / n, labels and every other enrichment stay as
they are; only `text`, `footnotes` and `section` change. A paragraph is
rebuilt only when the DOCX paragraph contains its text (word-trigram
coverage ≥ --min-coverage, not counting headings and note text the PDF ran
into it), when no prose the corpus had would disappear from the report, and
when no paragraph left as it is carries the same text.

Dry run by default; --apply rewrites the shards, stamps `textSource` on the
document records, refreshes wordCount and re-hashes both manifests.

    python3 sp_rebuild_from_docx.py --doc a-hrc-58-58 --show
    python3 sp_rebuild_from_docx.py --workers 4 --apply
"""
from __future__ import annotations

import argparse
import difflib
import glob
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from sp_footnotes_from_docx import fetch_docx, docx_text

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
W_NS = {"w": W[1:-1]}
SOURCE = "documents.un.org docx"

# Heading styles of the UN templates (G = Geneva, bare = New York), plus Word's
# built-ins, mapped to nesting depth.
HEAD_LEVEL = {
    "HChG": 0, "HCh": 0, "HCh0": 0, "Heading1": 0,
    "H1G": 1, "H1": 1, "Heading2": 1,
    "H23G": 2, "H23": 2, "Heading3": 2,
    "H4G": 3, "H4": 3, "Heading4": 3,
    "H56G": 4, "H56": 4, "Heading5": 4,
}
NUMBERED = re.compile(r"^(\d{1,3})\.\s")
NOTE_LINE = re.compile(r"^(\d{1,3})\s+\S")
NOTES_START = re.compile(r"^(?:[_\-–—]{5,}|\*(?:\s*\*){2,}|Notes|NOTES|Endnotes)\s*$")
MARKER = re.compile(r"\[\[fn:\d+\]\]")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ─────────── DOCX → blocks ───────────
def _notes(z: ZipFile):
    """{id: text} of the notes part and the tag of its references. Where most
    notes open with their own mark glyph (a symbol-font mark that survives as
    "?" or "*"), that glyph is a document convention and is stripped."""
    names = z.namelist()
    if "word/footnotes.xml" in names:
        part, tag, ref = "word/footnotes.xml", "w:footnote", f"{W}footnoteReference"
    elif "word/endnotes.xml" in names:
        part, tag, ref = "word/endnotes.xml", "w:endnote", f"{W}endnoteReference"
    else:
        return {}, None
    by_id = {}
    for fn in ET.fromstring(z.read(part)).findall(tag, W_NS):
        try:
            fid = int(fn.attrib.get(f"{W}id"))
        except (TypeError, ValueError):
            continue
        if fid >= 1:
            by_id[fid] = re.sub(r"\s+", " ", " ".join(docx_text(p) for p in fn.findall("w:p", W_NS))).strip()
    glyph = re.compile(r"^[?*†‡]+\s*")
    convention = bool(by_id) and sum(1 for t in by_id.values() if glyph.match(t)) / len(by_id) > 0.5
    if convention:
        by_id = {k: glyph.sub("", t) for k, t in by_id.items()}
    return by_id, ref


def _restarts(z: ZipFile, body) -> tuple[list, bool]:
    """Section boundaries (paragraph elements that close a section) and, per
    section, whether note numbering restarts there."""
    default = False
    if "word/settings.xml" in z.namelist():
        s = ET.fromstring(z.read("word/settings.xml"))
        r = s.find(f"{W}footnotePr/{W}numRestart")
        default = r is not None and r.attrib.get(f"{W}val") == "eachSect"
    bounds, flags = [], []
    for p in body.iter(f"{W}p"):
        sp = p.find(f"{W}pPr/{W}sectPr")
        if sp is not None:
            bounds.append(p)
            r = sp.find(f"{W}footnotePr/{W}numRestart")
            flags.append(default if r is None else r.attrib.get(f"{W}val") == "eachSect")
    final = body.find(f"{W}sectPr")
    r = final.find(f"{W}footnotePr/{W}numRestart") if final is not None else None
    flags.append(default if r is None else r.attrib.get(f"{W}val") == "eachSect")
    return bounds, flags


def _numbering(z: ZipFile):
    """Word list numbering: {numId: {ilvl: (start, numFmt, lvlText)}} and the
    (numId, ilvl) each paragraph style carries."""
    names = z.namelist()
    levels: dict[str, dict[int, tuple]] = {}

    def val(el, tag, default=None):
        node = el.find(f"{W}{tag}") if el is not None else None
        return node.attrib.get(f"{W}val", default) if node is not None else default

    if "word/numbering.xml" in names:
        root = ET.fromstring(z.read("word/numbering.xml"))
        abstract = {}
        for a in root.findall(f"{W}abstractNum"):
            abstract[a.attrib.get(f"{W}abstractNumId")] = {
                int(l.attrib.get(f"{W}ilvl", 0)): (int(val(l, "start", 1)), val(l, "numFmt", "decimal"), val(l, "lvlText", ""))
                for l in a.findall(f"{W}lvl")}
        for n in root.findall(f"{W}num"):
            lv = dict(abstract.get(val(n, "abstractNumId"), {}))
            for o in n.findall(f"{W}lvlOverride"):
                i = int(o.attrib.get(f"{W}ilvl", 0))
                if i in lv and o.find(f"{W}startOverride") is not None:
                    lv[i] = (int(val(o, "startOverride", 1)),) + lv[i][1:]
            levels[n.attrib.get(f"{W}numId")] = lv
    by_style = {}
    if "word/styles.xml" in names:
        for st in ET.fromstring(z.read("word/styles.xml")).findall(f"{W}style"):
            np_ = st.find(f"{W}pPr/{W}numPr")
            if np_ is not None and np_.find(f"{W}numId") is not None:
                by_style[st.attrib.get(f"{W}styleId")] = (val(np_, "numId"), int(val(np_, "ilvl", 0)))
    return levels, by_style


def _fmt(n: int, fmt: str) -> str:
    if fmt in ("lowerLetter", "upperLetter"):
        s = chr(ord("a") + (n - 1) % 26) * ((n - 1) // 26 + 1)
        return s if fmt == "lowerLetter" else s.upper()
    if fmt in ("lowerRoman", "upperRoman"):
        out, v = "", n
        for k, r in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
                     (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
            while v >= k:
                out, v = out + r, v - k
        return out if fmt == "lowerRoman" else out.upper()
    if fmt == "bullet":
        return "•"
    if fmt == "none":
        return ""
    return str(n)


def parse_blocks(path: Path, auto_numbers: bool = False) -> list[dict]:
    """Body paragraphs in order: {kind: head|body|table, level, text, notes}.
    Note references become [[fn:N]] with N as printed (body order, custom-mark
    notes skipped, restarting where the section says so). With auto_numbers,
    Word list numbering is written out ("12. …", "(b) …") for reports whose
    paragraph numbers are not typed."""
    with ZipFile(path) as z:
        by_id, ref_tag = _notes(z)
        body = ET.fromstring(z.read("word/document.xml")).find("w:body", W_NS)
        bounds, flags = _restarts(z, body)
        levels, by_style = _numbering(z) if auto_numbers else ({}, {})
    counters: dict[str, list] = {}
    # table paragraphs keyed by their row (inner rows win for nested tables)
    row_of = {id(p): id(tr) for tr in body.iter(f"{W}tr") for p in tr.iter(f"{W}p")}
    in_box = {id(p) for b in body.iter(f"{W}txbxContent") for p in b.iter(f"{W}p")}
    bound_ids = {id(p): i for i, p in enumerate(bounds)}
    counter, section = 0, 0
    blocks = []

    def walk(node, parts, notes):
        nonlocal counter
        for ch in node:
            tag = ch.tag
            if tag == f"{W}txbxContent" or tag.endswith("}Fallback"):
                continue
            if tag == f"{W}t":
                parts.append(ch.text or "")
            elif tag in (f"{W}tab", f"{W}br", f"{W}cr"):
                parts.append(" ")
            elif tag == f"{W}noBreakHyphen":
                parts.append("-")
            elif ref_tag and tag == ref_tag:
                try:
                    fid = int(ch.attrib.get(f"{W}id"))
                except (TypeError, ValueError):
                    continue
                if fid < 1:
                    continue
                text = by_id.get(fid, "")
                # Word numbers every note except those with a custom mark (the
                # asterisk title notes). A note whose text merely starts with
                # "*" or a stray "?" glyph still takes a number: checked
                # against the printed PDFs of A/77/514 and A/75/298.
                if ch.attrib.get(f"{W}customMarkFollows") in ("1", "true"):
                    continue
                text = re.sub(r"^\?\s+", "", text)
                counter += 1
                parts.append(f"[[fn:{counter}]]")
                notes.append((counter, text))
            else:
                walk(ch, parts, notes)

    for p in body.iter(f"{W}p"):
        if id(p) in in_box:
            continue
        parts, notes = [], []
        walk(p, parts, notes)
        text = re.sub(r"\s+", " ", "".join(parts)).strip()
        # "word.[[fn:3]]" never takes a space before the marker
        text = re.sub(r"\s+(\[\[fn:\d+\]\])", r"\1", text)
        st = p.find(f"{W}pPr/{W}pStyle")
        style = st.attrib.get(f"{W}val", "") if st is not None else ""
        if auto_numbers and text:
            text = _numbered(p, style, text, levels, by_style, counters)
        if text:
            if id(p) in row_of:
                kind = "table"
            elif style in HEAD_LEVEL and len(text) <= (150 if NUMBERED.match(text) else 300):
                # (a numbered paragraph or a block of prose left in a heading
                # style is still a paragraph)
                kind = "head"
            else:
                kind = "body"
            blocks.append({"kind": kind, "level": HEAD_LEVEL.get(style), "text": text, "notes": notes,
                           "row": row_of.get(id(p))})
        if id(p) in bound_ids:
            section = bound_ids[id(p)] + 1
            if flags[section]:
                counter = 0
    return blocks


def _numbered(p, style: str, text: str, levels: dict, by_style: dict, counters: dict) -> str:
    """Prefix a paragraph with its Word list label, advancing the counters."""
    num = by_style.get(style)
    np_ = p.find(f"{W}pPr/{W}numPr")
    if np_ is not None and np_.find(f"{W}numId") is not None:
        il = np_.find(f"{W}ilvl")
        num = (np_.find(f"{W}numId").attrib.get(f"{W}val"),
               int(il.attrib.get(f"{W}val", 0)) if il is not None else (num[1] if num else 0))
    if not num or num[0] not in levels or num[1] not in levels[num[0]]:
        return text
    nid, ilvl = num
    lv = levels[nid]
    c = counters.setdefault(nid, [0] * 9)
    c[ilvl] = c[ilvl] + 1 if c[ilvl] else lv[ilvl][0]
    for d in range(ilvl + 1, 9):
        c[d] = 0

    def part(m):
        k = int(m.group(1)) - 1
        start, fmt = lv.get(k, (1, "decimal", ""))[:2]
        return _fmt(c[k] or start, fmt)

    label = re.sub(r"%(\d)", part, lv[ilvl][2]).strip()
    # a label typed into the text as well is not repeated
    if not label or re.match(r"^\(?[0-9A-Za-z]{1,5}[.)]\s", text):
        return text
    return f"{label} {text}"


def numbered_spans(blocks: list[dict]) -> list[dict]:
    """One entry per numbered DOCX paragraph: its number, the text of the
    paragraph plus the unnumbered blocks that follow it, the notes in it and
    the heading path it sits under."""
    spans = []
    stack: list[tuple[int, str]] = []
    seen_numbered = False
    cur = None
    heads_before: list[str] = []
    for b in blocks:
        if b["kind"] == "head":
            cur = None
            label = MARKER.sub("", b["text"]).strip()
            stack = [(l, t) for l, t in stack if l < b["level"]] + [(b["level"], label)]
            heads_before.append(label)
            continue
        if b["kind"] == "table":
            # A box or table between two paragraphs stays with the one before
            # it, one line per row, as the PDF text had it.
            if cur is not None:
                if cur["row"] == b["row"]:
                    cur["parts"][-1] += " " + b["text"]
                else:
                    cur["parts"].append(b["text"])
                    cur["row"] = b["row"]
                cur["notes"].extend(b["notes"])
            continue
        m = NUMBERED.match(b["text"])
        if m:
            seen_numbered = True
            cur = {"n": int(m.group(1)), "parts": [b["text"]], "notes": list(b["notes"]),
                   "section": [t for _, t in stack], "heads": " ".join(heads_before), "row": None}
            spans.append(cur)
            heads_before = []
        elif cur is not None:
            cur["parts"].append(b["text"])
            cur["notes"].extend(b["notes"])
            cur["row"] = None
        elif not seen_numbered:
            # Title page and summary: headings above them are not sections.
            stack = []
    for s in spans:
        parts = s.pop("parts")
        del s["row"]
        # Older reports type their endnotes as plain paragraphs after the
        # last one ("34 General Assembly resolution 34/169, annex."), set
        # off by a rule or a "Notes" line: they are not part of it.
        for i, line in enumerate(parts[1:], 1):
            a, b = NOTE_LINE.match(line), NOTE_LINE.match(parts[i + 1]) if i + 1 < len(parts) else None
            if NOTES_START.match(line) or (a and b and int(b.group(1)) == int(a.group(1)) + 1):
                parts = parts[:i]
                break
        s["text"] = "\n".join(parts)
    return spans


# ─────────── alignment ───────────
def words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", MARKER.sub(" ", text).lower())


def shingles(text: str) -> set:
    w = words(text)
    return set(zip(w, w[1:], w[2:])) if len(w) >= 3 else set(w)


def coverage(old: set, new: set) -> float:
    return len(old & new) / len(old) if old else 0.0


def lost_words(old: str, new: str, kept: set) -> int:
    """Words of `old` missing from `new` whose trigrams are not in `kept`,
    counted over runs longer than three words (shorter ones are glued note
    numbers, hyphenation and page furniture)."""
    a, b = words(old), words(new)
    if a == b:
        return 0
    lost = 0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op not in ("delete", "replace") or i2 - i1 <= 3:
            continue
        run = a[i1:i2]
        if "".join(run) == "".join(b[j1:j2]):
            continue
        sh = set(zip(run, run[1:], run[2:]))
        # Two trigrams straddle each seam where the PDF glued a heading or
        # a note onto prose, so a couple of unmatched ones are expected.
        if len(sh - kept) > max(2, 0.2 * len(sh)):
            lost += len(run)
    return lost


def rebuild_doc(paras: list[dict], spans: list[dict], min_cov: float):
    """Return ({para id: (text, footnotes)}, {para id: section}, stats), or
    (None, None, stats) when no paragraph of the report can be rebuilt."""
    ordered = sorted(paras, key=lambda q: q["idx"])
    span_sh = [shingles(s["text"]) for s in spans]
    stats = {"paras": len(ordered), "spans": len(spans), "matched": 0, "changed": 0, "reason": ""}
    # Text the PDF extraction ran into a paragraph that is not prose of it:
    # headings (they become `section`) and note text (it becomes a footnote).
    # It may leave the paragraph, so it does not count against the match.
    gone_ok = set()
    for s in spans:
        gone_ok |= shingles(s["heads"])     # consecutive headings, as glued
        for t in s["section"]:
            gone_ok |= shingles(t)
        for _, note in s["notes"]:
            gone_ok |= shingles(note)

    matched: dict[int, int] = {}            # position in ordered -> span index
    j = 0
    for i, q in enumerate(ordered):
        old = shingles(q["text"]) - gone_ok
        best, best_k = 0.0, None
        for k in range(j, min(len(spans), j + 60)):
            if spans[k]["n"] != q["n"]:
                continue
            c = coverage(old, span_sh[k])
            if c > best:
                best, best_k = c, k
        if best_k is not None and best >= min_cov:
            matched[i] = best_k
            j = best_k + 1

    new_text = {}
    for i, k in matched.items():
        q = ordered[i]
        s = spans[k]
        text = s["text"]
        # Most reports store the paragraph without its "N. " (the reader
        # prints ¶N beside it); keep whichever form the report already uses.
        if not re.match(rf"{q['n']}\.\s", q["text"]):
            text = NUMBERED.sub("", text, count=1)
        present = {int(x) for x in re.findall(r"\[\[fn:(\d+)\]\]", text)}
        fns, seen = [], set()
        for n, note in s["notes"]:
            if n in present and n not in seen and note:
                fns.append({"n": n, "text": note})
                seen.add(n)
        new_text[q["id"]] = (text, fns)

    def drop(i):
        del new_text[ordered[i]["id"]]
        del matched[i]

    # 1. Prose the corpus had must survive. A run of words that leaves a
    #    paragraph is fine when it lives on elsewhere in the rebuilt report
    #    (the PDF sometimes ran the next paragraph's first line in) or is
    #    heading / note text; otherwise that paragraph keeps its old text.
    kept = set(gone_ok)
    for i, q in enumerate(ordered):
        kept |= shingles(new_text[q["id"]][0]) if i in matched else shingles(q["text"])
    stats["kept_lossy"] = 0
    for i in list(matched):
        q = ordered[i]
        if lost_words(q["text"], new_text[q["id"]][0], kept) > 3:
            drop(i)
            stats["kept_lossy"] += 1
    # 2. A paragraph that keeps its old text must not also turn up inside a
    #    rebuilt neighbour (the PDF sometimes split a DOCX paragraph in two),
    #    or the reader would print it twice.
    stats["kept_dup"] = 0
    changed = True
    while changed:
        changed = False
        for i, q in enumerate(ordered):
            if i in matched:
                continue
            old = shingles(q["text"]) - gone_ok
            if len(old) < 5:
                continue
            for pi in [p for p in matched if abs(p - i) <= 3]:
                if coverage(old, span_sh[matched[pi]]) >= 0.6:
                    drop(pi)
                    stats["kept_dup"] += 1
                    changed = True
    stats["matched"] = len(matched)
    if not matched:
        stats["reason"] = "no paragraph aligned"
        return None, None, stats

    # Too few paragraphs found in the DOCX: headings could not be placed
    # reliably, so the report stays as it is.
    if len(matched) < 0.8 * len(ordered):
        stats["reason"] = "under 80% of paragraphs aligned"
        return None, None, stats

    # Sections: an aligned paragraph takes the heading path of its DOCX
    # paragraph; one that is not aligned takes that of the DOCX paragraph it
    # resembles most between its aligned neighbours, else the one before.
    sections = {}
    if any(s["section"] for s in spans):
        pos = sorted(matched)
        last = spans[matched[pos[0]]]["section"]
        for i, q in enumerate(ordered):
            if i in matched:
                last = spans[matched[i]]["section"]
                sections[q["id"]] = list(last)
                continue
            lo = max((matched[p] for p in pos if p < i), default=-1)
            hi = min((matched[p] for p in pos if p > i), default=len(spans))
            old = shingles(q["text"]) - gone_ok
            best, best_k = 0.3, None
            for k in range(lo + 1, hi):
                c = coverage(old, span_sh[k])
                if c > best:
                    best, best_k = c, k
            sections[q["id"]] = list(spans[best_k]["section"] if best_k is not None else last)
    stats["changed"] = sum(1 for q in ordered if q["id"] in new_text and new_text[q["id"]][0] != q["text"])
    return new_text, sections, stats


def strip_glued_heading(text: str, headings: list[str]) -> str:
    """Cut a heading the PDF extraction glued onto the tail of a paragraph
    that was not rebuilt, now that the heading lives in `section`."""
    tail = re.search(r"\s((?:[IVXL]{1,5}|[A-Z]|\d{1,2})\.\s+[A-Z][^.:]{3,300})$", text)
    if not tail:
        return text
    got = "".join(words(tail.group(1)))
    for h in headings:
        if got and got == "".join(words(h)):
            return text[: tail.start()].rstrip()
    return text


# ─────────── main ───────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", action="append", help="docId(s) to process (default: every SP report)")
    ap.add_argument("--cache", default=str(ROOT / "sp_docx_cache"))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--min-coverage", type=float, default=0.85)
    ap.add_argument("--show", action="store_true", help="print old/new text of every changed paragraph")
    ap.add_argument("--report", help="write per-report stats as JSON lines to this path")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)

    documents = load(DOCS / "documents.json")
    sp_docs = {d["docId"]: d for d in documents if d.get("type") == "sp"}
    shards, paras_by_doc = {}, {}
    for path in sorted(glob.glob(str(DOCS / "sp" / "shards" / "*.json"))):
        data = load(Path(path))
        shards[path] = data
        for q in data:
            paras_by_doc.setdefault(q["docId"], []).append(q)
    targets = sorted(d for d in (args.doc or sp_docs) if d in sp_docs and d in paras_by_doc)
    print(f"[sp-rebuild] {len(targets)} report(s) · cache {cache}")

    def work(doc_id):
        symbol = sp_docs[doc_id].get("signature") or sp_docs[doc_id].get("symbol")
        path = fetch_docx(symbol, cache)
        if not path:
            return doc_id, None, None, {"reason": "no docx"}
        try:
            spans = numbered_spans(parse_blocks(path))
            if len(spans) < 3:
                # paragraph numbers are Word list numbering, not typed
                spans = numbered_spans(parse_blocks(path, auto_numbers=True))
        except (BadZipFile, ET.ParseError, KeyError) as e:
            return doc_id, None, None, {"reason": f"unreadable docx ({type(e).__name__})"}
        if len(spans) < 3:
            return doc_id, None, None, {"reason": "no numbered paragraphs in the docx"}
        return (doc_id, *rebuild_doc(paras_by_doc[doc_id], spans, args.min_coverage))

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for doc_id, new_text, sections, stats in ex.map(work, targets):
            results.append((doc_id, new_text, sections, stats))

    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            for doc_id, _, _, st in results:
                fh.write(json.dumps({"docId": doc_id, **st}) + "\n")
    ok = [r for r in results if r[1] is not None]
    skipped: dict = {}
    for _, nt, _, st in results:
        if nt is None:
            key = re.sub(r"[\d.]+%|\d+", "#", st["reason"])
            skipped[key] = skipped.get(key, 0) + 1
    tot = sum(r[3]["paras"] for r in ok)
    matched = sum(r[3]["matched"] for r in ok)
    changed = sum(r[3]["changed"] for r in ok)
    print(f"[sp-rebuild] rebuilt {len(ok)}/{len(results)} reports · paragraphs aligned {matched}/{tot} · text changed {changed}")
    if skipped:
        print(f"[sp-rebuild] left untouched: {dict(sorted(skipped.items(), key=lambda kv: -kv[1]))}")
    if args.doc:
        for doc_id, _, _, st in results:
            print(f"  {doc_id}: {st}")

    # Apply the edits to the in-memory shards.
    touched = set()
    for doc_id, new_text, sections, _ in ok:
        heads = sorted({h for sec in sections.values() for h in sec}, key=len, reverse=True) if sections else []
        for q in sorted(paras_by_doc[doc_id], key=lambda q: q["idx"]):
            before = (q["text"], q.get("footnotes"), q.get("section"))
            if q["id"] in new_text:
                q["text"], fns = new_text[q["id"]]
                q["footnotes"] = fns
            elif heads:
                q["text"] = strip_glued_heading(q["text"], heads)
            if sections:
                q["section"] = sections[q["id"]]
            if args.show and before[0] != q["text"]:
                print(f"\n--- {q['id']} ¶{q['n']}  {' › '.join(q.get('section') or [])}\nOLD: {before[0]}\nNEW: {q['text']}\nFN : {[f['n'] for f in q.get('footnotes') or []]}")
            if before != (q["text"], q.get("footnotes"), q.get("section")):
                touched.add(doc_id)
    print(f"[sp-rebuild] {len(touched)} report(s) would change")
    if not args.apply:
        print("[sp-rebuild] dry run — nothing written (use --apply)")
        return

    for path, data in shards.items():
        if any(q["docId"] in touched for q in data):
            Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for d in documents:
        if d["docId"] in touched:
            d["textSource"] = SOURCE
            d["footnotesSource"] = SOURCE
            d["wordCount"] = sum(len(MARKER.sub("", q["text"]).split()) for q in paras_by_doc[d["docId"]])
    raw = (DOCS / "documents.json").read_text(encoding="utf-8")
    (DOCS / "documents.json").write_text(json.dumps(documents, ensure_ascii=False, separators=(",", ":")) + ("\n" if raw.endswith("\n") else ""), encoding="utf-8")
    spm_path = DOCS / "sp" / "manifest.json"
    spm_raw = spm_path.read_text(encoding="utf-8")
    spm = json.loads(spm_raw)
    for key, entry in spm["files"].items():
        f = DOCS / "sp" / key
        entry["sha"] = hashlib.sha256(f.read_bytes()).hexdigest()[: len(entry["sha"])]
        entry["bytes"] = f.stat().st_size
    spm_path.write_text(json.dumps(spm, ensure_ascii=False, indent=2) + ("\n" if spm_raw.endswith("\n") else ""), encoding="utf-8")
    m_path = DOCS / "manifest.json"
    m_raw = m_path.read_text(encoding="utf-8")
    m = json.loads(m_raw)
    for key, entry in m["files"].items():
        f = DOCS / key
        if f.exists() and isinstance(entry, dict) and "sha" in entry:
            entry["sha"] = hashlib.sha256(f.read_bytes()).hexdigest()[: len(entry["sha"])]
            if "bytes" in entry:
                entry["bytes"] = f.stat().st_size
    m_path.write_text(json.dumps(m, ensure_ascii=False, indent=2) + ("\n" if m_raw.endswith("\n") else ""), encoding="utf-8")
    print(f"[sp-rebuild] applied: {len(touched)} report(s) rewritten, manifests re-hashed")


if __name__ == "__main__":
    main()
