#!/usr/bin/env python3
"""Recover footnotes for Special Procedures reports from the UN Documents DOCX.

The SP corpus was extracted from PDFs as plain text, so a footnote reference
survives only as a digit glued to the preceding word ("…Human Rights
Council.1") and the footnote text is missing altogether for 1,292 of the
1,591 reports. UN Documents serves the same reports as Word files whose
footnotes are structured (word/footnotes.xml + w:footnoteReference in the
body), so this script:

  1. downloads the DOCX for every SP report that lacks footnote text
     (cached under --cache; Word-97 binaries are converted with soffice);
  2. numbers the references the way they print — in body order, skipping
     custom-mark (asterisk) notes — and maps printed number → text;
  3. walks the report's corpus paragraphs in order and accepts a glued digit
     as footnote N when it continues the increasing sequence of printed
     numbers (a "Rev.1" or "para. 3" glued the same way breaks the sequence
     and is left alone), preferring digits whose paragraph text also matches
     a DOCX paragraph carrying that reference;
  4. rewrites the digit as the reader's `[[fn:N]]` marker and attaches
     {n, text} to the paragraph.

Dry run by default; --apply rewrites the SP shards (committed spaced form),
stamps `footnotesSource` on the document records and re-hashes the manifests.

    python3 sp_footnotes_from_docx.py --doc a-hrc-44-57 --apply
    python3 sp_footnotes_from_docx.py --workers 4 --apply
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import BadZipFile, ZipFile

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
W_NS = {"w": W[1:-1]}
UA = "Mozilla/5.0 (compatible; UNHRDB footnote recovery; +https://github.com/lszoszk/generalcomments)"
GLUED = re.compile(r'(?<=[a-zA-Z\)”’"\.,;:])(\d{1,3})(?=\s+[A-Z“"(]|\s*$|[\.,;:)])')


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def norm(s: str) -> str:
    s = re.sub(r"\[\[fn:\d+\]\]", "", s)
    s = GLUED.sub("", s)
    return re.sub(r"[^a-z0-9]+", "", s.lower())


# ─────────── download ───────────
def fetch_docx(symbol: str, cache: Path) -> Path | None:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", symbol).strip("_")
    target = cache / f"{slug}.docx"
    if target.exists() and target.stat().st_size > 2000:
        return target
    missing = cache / f"{slug}.missing"
    if missing.exists():
        return None
    url = f"https://documents.un.org/api/symbol/access?s={urllib.parse.quote(symbol, safe='')}&l=en&t=docx"
    tmp = cache / f"{slug}.download"
    # curl rather than urllib: Python's stdlib does not trust the
    # documents.un.org certificate chain on every machine, curl does.
    r = subprocess.run(["curl", "-sL", "--max-time", "90", "-A", UA, "-o", str(tmp), "-w", "%{http_code}", url],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.startswith("2") or not tmp.exists():
        print(f"    [{symbol}] download failed: curl exit {r.returncode} http {r.stdout.strip()}", file=sys.stderr)
        tmp.unlink(missing_ok=True)
        return None
    data = tmp.read_bytes()
    if len(data) < 2000 or data[:15].lower().startswith(b"<!doctype") or b"<html" in data[:400].lower():
        tmp.unlink(missing_ok=True)
        missing.write_text("no docx on documents.un.org\n")
        return None
    if data[:2] == b"PK":
        tmp.rename(target)
        return target
    # Word 97 binary → convert with LibreOffice when available.
    if data[:4] == b"\xd0\xcf\x11\xe0" and shutil.which("soffice"):
        legacy = cache / f"{slug}.doc"
        tmp.rename(legacy)
        subprocess.run(["soffice", "--headless", "--convert-to", "docx", "--outdir", str(cache), str(legacy)],
                       capture_output=True, timeout=180)
        legacy.unlink(missing_ok=True)
        return target if target.exists() else None
    tmp.unlink(missing_ok=True)
    return None


# ─────────── parse ───────────
def docx_text(el) -> str:
    parts = []
    for node in el.iter():
        if node.tag == f"{W}t" and node.text:
            parts.append(node.text)
        elif node.tag == f"{W}tab":
            parts.append(" ")
    return "".join(parts)


def parse_docx(path: Path):
    """Return (printed_map {n: text}, paragraphs [(norm_text, [printed n...])])."""
    with ZipFile(path) as z:
        names = z.namelist()
        # Older UN documents carry their notes as Word endnotes.
        if "word/footnotes.xml" in names:
            part, note_tag, ref_tag = "word/footnotes.xml", "w:footnote", f"{W}footnoteReference"
        elif "word/endnotes.xml" in names:
            part, note_tag, ref_tag = "word/endnotes.xml", "w:endnote", f"{W}endnoteReference"
        else:
            return {}, []
        froot = ET.fromstring(z.read(part))
        broot = ET.fromstring(z.read("word/document.xml"))
    by_id = {}
    for fn in froot.findall(note_tag, W_NS):
        try:
            fid = int(fn.attrib.get(f"{W}id"))
        except (TypeError, ValueError):
            continue
        if fid < 1:
            continue
        text = re.sub(r"\s+", " ", " ".join(docx_text(p) for p in fn.findall("w:p", W_NS))).strip()
        by_id[fid] = text
    # Some documents put the note mark itself (a symbol-font glyph that
    # survives as "?" or "*") at the start of EVERY note text: a document
    # convention to strip, not an unnumbered title note. Only when a
    # minority of notes carry such a prefix does it mark an asterisk note.
    glyph = re.compile(r"^[?*†‡]+\s*")
    prefixed = sum(1 for t in by_id.values() if glyph.match(t))
    convention = by_id and prefixed / len(by_id) > 0.5
    if convention:
        by_id = {k: glyph.sub("", t) for k, t in by_id.items()}
    printed = {}
    paragraphs = []
    body = broot.find("w:body", W_NS)
    counter = 0
    for p in body.iter(f"{W}p"):
        refs = []
        parts = []
        for node in p.iter():
            if node.tag == f"{W}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{W}tab":
                parts.append(" ")
            elif node.tag == ref_tag:
                try:
                    fid = int(node.attrib.get(f"{W}id"))
                except (TypeError, ValueError):
                    continue
                if fid < 1:
                    continue
                text = by_id.get(fid, "")
                # Unnumbered notes: Word's custom marks, and the title notes
                # UN documents set with an asterisk in a symbol font, which
                # comes through as "?" / "*" — they must not shift the count.
                if node.attrib.get(f"{W}customMarkFollows") in ("1", "true") or (not convention and re.match(r"^[?*†‡]", text)):
                    continue
                counter += 1
                if text:
                    printed[counter] = text
                refs.append(counter)
                parts.append(f"[[fn:{counter}]]")
        raw = re.sub(r"[ \t]+", " ", "".join(parts)).strip()
        if raw or refs:
            paragraphs.append((raw, refs))
    return printed, paragraphs


# ─────────── match ───────────
LETTERS = re.compile(r"[^a-z]")


def letters(s: str) -> str:
    return LETTERS.sub("", re.sub(r"\[\[fn:\d+\]\]", "", s).lower())


def align_globally(doc_paras: list[dict], docx_paras: list[tuple[str, list[int]]]) -> dict[int, list[tuple[int, int]]]:
    """Place the DOCX notes into the corpus paragraphs by letter context.

    Both texts are reduced to their letters and concatenated document-wide,
    so it does not matter how either side split its paragraphs. For each
    DOCX marker the 20 letters before it and the 12 after it are looked up
    in the corpus stream (moving forward only); the insertion point is the
    raw position right after that letter, past any closing punctuation. A
    short digit run glued there is the PDF's own note number: it is dropped
    and, when it differs from the DOCX count (numbering restarts in an
    annex), it is what the reader shows.

    Returns {paragraph index in doc_paras: [(shown, source n), …]} and edits
    the paragraph texts in place.
    """
    # corpus stream
    letter_para: list[int] = []
    letter_raw: list[int] = []
    chunks = []
    for pi, q in enumerate(doc_paras):
        text = q["text"]
        # skip existing marker spans, or their letters ("fn") pollute the stream
        skip = [False] * len(text)
        for m in re.finditer(r"\[\[fn:\d+\]\]", text):
            for k in range(m.start(), m.end()):
                skip[k] = True
        for i, ch in enumerate(text):
            if ch.isalpha() and not skip[i]:
                letter_para.append(pi)
                letter_raw.append(i)
                chunks.append(ch.lower())
    stream = "".join(chunks)
    # docx stream with marker offsets
    dchunks = []
    marks = []                              # (letter offset, n)
    for raw, refs in docx_paras:
        for m in re.finditer(r"\[\[fn:(\d+)\]\]|[A-Za-z]", raw):
            if m.group(1):
                marks.append((len(dchunks), int(m.group(1))))
            else:
                dchunks.append(m.group(0).lower())
    dstream = "".join(dchunks)
    cursor = 0
    inserts: dict[int, list[tuple[int, int, int]]] = {}   # pi -> [(raw pos, shown, source)]
    for off, n in marks:
        before = dstream[max(0, off - 20):off]
        after = dstream[off:off + 12]
        if len(before) < 12:
            continue
        pos = stream.find(before, cursor)
        while pos != -1 and stream[pos + len(before):pos + len(before) + len(after)] != after:
            pos = stream.find(before, pos + 1)
        if pos == -1:
            continue
        li = pos + len(before) - 1          # index of the last letter before the note
        cursor = li + 1
        pi = letter_para[li]
        inserts.setdefault(pi, []).append((letter_raw[li] + 1, n))
    placed: dict[int, list[tuple[int, int]]] = {}
    for pi, items in inserts.items():
        text = doc_paras[pi]["text"]
        edits = []
        for rawpos, n in items:
            pos = rawpos
            while pos < len(text) and text[pos] in ".,;:)]”’\"":
                pos += 1
            drop, shown = 0, n
            dm = re.match(r"(\d{1,3})(?![\d\w])", text[pos:])
            if dm:
                drop = len(dm.group(1))
                shown = int(dm.group(1))
            edits.append((pos, drop, shown, n))
        for pos, drop, shown, n in sorted(edits, key=lambda t: -t[0]):
            text = text[:pos] + f"[[fn:{shown}]]" + text[pos + drop:]
        doc_paras[pi]["text"] = text
        placed[pi] = [(shown, n) for _, _, shown, n in sorted(edits, key=lambda t: t[0])]
    return placed


def recover(doc_paras: list[dict], printed: dict[int, str], docx_paras: list[tuple[str, list[int]]]):
    """Insert [[fn:N]] markers + footnotes into doc_paras (in place). Returns stats."""
    stats = {"printed": len(printed), "aligned": 0, "sequence": 0, "rejected": 0}
    ordered = sorted(doc_paras, key=lambda x: x["idx"])
    pre_marked = {i for i, q in enumerate(ordered) if "[[fn:" in q["text"]}
    aligned = align_globally([q if i not in pre_marked else {"text": q["text"], "idx": q["idx"]} for i, q in enumerate(ordered)], docx_paras)
    # (paragraphs that already carried markers were passed as throwaway copies)
    expected = 1
    for i, q in enumerate(ordered):
        text = q["text"]
        if i in pre_marked:
            nums = [int(x) for x in re.findall(r"\[\[fn:(\d+)\]\]", text)]
            if nums:
                expected = max(expected, max(nums) + 1)
            continue
        placed_here = aligned.get(i, [])
        if placed_here:
            stats["aligned"] += len(placed_here)
        if not placed_here:
            # Fallback: glued digits that continue the printed sequence. A jump
            # beyond +4 is accepted only when the next digit continues from it
            # (resynchronisation after notes the corpus never had).
            matches = list(GLUED.finditer(text))
            vals = [int(m.group(1)) for m in matches]
            new_text, last, attach = [], 0, []
            for i, m in enumerate(matches):
                g = vals[i]
                nxt = vals[i + 1] if i + 1 < len(vals) else None
                ok = g in printed and g >= expected and (g <= expected + 4 or (nxt is not None and g < nxt <= g + 2))
                if ok:
                    new_text.append(text[last:m.start()])
                    new_text.append(f"[[fn:{g}]]")
                    last = m.end()
                    placed_here.append((g, g))
                    expected = g + 1
                else:
                    stats["rejected"] += 1
            if placed_here:
                new_text.append(text[last:])
                q["text"] = "".join(new_text)
                stats["sequence"] += len(placed_here)
        if placed_here:
            existing = {f["n"] for f in (q.get("footnotes") or []) if isinstance(f, dict)}
            q["footnotes"] = (q.get("footnotes") or []) + [{"n": shown, "text": printed[src]}
                                                          for shown, src in placed_here if src in printed and shown not in existing]
            expected = max(expected, max(src for _, src in placed_here) + 1)
    stats["accepted"] = stats["aligned"] + stats["sequence"]
    return stats


# ─────────── main ───────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", action="append", help="docId(s) to process (default: every SP doc without footnote text)")
    ap.add_argument("--cache", default=str(ROOT / "sp_docx_cache"))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)

    documents = load(DOCS / "documents.json")
    sp_docs = {d["docId"]: d for d in documents if d.get("type") == "sp"}
    shards = {}
    paras_by_doc: dict[str, list[dict]] = {}
    for path in sorted(glob.glob(str(DOCS / "sp" / "shards" / "*.json"))):
        data = load(Path(path))
        shards[path] = data
        for q in data:
            paras_by_doc.setdefault(q["docId"], []).append(q)
    has_fn = {d for d, ps in paras_by_doc.items() if any(q.get("footnotes") for q in ps)}
    if args.doc:
        targets = [d for d in args.doc if d in sp_docs]
    else:
        # Every report with a glued digit in a paragraph that carries no marker —
        # including the 272 reports that already hold some footnote text but
        # whose markers were never placed.
        targets = [d for d in sp_docs
                   if any(GLUED.search(q["text"]) and "[[fn:" not in q["text"] for q in paras_by_doc.get(d, []))]
        targets.sort()
    if args.limit:
        targets = targets[: args.limit]
    print(f"[sp-fn] {len(targets)} report(s) to process · cache {cache}")

    def work(doc_id):
        d = sp_docs[doc_id]
        symbol = d.get("signature") or d.get("symbol")
        t0 = time.time()
        path = fetch_docx(symbol, cache)
        if not path:
            return doc_id, None, "no docx"
        try:
            printed, docx_paras = parse_docx(path)
        except (BadZipFile, ET.ParseError, KeyError) as e:
            path.unlink(missing_ok=True)
            return doc_id, None, f"unreadable docx ({e})"
        if not printed:
            return doc_id, None, "docx has no footnotes"
        stats = recover(paras_by_doc[doc_id], printed, docx_paras)
        stats["secs"] = round(time.time() - t0, 1)
        return doc_id, stats, ""

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (doc_id, stats, err) in enumerate(ex.map(work, targets), 1):
            results.append((doc_id, stats, err))
            sym = sp_docs[doc_id].get("signature")
            if stats:
                print(f"  [{i}/{len(targets)}] {sym:16} printed {stats['printed']:4d} · aligned {stats['aligned']:4d} · sequence {stats['sequence']:4d} · rejected {stats['rejected']:3d}")
            else:
                print(f"  [{i}/{len(targets)}] {sym:16} SKIP — {err}")
    ok = [r for r in results if r[1]]
    acc = sum(r[1]["accepted"] for r in ok)
    rej = sum(r[1]["rejected"] for r in ok)
    pr = sum(r[1]["printed"] for r in ok)
    print(f"[sp-fn] recovered footnotes in {len(ok)}/{len(targets)} reports · markers placed {acc} of {pr} printed notes · glued digits left alone {rej}")
    skipped = {}
    for _, stats, err in results:
        if not stats:
            skipped[err] = skipped.get(err, 0) + 1
    if skipped:
        print(f"[sp-fn] skipped: {skipped}")
    if not args.apply:
        print("[sp-fn] dry run — nothing written (use --apply)")
        return
    # Write shards in the committed (spaced) form, stamp documents, re-hash manifests.
    touched_docs = {r[0] for r in ok if r[1]["accepted"]}
    changed = 0
    for path, data in shards.items():
        if any(q["docId"] in touched_docs for q in data):
            Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            changed += 1
    for d in documents:
        if d["docId"] in touched_docs:
            d["footnotesSource"] = "documents.un.org docx"
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
    print(f"[sp-fn] applied: {changed} shard(s) rewritten, {len(touched_docs)} document(s) stamped, manifests re-hashed")


if __name__ == "__main__":
    main()
