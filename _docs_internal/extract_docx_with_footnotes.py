#!/usr/bin/env python3
"""Walk a .docx and emit each paragraph with inline footnote markers
shown as [[fn:N]] at exactly the position(s) where Word stored them.

This gives us the GROUND TRUTH for footnote placement against which we
can validate (or correct) the [[fn:N]] markers in the corpus."""

import sys
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def iter_paragraphs(docx_path: Path):
    """Yield (paragraph_text, footnote_ids_in_order) tuples.

    For each <w:p>, walks <w:r> runs; <w:t> contributes text, and a
    <w:footnoteReference w:id="N"/> contributes a `[[fn:<seq>]]` marker
    (where seq is incremented per paragraph; we resolve the mapping from
    Word's footnote ID → our sequential ¶-local fn number afterwards)."""
    with zipfile.ZipFile(docx_path, "r") as zf:
        with zf.open("word/document.xml") as f:
            tree = ET.parse(f)
        try:
            with zf.open("word/footnotes.xml") as f:
                fn_tree = ET.parse(f)
        except KeyError:
            fn_tree = None

    # Build mapping from Word footnote-id → footnote text (for verification)
    fn_text_by_id = {}
    if fn_tree is not None:
        for fn in fn_tree.iter(f"{W_NS}footnote"):
            wid = fn.get(f"{W_NS}id")
            text_parts = []
            for t in fn.iter(f"{W_NS}t"):
                if t.text:
                    text_parts.append(t.text)
            fn_text_by_id[wid] = "".join(text_parts).strip()

    for p in tree.iter(f"{W_NS}p"):
        chunks = []
        fn_ids_in_order = []
        for elem in p.iter():
            tag = elem.tag
            if tag == f"{W_NS}t":
                if elem.text:
                    chunks.append(elem.text)
            elif tag == f"{W_NS}footnoteReference":
                wid = elem.get(f"{W_NS}id")
                fn_ids_in_order.append(wid)
                # placeholder — we'll renumber per paragraph below
                chunks.append(f"§§FN§§{wid}§§")
            elif tag == f"{W_NS}br" or tag == f"{W_NS}cr":
                chunks.append("\n")
            elif tag == f"{W_NS}tab":
                chunks.append("\t")
        text = "".join(chunks)
        # Renumber the §§FN§§<wid>§§ markers as [[fn:k]] sequential per paragraph
        seq = 0
        out = []
        i = 0
        while i < len(text):
            if text[i:i + 7] == "§§FN§§":
                end = text.find("§§", i + 7)
                if end != -1:
                    seq += 1
                    out.append(f"[[fn:{seq}]]")
                    i = end + 2
                    continue
            out.append(text[i])
            i += 1
        rendered = "".join(out)
        yield rendered, fn_ids_in_order, fn_text_by_id


def main():
    if len(sys.argv) < 2:
        print("usage: extract_docx_with_footnotes.py <file.docx> [--paragraph N]")
        sys.exit(1)
    path = Path(sys.argv[1])
    target = None
    if "--paragraph" in sys.argv:
        target = int(sys.argv[sys.argv.index("--paragraph") + 1])

    pidx = 0
    for text, fn_ids, fn_bodies in iter_paragraphs(path):
        text = text.strip()
        if not text:
            continue
        # Skip leading paragraphs that are headings / metadata; the
        # numbered substantive ¶s start where text begins with "1." (or
        # similar). We just print every non-empty paragraph and let the
        # caller search for the right one.
        pidx += 1
        if target is None or pidx == target:
            print(f"=== rendered paragraph #{pidx} ===")
            print(text[:1200])
            print()
            if fn_ids:
                print("  footnote IDs (Word internal):", fn_ids)
                for wid in fn_ids:
                    body = fn_bodies.get(wid, "(no body)")
                    print(f"    fn id={wid}: {body[:200]}")
            print()
            if target is not None:
                return


if __name__ == "__main__":
    main()
