#!/usr/bin/env python3
"""Extract footnote markers + bodies from General Comment DOCX files.

WHY DOCX: lessons learned from the GC footnote pipeline (see
_docs_internal/extract_docx_with_footnotes.py + fix_fn_markers.py):

  L1. DOCX is ground truth. Word's <w:footnoteReference w:id="N"/>
      element sits exactly where the superscript belongs. PDFs flatten
      superscripts into the text stream and pdftotext routinely
      mangles marker placement (Cat A: split-word; Cat B: wrong-token).

  L2. Numbering is doc-wide cumulative, not per-paragraph. The corpus
      stores [[fn:N]] inline markers + a `footnotes: [{n, text}]` array
      on each paragraph; N is monotonic across the whole document.

  L3. Orphan footnote bodies (entry exists, inline marker missing) are
      tolerable — the reader handles them gracefully.

WHAT THIS SCRIPT DOES
---------------------
For every GC doc in docs/documents.json with a usable signature:

  1. Fetch the English DOCX from documents.un.org/api/symbol/access
     (cached to _docs_internal/footnotes/docx/<docId>.docx).
  2. Walk word/document.xml. For each <w:p>, concatenate <w:t> text
     and replace every <w:footnoteReference w:id="X"/> with a
     `§§FN§§<X>§§` placeholder at the exact position Word recorded.
  3. Match the paragraph to a corpus paragraph by leading-number
     prefix (e.g., docx para starts with "12. " → corpus paragraph
     n=12 of the same docId).
  4. Renumber Word footnote IDs to doc-wide sequential N (1, 2, 3, …)
     in source-document order, and resolve each ID to its body text
     from word/footnotes.xml.
  5. Emit a per-doc record into _docs_internal/footnotes/footnotes.json:

         {
           "<docId>": {
             "source": "docx",
             "signature": "A/74/385",
             "paragraphs": {
               "<n>": {
                 "inline_text": "…body text with [[fn:N]] markers…",
                 "footnotes": [{"n": N, "text": "…body…"}, …]
               },
               …
             }
           },
           …
         }

`apply_sp_footnotes.py` then stitches that onto docs/corpus.json,
running `fix_fn_markers.py` semantics afterwards is unnecessary
because docx-derived markers are already at correct positions.

USAGE
-----
    python3 _docs_internal/footnotes/extract_sp_footnotes.py             # dry run
    python3 _docs_internal/footnotes/extract_sp_footnotes.py --doc <id>  # one doc
    python3 _docs_internal/footnotes/extract_sp_footnotes.py --no-fetch  # use cache only
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

# ─────────────────────────────────────  paths
REPO = Path(__file__).resolve().parent.parent.parent
DOCS_JSON = REPO / "docs" / "documents.json"
CORPUS = REPO / "docs" / "corpus.json"
DOCX_DIR = REPO / "_docs_internal" / "footnotes" / "gc-docx"
OUT_JSON = REPO / "_docs_internal" / "footnotes" / "gc_footnotes.json"

# ─────────────────────────────────────  http
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE     # documents.un.org cert chain is fussy

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Match the leading "N." or "N. " prefix that anchors a numbered ¶.
LEADING_NUM = re.compile(r"^\s*(\d{1,4})\.(?:\s+|$)")


def fetch_docx(signature: str, dest: Path, force: bool = False) -> str:
    """Download the English ?t=docx response.

    Returns one of:
      - "docx"   — native OOXML zip (PK header). dest holds a real docx.
      - "doc"    — Word 97-2003 OLE compound binary. dest holds .doc bytes.
      - "wpc"    — WordPerfect (pre-Word). Caller will skip / fallback.
      - "miss"   — 404 or other unrecoverable error.

    The UN's `t=docx` endpoint serves whatever format the original
    Word source uses; only post-2015 docs are native docx. Older docs
    arrive as OLE .doc or even WordPerfect bytes despite the .docx
    extension. Caller branches on the returned kind."""
    if not force and dest.exists() and dest.stat().st_size > 1024:
        # Sniff cached file
        with open(dest, "rb") as fh:
            head = fh.read(8)
        if head[:4] == b"PK\x03\x04":
            return "docx"
        if head[:4] == b"\xd0\xcf\x11\xe0":
            return "doc"
        if head.startswith(b"\xffWPC"):
            return "wpc"
        # else: re-fetch
    url = f"https://documents.un.org/api/symbol/access?s={signature}&l=en&t=docx"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "miss"
        print(f"  ✗ {signature}: HTTP {e.code}", file=sys.stderr)
        return "miss"
    except Exception as e:
        print(f"  ✗ {signature}: {type(e).__name__}: {e}", file=sys.stderr)
        return "miss"
    head = data[:4]
    if head == b"PK\x03\x04":
        dest.write_bytes(data)
        return "docx"
    if head == b"\xd0\xcf\x11\xe0":
        # OLE compound — write as .doc sibling for offline conversion
        doc_path = dest.with_suffix(".doc")
        doc_path.write_bytes(data)
        return "doc"
    if head.startswith(b"\xffWPC"):
        wpc_path = dest.with_suffix(".wpc")
        wpc_path.write_bytes(data)
        return "wpc"
    print(f"  ✗ {signature}: unknown format ({data[:8]!r})", file=sys.stderr)
    return "miss"


_SOFFICE_PATHS = (
    "/opt/homebrew/bin/soffice",
    "/usr/local/bin/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "soffice",
    "libreoffice",
)


def _find_soffice() -> str | None:
    import shutil
    for cand in _SOFFICE_PATHS:
        if cand.startswith("/"):
            if Path(cand).is_file():
                return cand
        else:
            found = shutil.which(cand)
            if found:
                return found
    return None


def convert_doc_to_docx(doc_path: Path, docx_path: Path) -> bool:
    """Convert legacy Word 97-2003 .doc → .docx using LibreOffice headless.

    Why LibreOffice and not macOS `textutil`: textutil drops footnote
    references during conversion (verified on a-65-207 — produced an
    OOXML zip with NO word/footnotes.xml). soffice preserves both
    footnote bodies AND inline <w:footnoteReference> elements.

    Returns True iff docx_path now holds a valid OOXML file."""
    import subprocess
    soffice = _find_soffice()
    if not soffice:
        print("  ✗ LibreOffice (soffice) not on PATH — skipping .doc files",
              file=sys.stderr)
        return False
    try:
        subprocess.run(
            [
                soffice, "--headless", "--convert-to", "docx",
                "--outdir", str(doc_path.parent), str(doc_path),
            ],
            check=True, capture_output=True, timeout=120,
        )
    except subprocess.CalledProcessError as e:
        print(f"  ✗ soffice failed on {doc_path.name}: "
              f"{e.stderr.decode(errors='replace')[:160]}",
              file=sys.stderr)
        return False
    except subprocess.TimeoutExpired:
        print(f"  ✗ soffice timed out on {doc_path.name}", file=sys.stderr)
        return False
    if not docx_path.exists() or docx_path.stat().st_size < 1024:
        return False
    with open(docx_path, "rb") as fh:
        return fh.read(4) == b"PK\x03\x04"


# LibreOffice-converted .doc files prefix footnote bodies with the
# footnote-separator glyph, which arrives as "? " (literal question
# mark followed by space) once <w:t> text runs are stitched back
# together. Strip it so the corpus sees a clean body.
_LO_FN_PREFIX = re.compile(r"^\?\s*")
_WS = re.compile(r"\s+")


def collect_footnote_bodies(zf: zipfile.ZipFile) -> dict[str, str]:
    """Build { word_fn_id: body_text } for substantive footnotes only.

    Word reserves IDs -1 and 0 for the separator/continuation runs
    (w:type="separator" / "continuationSeparator"); we skip those.
    LibreOffice-converted docs leak a "? " separator into bodies; we
    strip it here."""
    try:
        tree = ET.parse(zf.open("word/footnotes.xml"))
    except KeyError:
        return {}
    bodies: dict[str, str] = {}
    for fn in tree.iter(f"{W}footnote"):
        if fn.get(f"{W}type"):    # separator/continuationSeparator → skip
            continue
        wid = fn.get(f"{W}id")
        parts = []
        for t in fn.iter(f"{W}t"):
            if t.text:
                parts.append(t.text)
        body = "".join(parts).strip()
        body = _LO_FN_PREFIX.sub("", body)
        body = _WS.sub(" ", body).strip()
        if body:
            bodies[wid] = body
    return bodies


def iter_docx_paragraphs(zf: zipfile.ZipFile):
    """Yield (text_with_§§FN§§<id>§§ placeholders, [word_fn_ids]) for
    every non-empty paragraph in word/document.xml. Order preserved."""
    tree = ET.parse(zf.open("word/document.xml"))
    for p in tree.iter(f"{W}p"):
        chunks: list[str] = []
        fn_ids_in_para: list[str] = []
        for elem in p.iter():
            tag = elem.tag
            if tag == f"{W}t":
                if elem.text:
                    chunks.append(elem.text)
            elif tag == f"{W}footnoteReference":
                wid = elem.get(f"{W}id")
                fn_ids_in_para.append(wid)
                chunks.append(f"§§FN§§{wid}§§")
            elif tag in (f"{W}br", f"{W}cr"):
                chunks.append("\n")
            elif tag == f"{W}tab":
                chunks.append("\t")
        text = "".join(chunks).strip()
        if text:
            yield text, fn_ids_in_para


def extract_doc(docx_path: Path) -> dict | None:
    """Return { paragraphs: {n: {inline_text, footnotes}}, total_fn_emitted }
    or None if footnotes.xml is missing / empty.

    Footnote N is assigned doc-wide in source-document order:
      first <w:footnoteReference> encountered → fn 1; second → fn 2; …
    The Word-internal w:id is just an opaque key into footnotes.xml."""
    with zipfile.ZipFile(docx_path) as zf:
        bodies = collect_footnote_bodies(zf)
        if not bodies:
            return None

        # First pass: assign sequential N to each w:id in document order.
        wid_to_n: dict[str, int] = {}
        next_n = 0
        # Re-walk the doc to capture w:id sequence (mirrored in iter below).
        tree = ET.parse(zf.open("word/document.xml"))
        for p in tree.iter(f"{W}p"):
            for elem in p.iter():
                if elem.tag == f"{W}footnoteReference":
                    wid = elem.get(f"{W}id")
                    if wid not in wid_to_n and wid in bodies:
                        next_n += 1
                        wid_to_n[wid] = next_n

        if not wid_to_n:
            return None

        # Second pass: yield each ¶ with its inline text + fn ids.
        # Two output buckets:
        #   - paragraphs[n]  text starts with "N. ", anchored.
        #   - extras[]       fn-bearing ¶ without leading number;
        #                    Word stores numbering in <w:numPr> for
        #                    these (rare in GCs but possible).
        #                    apply_sp_footnotes.py aligns extras to
        #                    corpus paragraphs by content prefix.
        paragraphs: dict[int, dict] = {}
        extras: list[dict] = []
        seq_in_doc = 0
        # Unlike SP extractor: emit EVERY numbered ¶ even with
        # zero fn refs. apply_gc_footnotes needs to OVERWRITE
        # corpus paragraphs that got bogus PDF-extracted markers
        # (e.g. CEDAW/C/GC/31 ¶13), which means it must
        # know "docx says this ¶ has zero fns".
        for text, fn_ids in iter_docx_paragraphs(zf):
            seq_in_doc += 1
            inline = text
            seen_fns: list[int] = []
            for wid in fn_ids:
                seq = wid_to_n.get(wid)
                if seq is None:
                    inline = inline.replace(f"§§FN§§{wid}§§", "", 1)
                    continue
                inline = inline.replace(f"§§FN§§{wid}§§", f"[[fn:{seq}]]", 1)
                seen_fns.append(seq)
            inline = re.sub(r"[ \t ]+", " ", inline).strip()
            footnotes_for_para = [
                {"n": seq, "text": bodies[wid]}
                for wid, seq in sorted(wid_to_n.items(), key=lambda kv: kv[1])
                if seq in seen_fns
            ]
            m = LEADING_NUM.match(inline)
            if m:
                n = int(m.group(1))
                inline = inline[m.start():]
                paragraphs[n] = {
                    "inline_text": inline,
                    "footnotes": footnotes_for_para,
                }
            elif seen_fns:
                # Non-numbered ¶s only kept when fn-bearing.
                extras.append({
                    "seq": seq_in_doc,
                    "inline_text": inline,
                    "footnotes": footnotes_for_para,
                })
    return {
        "paragraphs": paragraphs,
        "extras": extras,
        "total_fn": len(wid_to_n),
        "wid_to_n": wid_to_n,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--doc", help="Process only this docId.")
    ap.add_argument("--no-fetch", action="store_true",
                    help="Skip downloads — use cached docx files only.")
    ap.add_argument("--force", action="store_true",
                    help="Re-download even if cached.")
    args = ap.parse_args()

    DOCX_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Extracting SP footnotes (docx-first ground-truth path).")
    print(f"  cache dir: {DOCX_DIR.relative_to(REPO)}")
    print(f"  output:    {OUT_JSON.relative_to(REPO)}")
    print()

    with DOCS_JSON.open() as f:
        docs = json.load(f)
    sp_docs = [d for d in docs if d.get("type") == "gc"]
    if args.doc:
        sp_docs = [d for d in sp_docs if d["docId"] == args.doc]
    print(f"  GC docs to process: {len(sp_docs)}")

    out: dict = {}
    if OUT_JSON.exists():
        try:
            out = json.loads(OUT_JSON.read_text())
        except Exception:
            out = {}

    n_ok = n_no_docx = n_no_fn = n_no_paras = 0
    n_native = n_converted = 0
    total_paras = 0
    total_fns = 0

    for i, d in enumerate(sp_docs, start=1):
        doc_id = d["docId"]
        # GC catalogue carries `signature` (sometimes joint with em-dash,
        # e.g. CEDAW/C/GC/31/Rev.1–CRC/C/GC/18/Rev.1) and `ohchrSymbol`
        # (simpler primary, e.g. CEDAW/C/GC/31/REV.1). documents.un.org
        # accepts ohchrSymbol but NOT the joint form, so probe in that
        # order. Fallback also strips an em-dash to take just the part
        # before it.
        candidates = []
        for raw in (d.get("ohchrSymbol"), d.get("signature"), doc_id):
            if not raw or raw in candidates: continue
            candidates.append(raw)
            # If em-dash present, also try the leading half by itself.
            if "–" in raw:
                head = raw.split("–", 1)[0]
                if head not in candidates: candidates.append(head)
        docx_path = DOCX_DIR / f"{doc_id}.docx"
        doc_path = DOCX_DIR / f"{doc_id}.doc"

        kind = "miss"
        if not args.no_fetch:
            for sym in candidates:
                kind = fetch_docx(sym, docx_path, force=args.force)
                time.sleep(0.3)
                if kind != "miss":
                    break
        else:
            # use cache
            if docx_path.exists():
                with open(docx_path, "rb") as fh:
                    if fh.read(4) == b"PK\x03\x04":
                        kind = "docx"
            elif doc_path.exists():
                kind = "doc"

        if kind == "doc":
            # Convert legacy .doc → .docx via textutil (macOS).
            if not docx_path.exists() or args.force:
                if not convert_doc_to_docx(doc_path, docx_path):
                    n_no_docx += 1
                    print(f"  [{i:3d}/{len(sp_docs)}] {doc_id:24s}  ✗ doc→docx conversion failed")
                    continue
            n_converted += 1
        elif kind == "docx":
            n_native += 1
        else:
            n_no_docx += 1
            print(f"  [{i:3d}/{len(sp_docs)}] {doc_id:24s}  no docx ({kind})")
            continue

        if not docx_path.exists():
            n_no_docx += 1
            continue

        try:
            result = extract_doc(docx_path)
        except Exception as e:
            print(f"  [{i:3d}/{len(sp_docs)}] {doc_id:24s}  ✗ extract failed: {e}",
                  file=sys.stderr)
            continue

        if result is None:
            n_no_fn += 1
            print(f"  [{i:3d}/{len(sp_docs)}] {doc_id:24s}  no footnotes")
            continue

        if not result["paragraphs"] and not result.get("extras"):
            n_no_paras += 1
            print(f"  [{i:3d}/{len(sp_docs)}] {doc_id:24s}  fn={result['total_fn']:3d}  "
                  f"no ¶ to attach (no numbered match, no extras)")
            continue

        out[doc_id] = {
            "source": "docx",
            "signature": candidates[0] if candidates else doc_id,
            "paragraphs": {str(n): info for n, info in result["paragraphs"].items()},
            "extras": result.get("extras") or [],
        }
        n_ok += 1
        total_paras += len(result["paragraphs"])
        total_fns += result["total_fn"]
        n_extras_doc = len(result.get("extras") or [])
        print(f"  [{i:3d}/{len(sp_docs)}] {doc_id:24s}  "
              f"fn={result['total_fn']:3d}  ¶matched={len(result['paragraphs']):3d}  "
              f"extras={n_extras_doc:3d}")

    print()
    print(f"  ok:                  {n_ok:3d}   (native docx={n_native}, converted .doc={n_converted})")
    print(f"  no docx / unsupp:    {n_no_docx:3d}")
    print(f"  docx but no fn:      {n_no_fn:3d}")
    print(f"  fn but no ¶ match:   {n_no_paras:3d}")
    print(f"  total paragraphs:    {total_paras:,}")
    print(f"  total footnotes:     {total_fns:,}")

    # Compact JSON — 4MB compact vs 4.4MB indented; size matters in git.
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"\n  ✅ wrote {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
