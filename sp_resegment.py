#!/usr/bin/env python3
"""Re-cut a Special Procedures report into paragraphs from its DOCX or its PDF.

sp_rebuild_from_docx.py repairs a report paragraph by paragraph, which needs
the corpus to have cut the report at the right places. For some reports it
did not: the PDF extraction took numbers inside the prose for paragraph starts
("…in 2015. 698. …"), merged paragraphs across page breaks, or dropped whole
stretches, so fewer than 80% of the corpus paragraphs match anything. Those
reports are re-cut here from scratch:

  DOCX  when UN Documents has one and it covers the report — the same parser
        as sp_rebuild_from_docx.py (typed or Word-numbered paragraphs,
        heading styles, w:footnoteReference);
  PDF   otherwise, from the page layout: running headers and footers dropped
        by position, the footnote block under the separator rule turned into
        notes, headings recognised by position, case and weight, paragraph
        starts by their number at the body margin, and paragraphs stitched
        back together across page breaks.

A report is re-cut only when the new text still carries the prose the corpus
had (≥ --min-coverage of its word trigrams, not counting headings and note
text), so nothing that was searchable disappears. The paragraphs of a re-cut
report get fresh ids (<docId>-0001 …) and numbers; labels are recomputed with
the ingest's own patterns, and citedArticles carry over from the old
paragraph that holds the same text.

Dry run by default; --apply rewrites the shards, updates paragraphCount /
wordCount / labelCount / textSource in documents.json and the paragraph
counts and hashes in both manifests.

    python3 sp_resegment.py --doc a-hrc-14-46 --show
    python3 sp_resegment.py --docs-from report.csv --apply
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import re
import subprocess
import sys
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz  # PyMuPDF

import sp_rebuild_from_docx as R
from ingest_sp_mandate import label_paragraph

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
PDF_CACHE = ROOT / "sp_ingest_pdfs"


def slug(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", symbol).strip("_")


# ─────────── PDF → blocks ───────────
def fetch_pdf(symbol: str) -> Path | None:
    target = PDF_CACHE / f"{slug(symbol)}.pdf"
    if target.exists() and target.stat().st_size > 2000:
        return target
    PDF_CACHE.mkdir(exist_ok=True)
    url = f"https://documents.un.org/api/symbol/access?s={urllib.parse.quote(symbol, safe='')}&l=en&t=pdf"
    tmp = target.with_suffix(".download")
    subprocess.run(["curl", "-sL", "--max-time", "120", "-A", "Mozilla/5.0", "-o", str(tmp), url], capture_output=True)
    if tmp.exists() and tmp.read_bytes()[:4] == b"%PDF":
        tmp.rename(target)
        return target
    tmp.unlink(missing_ok=True)
    return None


SEPARATOR = re.compile(r"^[_\s]{5,}$")
NOTE_START = re.compile(r"^\s*(\d{1,3})(?:/|\s)\s*(\S.*)$", re.S)
LIST_ITEM = re.compile(r"^\(?[a-z]{1,4}\)\s|^\([ivx]+\)\s|^[•\-–]\s")
ROMAN = re.compile(r"^[IVXL]{1,6}\.\s")
LETTER = re.compile(r"^[A-Z]\.\s")
NOTES_HEAD = re.compile(r"^(?:Notes|NOTES|Endnotes|ENDNOTES)$")


def _lines(block) -> list[dict]:
    out = []
    for line in block["lines"]:
        spans = [s for s in line["spans"] if s["text"].strip() or s["text"] == " "]
        if spans:
            out.append({"bbox": line["bbox"], "spans": spans})
    return out


def _line_text(line, body_size: float, notes_here: set, marker_style: bool) -> str:
    """Text of a line; superscript note numbers become [[fn:N]]."""
    parts = []
    base = max((s["size"] for s in line["spans"]), default=body_size)
    for s in line["spans"]:
        t = s["text"]
        sup = (s["flags"] & 1) or (s["size"] < 0.8 * base and s["bbox"][3] < line["bbox"][3] - 1)
        if sup and re.fullmatch(r"\s*\d{1,3}\s*", t) and marker_style:
            parts.append(f"[[fn:{int(t)}]]")
        else:
            parts.append(t)
    return "".join(parts)


def _join_lines(lines: list[str], vocab: set) -> str:
    text = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if not text:
            text = ln
            continue
        m = re.search(r"([A-Za-z]+)-$", text)
        n = re.match(r"([a-z]+)", ln)
        if m and n:
            joined = (m.group(1) + n.group(1)).lower()
            # a line-end hyphen is kept when the report writes the word
            # hyphenated elsewhere or never writes it joined
            if joined in vocab:
                text = text[:-1] + ln
                continue
            text = text + ln
            continue
        text = text + " " + ln
    return re.sub(r"\s+", " ", text).strip()


def _split_blocks(raw_blocks, height: float, state: dict) -> list[dict]:
    """PyMuPDF text blocks, cut where a new paragraph or heading visibly starts
    inside one (some PDFs come as one block per page): at a line that opens
    with the next paragraph number, or with any number after a line that
    closes a sentence, and around a short line that reads as a heading
    ("II. ACTIVITIES", "B. Country visits"). Lines in the running-header and
    footer bands are dropped here; `state` carries the last paragraph number
    across pages."""
    out = []
    for b in raw_blocks:
        if b.get("type") != 0:
            continue
        lines = [ln for ln in _lines(b) if not (ln["bbox"][3] < 0.075 * height or ln["bbox"][1] > 0.935 * height)
                 and not _furniture("".join(sp["text"] for sp in ln["spans"]).strip(), state["symbol"])]
        cur, prev = [], None
        for ln in lines:
            t = "".join(s["text"] for s in ln["spans"]).strip()
            if not t:
                continue
            pt = "".join(s["text"] for s in prev["spans"]).strip() if prev else ""
            closes = bool(re.search(r"[.:;!?”\")]$", pt)) or not pt
            m = re.match(r"^(\d{1,3})\.(\s|$)", t)
            head = (len(t) < 120 and closes and not re.search(r"[.;:,]$", t)
                    and (re.match(r"^(?:[IVXL]{1,6}|[A-Z])\.\s+\S", t) or (t.isupper() and len(t) > 6)))
            start = bool(m and (int(m.group(1)) == state["last"] + 1 or closes)) or head or (prev and prev.get("_head"))
            if m and start:
                state["last"] = int(m.group(1))
            if start and cur:
                out.append(_mk_block(cur))
                cur = []
            ln = {**ln, "_head": bool(head)}
            cur.append(ln)
            prev = ln
        if cur:
            out.append(_mk_block(cur))
    return out


def _furniture(t: str, symbol: str) -> bool:
    """A running header or footer line: the report's own symbol, "page 7",
    a page counter or a job number."""
    t = re.sub(r"\s+", " ", t).strip()
    return bool(t) and (t.replace(" ", "") == symbol.replace(" ", "")
                        or re.fullmatch(r"(?:page|Page)\s+\d+|[-–]\s*\d{1,3}\s*[-–]|\d{1,3}/\d{1,3}|(?:GE\.)?\d{2}-\d{4,6}(?:\s*\(E\))?", t) is not None)


def _mk_block(lines) -> dict:
    xs0 = [ln["bbox"][0] for ln in lines]
    return {"type": 0, "lines": lines,
            "bbox": (min(xs0), lines[0]["bbox"][1], max(ln["bbox"][2] for ln in lines), lines[-1]["bbox"][3])}


def parse_pdf_blocks(path: Path, symbol: str = "") -> list[dict]:
    """Blocks in the shape sp_rebuild_from_docx.parse_blocks returns."""
    doc = fitz.open(path)
    split_state = {"last": 0, "symbol": symbol}
    pages = []
    sizes = Counter()
    starts_x = Counter()
    vocab = set()
    for page in doc:
        d = page.get_text("dict")
        blocks = _split_blocks(d["blocks"], page.rect.height, split_state)
        pages.append((page.rect.width, page.rect.height, blocks))
        for b in blocks:
            for ln in _lines(b):
                for s in ln["spans"]:
                    sizes[round(s["size"], 1)] += len(s["text"])
                    vocab.update(w.lower() for w in re.findall(r"[A-Za-z]+", s["text"]))
            first = "".join(s["text"] for s in _lines(b)[0]["spans"]).strip()
            if re.match(r"^\d{1,3}\.(\s|$)", first):
                starts_x[round(b["bbox"][0] / 4) * 4] += 1
    doc.close()
    body_size = sizes.most_common(1)[0][0] if sizes else 10
    body_x = starts_x.most_common(1)[0][0] if starts_x else None

    out: list[dict] = []
    last_n = 0
    note_counter = 0
    in_endnotes = False
    for pno, (width, height, blocks) in enumerate(pages):
        # (PyMuPDF's own block order is the reading order; sorting by position
        # interleaves the pieces of a justified line)
        body, notes = [], []
        below_rule = False
        for b in blocks:
            x0, y0, x1, y1 = b["bbox"]
            lines = _lines(b)
            raw = "\n".join("".join(s["text"] for s in ln["spans"]) for ln in lines).strip()
            # running header / footer bands
            if y1 < 0.075 * height or y0 > 0.935 * height:
                continue
            if re.fullmatch(r"(?:GE\.)?\d{2}-\d{4,6}(?:\s*\(E\))?|\d{1,3}/\d{1,3}|[-–]?\s*\d{1,3}\s*[-–]?|page\s+\d+", raw, re.I):
                continue
            if SEPARATOR.match(raw):
                below_rule = True
                continue
            if below_rule:
                notes.append(b)
                continue
            body.append(b)
        # notes of this page: "12 text" or "12/ text", possibly several per block
        page_notes = {}
        cur = None
        for b in notes:
            for ln in _lines(b):
                t = "".join(s["text"] for s in ln["spans"])
                m = NOTE_START.match(t)
                if m and (cur is None or int(m.group(1)) in (cur + 1, 1)):
                    cur = int(m.group(1))
                    page_notes[cur] = m.group(2).strip()
                elif cur is not None:
                    page_notes[cur] = (page_notes[cur] + " " + t.strip()).strip()
        widths = Counter()
        for b in body:
            widths[round(b["bbox"][0] / 3) * 3] += sum(len(s["text"]) for ln in _lines(b) for s in ln["spans"])
        margin = min((x for x, n in widths.items() if n >= 0.15 * sum(widths.values())), default=body_x or 0)
        for b in body:
            x0, y0, x1, y1 = b["bbox"]
            lines = _lines(b)
            texts = [_line_text(ln, body_size, set(page_notes), bool(page_notes)) for ln in lines]
            text = _join_lines(texts, vocab)
            text = re.sub(r"\s+(\[\[fn:\d+\]\])", r"\1", text)
            # old typewritten notes: "…the law 3/ and…"
            if page_notes:
                text = re.sub(r"(?<=\S)\s?(\d{1,3})/(?=[\s.,;:)]|$)",
                              lambda m: f"[[fn:{m.group(1)}]]" if int(m.group(1)) in page_notes else m.group(0), text)
            if not text or re.search(r"(?:\.\s){5,}|\.{6,}", text):
                continue                      # empty, or a contents line with dot leaders
            spans = [s for ln in lines for s in ln["spans"] if s["text"].strip()]
            bold = spans and all(s["flags"] & 16 for s in spans)
            big = spans and min(s["size"] for s in spans) > body_size + 0.5
            # a paragraph number sits at the page's own margin (margins
            # alternate on facing pages) — or opens a long block anyway
            num = re.match(r"^(\d{1,3})\.\s", text)
            numbered_start = bool(num) and (x0 <= margin + 10 or len(text) > 150 or int(num.group(1)) == last_n + 1)
            letters = re.sub(r"[^A-Za-z]", "", text)
            upper = len(letters) > 3 and letters.isupper()
            centred = abs((x0 + x1) / 2 - width / 2) < 0.08 * width and (x1 - x0) < 0.75 * width and len(text) <= 150
            marker = re.match(r"^(?:[IVXL]{1,6}|[A-Z])\.\s+[A-Z“\"]", text) or (num and len(text) <= 100 and (bold or title))
            words_ = text.split()
            title = (len(text) <= 60 and len(words_) <= 7
                     and all(w[:1].isupper() or w.lower() in {"and", "of", "the", "in", "on", "for", "to", "de", "del", "la", "(islamic", "republic"} for w in words_))
            short = len(text) <= 200 and not re.search(r"[.;:,]$", text)
            is_head = (not numbered_start and not LIST_ITEM.match(text) and short and text[:1].isalnum() and text[:1] == text[:1].upper()
                       and (bold or big or upper or centred or marker or title))
            if in_endnotes and not is_head:
                m = NOTE_START.match(text)
                if m:
                    note_counter = int(m.group(1))
                continue
            if is_head:
                label = MARKER_RE.sub("", text).strip()
                in_endnotes = bool(NOTES_HEAD.match(label))
                if in_endnotes:
                    continue
                if ROMAN.match(label) or (upper and not LETTER.match(label)):
                    level = 0
                elif LETTER.match(label):
                    level = 1
                else:
                    level = 2
                prev = out[-1] if out else None
                if (prev and prev["kind"] == "head" and prev.get("_page") == pno
                        and not re.match(r"^(?:[IVXL]{1,6}|[A-Z]|\d{1,2})\.\s", label)
                        and (label[:1].islower() or label.isupper() == prev["text"].isupper())):
                    prev["text"] += " " + label          # a heading wrapped onto a second line
                    continue
                out.append({"kind": "head", "level": level, "text": label, "notes": [], "row": None, "_page": pno})
                continue
            if numbered_start:
                if last_n == 0:
                    # First paragraph: of everything before it (title page,
                    # summary, contents), only the headings right above it
                    # on its own page are section headings.
                    tail = []
                    for x in reversed(out):
                        if x["kind"] != "head" or x.get("_page") != pno:
                            break
                        tail.insert(0, x)
                    out[:] = tail
                last_n = int(num.group(1))
            ids = [int(x) for x in re.findall(r"\[\[fn:(\d+)\]\]", text)]
            notes_here = [(n, page_notes[n]) for n in ids if n in page_notes]
            # a block that is not a paragraph start, a list item or a quote
            # continues the paragraph cut by the page break or by the layout
            cont = (out and out[-1]["kind"] == "body" and not numbered_start and not LIST_ITEM.match(text)
                    and (text[:1].islower() or not re.search(r"[.:;!?”\")]$", out[-1]["text"])))
            if cont:
                out[-1]["text"] += " " + text
                out[-1]["notes"].extend(notes_here)
            else:
                out.append({"kind": "body", "level": None, "text": text, "notes": notes_here, "row": None})
    return out


MARKER_RE = re.compile(r"\[\[fn:\d+\]\]")


# ─────────── spans → paragraphs ───────────
def recut_spans(blocks: list[dict]) -> list[dict]:
    """numbered_spans for re-cutting: the same, except that unnumbered prose
    right under a heading (an annex's guiding principles, "Practice 3" in a
    compilation) is kept. Paragraph numbers must stay the report's own, so
    such text joins the numbered paragraph before it, heading line included,
    and that heading does not also open a section."""
    fixed, pending = [], []
    seen_numbered = False
    for b in blocks:
        if b["kind"] == "head":
            pending.append(b)
            continue
        numbered = b["kind"] == "body" and R.NUMBERED.match(b["text"])
        seen_numbered = seen_numbered or bool(numbered)
        if pending and not numbered and seen_numbered and b["kind"] == "body":
            # orphan prose under the pending headings: fold them in as text
            for h in pending:
                fixed.append({**h, "kind": "body", "text": h["text"]})
            pending = []
        fixed.extend(pending)
        pending = []
        fixed.append(b)
    fixed.extend(pending)
    return R.numbered_spans(fixed)


def docx_spans(symbol: str, cache: Path):
    path = R.fetch_docx(symbol, cache)
    if not path:
        return None
    try:
        lit = recut_spans(R.parse_blocks(path))
        auto = recut_spans(R.parse_blocks(path, auto_numbers=True))
    except Exception:
        return None
    return max((lit, auto), key=len)


def pdf_spans(symbol: str):
    path = fetch_pdf(symbol)
    if not path:
        return None
    try:
        return recut_spans(parse_pdf_blocks(path, symbol))
    except Exception as e:
        print(f"    [{symbol}] pdf parse failed: {e}", file=sys.stderr)
        return None


def recut(doc: dict, old: list[dict], spans: list[dict], min_cov: float, source: str):
    """New paragraph list for the report, or (None, reason)."""
    if not spans or len(spans) < 3:
        return None, "no numbered paragraphs"
    gone_ok = set()
    for s in spans:
        gone_ok |= R.shingles(s.get("heads", ""))
        for t in s["section"]:
            gone_ok |= R.shingles(t)
        for _, note in s["notes"]:
            gone_ok |= R.shingles(note)
    old_sh = set()
    for q in old:
        old_sh |= R.shingles(q["text"])
    old_sh -= gone_ok
    new_sh = set()
    for s in spans:
        new_sh |= R.shingles(s["text"])
    cov = R.coverage(old_sh, new_sh)
    if cov < min_cov:
        return None, f"{source} covers {cov:.0%} of the old text"
    base = {k: old[0][k] for k in ("docId", "type", "committee", "committees", "year")}
    old_sh_by = [(q, R.shingles(q["text"])) for q in old]
    paras = []
    for i, s in enumerate(spans, 1):
        text = R.NUMBERED.sub("", s["text"], count=1)
        present = {int(x) for x in re.findall(r"\[\[fn:(\d+)\]\]", text)}
        fns, seen = [], set()
        for n, note in s["notes"]:
            if n in present and n not in seen and note:
                fns.append({"n": n, "text": note})
                seen.add(n)
        q = {"id": f"{base['docId']}-{i:04d}", **base, "idx": i, "n": s["n"], "text": text,
             "labels": label_paragraph(MARKER_RE.sub("", text) + " " + " ".join(f["text"] for f in fns)),
             "footnotes": fns}
        if s["section"]:
            q["section"] = s["section"]
        # citedArticles follow the old paragraph whose text this one holds
        sh = R.shingles(text)
        cited = []
        for oq, osh in old_sh_by:
            if oq.get("citedArticles") and osh and len(osh & sh) >= 0.6 * len(osh):
                for c in oq["citedArticles"]:
                    if c not in cited and re.search(rf"\b{re.escape(str(c.get('article', '')))}\b", text):
                        cited.append(c)
        if cited:
            q["citedArticles"] = cited
        paras.append(q)
    return paras, f"{source} · coverage {cov:.1%}"


# ─────────── main ───────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", action="append", default=[])
    ap.add_argument("--docs-from", help="CSV with a docId column (e.g. the Jev integrity ranking)")
    ap.add_argument("--min-share", type=float, default=0.0, help="with --docs-from: only rows whose share_flagged ≥ this")
    ap.add_argument("--source", choices=["auto", "docx", "pdf"], default="auto")
    ap.add_argument("--min-coverage", type=float, default=0.9)
    ap.add_argument("--cache", default=str(ROOT / "sp_docx_cache"))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--report")
    ap.add_argument("--dump", help="write the re-cut paragraphs of every report to this JSON file")
    ap.add_argument("--only-from", help="JSON list of docIds allowed to be applied (e.g. those a QA pass accepted)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    targets = list(args.doc)
    if args.docs_from:
        for row in csv.DictReader(open(args.docs_from)):
            if float(row.get("share_flagged") or 0) >= args.min_share:
                targets.append(row["docId"])
    documents = R.load(DOCS / "documents.json")
    by_id = {d["docId"]: d for d in documents}
    shards, old_by_doc = {}, {}
    for path in sorted(glob.glob(str(DOCS / "sp" / "shards" / "*.json"))):
        data = R.load(Path(path))
        shards[path] = data
        for q in data:
            old_by_doc.setdefault(q["docId"], []).append(q)
    targets = [d for d in dict.fromkeys(targets) if d in old_by_doc]
    print(f"[sp-recut] {len(targets)} report(s)")

    def work(doc_id):
        d = by_id[doc_id]
        old = sorted(old_by_doc[doc_id], key=lambda q: q["idx"])
        reasons = []
        for source in (["docx", "pdf"] if args.source == "auto" else [args.source]):
            spans = docx_spans(d["signature"], Path(args.cache)) if source == "docx" else pdf_spans(d["signature"])
            if spans is None:
                reasons.append(f"no {source}")
                continue
            paras, why = recut(d, old, spans, args.min_coverage, source)
            if paras:
                return doc_id, paras, why, source
            reasons.append(why)
        return doc_id, None, "; ".join(reasons), None

    with ThreadPoolExecutor(args.workers) as ex:
        results = list(ex.map(work, targets))
    done = [r for r in results if r[1]]
    print(f"[sp-recut] re-cut {len(done)}/{len(results)} · by source {dict(Counter(r[3] for r in done))}")
    for doc_id, paras, why, source in results:
        old = old_by_doc[doc_id]
        print(f"  {doc_id:28} {'OK ' if paras else '-- '} {len(old):4d} → {len(paras) if paras else '':>4} ¶  {why}")
    if args.report:
        with open(args.report, "w") as fh:
            for doc_id, paras, why, source in results:
                fh.write(json.dumps({"docId": doc_id, "ok": bool(paras), "old": len(old_by_doc[doc_id]),
                                     "new": len(paras) if paras else None, "why": why, "source": source}) + "\n")
    if args.dump:
        json.dump({doc_id: paras for doc_id, paras, *_ in done}, open(args.dump, "w"), ensure_ascii=False)
    if args.only_from:
        allowed = set(json.load(open(args.only_from)))
        done = [r for r in done if r[0] in allowed]
        print(f"[sp-recut] {len(done)} report(s) allowed by {args.only_from}")
    if args.show:
        for doc_id, paras, *_ in done:
            for q in paras[:6]:
                print(f"\n--- {q['id']} ¶{q['n']} {' › '.join(q.get('section') or [])}\n{q['text'][:600]}\nFN {[f['n'] for f in q['footnotes']]}")
    if not args.apply:
        print("[sp-recut] dry run — nothing written (use --apply)")
        return

    new_by_doc = {doc_id: paras for doc_id, paras, *_ in done}
    source_of = {doc_id: src for doc_id, _, _, src in done}
    for path, data in shards.items():
        if not any(q["docId"] in new_by_doc for q in data):
            continue
        out, placed = [], set()
        for q in data:
            if q["docId"] in new_by_doc:
                if q["docId"] not in placed:
                    out.extend(new_by_doc[q["docId"]])
                    placed.add(q["docId"])
            else:
                out.append(q)
        shards[path] = out
        Path(path).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    for d in documents:
        if d["docId"] in new_by_doc:
            ps = new_by_doc[d["docId"]]
            d["paragraphCount"] = len(ps)
            d["wordCount"] = sum(len(MARKER_RE.sub("", q["text"]).split()) for q in ps)
            d["labelCount"] = sum(len(q["labels"]) for q in ps)
            d["textSource"] = "documents.un.org docx" if source_of[d["docId"]] == "docx" else "documents.un.org pdf (layout)"
            d["footnotesSource"] = d["textSource"]
    raw = (DOCS / "documents.json").read_text(encoding="utf-8")
    (DOCS / "documents.json").write_text(json.dumps(documents, ensure_ascii=False, separators=(",", ":")) + ("\n" if raw.endswith("\n") else ""), encoding="utf-8")
    # manifests: hashes, bytes and paragraph counts
    total = 0
    spm_path = DOCS / "sp" / "manifest.json"
    spm_raw = spm_path.read_text(encoding="utf-8")
    spm = json.loads(spm_raw)
    for key, entry in spm["files"].items():
        f = DOCS / "sp" / key
        entry["sha"] = hashlib.sha256(f.read_bytes()).hexdigest()[: len(entry["sha"])]
        entry["bytes"] = f.stat().st_size
        if "paragraphs" in entry:
            entry["paragraphs"] = len(shards[str(f)]) if str(f) in shards else entry["paragraphs"]
        total += entry.get("paragraphs", 0)
    spm["counts"]["paragraphs"] = total
    spm_path.write_text(json.dumps(spm, ensure_ascii=False, indent=2) + ("\n" if spm_raw.endswith("\n") else ""), encoding="utf-8")
    m_path = DOCS / "manifest.json"
    m_raw = m_path.read_text(encoding="utf-8")
    m = json.loads(m_raw)
    delta = total - m["counts"]["spParagraphs"]
    m["counts"]["spParagraphs"] = total
    m["counts"]["paragraphs"] += delta
    for key, entry in m["files"].items():
        f = DOCS / key
        if f.exists() and isinstance(entry, dict) and "sha" in entry:
            entry["sha"] = hashlib.sha256(f.read_bytes()).hexdigest()[: len(entry["sha"])]
            if "bytes" in entry:
                entry["bytes"] = f.stat().st_size
    m_path.write_text(json.dumps(m, ensure_ascii=False, indent=2) + ("\n" if m_raw.endswith("\n") else ""), encoding="utf-8")
    print(f"[sp-recut] applied: {len(new_by_doc)} report(s) re-cut · SP paragraphs {total} ({delta:+d})")


if __name__ == "__main__":
    main()
