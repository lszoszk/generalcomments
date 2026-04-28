#!/usr/bin/env python3
"""
Robust paragraph extractor for UN treaty body / SP PDFs.

Replaces the ad-hoc regex cleanup in ingest_new_gcs.py / ingest_sp_mandate.py.
Uses PyMuPDF's block-level layout (get_text("blocks")) to:

  1. Drop running headers (y0 < TOP_MARGIN)        — e.g., "CEDAW/C/GC/30/Add.1"
  2. Drop page footers   (y0 > BOTTOM_MARGIN)      — e.g., "26-02915  2/24"
  3. Detect the underscore-only separator block    — narrow, contains only `_`
  4. Drop every block AFTER the separator on the same page (footnote text)

Pages are processed independently so the footer of page N never bleeds into
the body of page N+1 (the bug that put `26-02915 2/24` in the middle of a
sentence).

Pages then concatenate, soft-wraps are repaired, and the existing
`^\\s*(\\d{1,3})\\.\\s+` regex segments paragraphs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import fitz  # PyMuPDF

# A4 = 595x842 pt at 72 dpi. UN docs use slightly different margins per
# committee but these thresholds work for every PDF we ingested in v7+v10.
TOP_MARGIN_Y    = 70    # blocks with y0 < 70 are running headers
BOTTOM_MARGIN_Y = 720   # blocks with y0 > 720 are page footers


def _is_separator_block(text: str) -> bool:
    """A footnote separator block consists almost entirely of underscores
    plus whitespace.  Real body text never matches."""
    s = text.strip()
    if len(s) < 5:
        return False
    underscores = s.count('_')
    return underscores >= 5 and underscores / max(1, len(s.replace(' ', '').replace('\n', ''))) > 0.7


# Footnote text typically starts with a small number followed by space + body
# (e.g., "8  See Universal Declaration...", "1 See the background paper..."
# "10  Ibid., para. 11."). The "N  text" pattern with two spaces is the
# fingerprint we use when no underscore separator is present.
_FOOTNOTE_LEAD = re.compile(r'^\s*\d{1,3}\s+[A-Z]')


def _clean_page_text(page: fitz.Page) -> str:
    """Return the page's body text with headers, footers and footnotes stripped.

    Detection strategy (combined — first applicable rule wins):
      A) Block is in the running-header or page-footer band (y outside
         [TOP_MARGIN_Y, BOTTOM_MARGIN_Y])           → drop.
      B) Block is the underscore-only separator     → drop AND drop every
         block after it (footnotes always follow).
      C) No separator block found (some UN PDFs draw the footnote rule as
         a graphic rather than text). Fallback: identify the dominant body
         x-indent for this page; any block whose x0 differs and whose first
         line matches the "N <text>" footnote-marker pattern → treat as
         footnote AND drop every following block.
    """
    blocks = page.get_text("blocks")

    # First pass: filter by y-band, keep raw block tuples.
    in_band = []
    for b in blocks:
        x0, y0, x1, y1, text, *_ = b
        if y0 < TOP_MARGIN_Y or y0 > BOTTOM_MARGIN_Y:
            continue
        if not (text and text.strip()):
            continue
        in_band.append((y0, x0, text))

    if not in_band:
        return ''

    in_band.sort(key=lambda t: (t[0], t[1]))

    # Compute the dominant body x-indent (mode) for fallback detection.
    from collections import Counter
    x_counts = Counter(round(x0) for _, x0, _ in in_band)
    body_x = x_counts.most_common(1)[0][0]

    # Walk in reading order, cut on the first footnote signal.
    body_blocks = []
    for y0, x0, text in in_band:
        # Rule B: underscore separator standalone
        if _is_separator_block(text):
            break
        # Rule C: footnote-style block (different x-indent + footnote lead)
        if (abs(round(x0) - body_x) >= 8
            and y0 > 350
            and _FOOTNOTE_LEAD.match(text)):
            break
        # Rule D: PDF sometimes inlines the horizontal rule INSIDE a body
        # block, so the body text ends with '...as a \n__________________'.
        # Trim that off rather than dropping the whole block. We're greedy:
        # everything from the first long underscore run onwards is junk.
        cleaned = re.sub(r'_{5,}.*\Z', '', text, flags=re.DOTALL).strip()
        if cleaned:
            body_blocks.append(cleaned)

    return '\n'.join(body_blocks)


def extract_paragraphs(pdf_path: Path) -> list[dict]:
    """Extract numbered paragraphs from a UN PDF.  Reuses the same output
    shape as the existing ingest scripts: list of {ID, Labels, Text}."""
    doc = fitz.open(pdf_path)
    cleaned_pages = [_clean_page_text(p) for p in doc]
    doc.close()
    text = '\n'.join(cleaned_pages)

    # Repair PDF artefacts that survive even after block-level filtering.
    text = re.sub(r'-\n', '', text)                     # hyphenated line break
    text = re.sub(r'(?<=[a-z,])\n(?=[a-z(])', ' ', text)  # mid-sentence wrap
    # Strip lone footnote-reference digits stuck to a sentence end:
    #   "...emissions.33 If the current pace..." → "...emissions. If the current pace..."
    # We only match a digit AT THE END of a sentence (right after . ! ? "), not
    # bare digits inline (which could be article numbers).
    text = re.sub(r'(?<=[.!?”\)])\s*\d{1,3}(?=\s+[A-Z])', '', text)
    text = re.sub(r'[ \t]+', ' ', text)

    # Paragraph segmentation by the leading "N. " marker.
    paragraphs = []
    para_split = re.split(r'(?m)^\s*(\d{1,3})\.\s+', text)
    if len(para_split) >= 3:
        for i in range(1, len(para_split) - 1, 2):
            num = para_split[i]
            body = para_split[i + 1].strip()
            if len(body) < 30:
                continue
            body = re.sub(r'\s+', ' ', body).strip()
            paragraphs.append({'ID': f'{num}.', 'Labels': [], 'Text': body})
    else:
        for i, chunk in enumerate(re.split(r'\n\s*\n', text), 1):
            chunk = chunk.strip()
            if len(chunk) > 50:
                paragraphs.append({
                    'ID': f'{i}.', 'Labels': [],
                    'Text': re.sub(r'\s+', ' ', chunk),
                })
    return paragraphs


# ---------------------------------------------------------------------------
# CLI: re-extract a list of PDFs and overwrite the labelled JSON, preserving
# any labels that were applied to paragraphs whose ID matches.
# ---------------------------------------------------------------------------
LABEL_PATTERNS = None  # imported lazily from ingest_sp_mandate.py to avoid duplication


def _load_label_patterns():
    """Reuse the labelling patterns from ingest_sp_mandate.py rather than
    keeping a third copy.  Loaded lazily so this module is import-cheap."""
    global LABEL_PATTERNS
    if LABEL_PATTERNS is not None:
        return LABEL_PATTERNS
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ingest_sp_mandate import COMPILED_LABELS  # noqa
    LABEL_PATTERNS = COMPILED_LABELS
    return LABEL_PATTERNS


def label_paragraph(text: str) -> list[str]:
    pats = _load_label_patterns()
    found = []
    for label, ps in pats:
        if any(p.search(text) for p in ps):
            found.append(label)
    return sorted(set(found))


def reingest(pdf_path: Path, out_json: Path) -> dict:
    """Re-extract paragraphs from `pdf_path` and write them to `out_json`,
    applying labels.  Returns a small summary dict."""
    paras = extract_paragraphs(pdf_path)
    for p in paras:
        p['Labels'] = label_paragraph(p['Text'])
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(paras, ensure_ascii=False, indent=2))
    n_lbl = sum(1 for p in paras if p['Labels'])
    return {'paragraphs': len(paras), 'labelled': n_lbl}


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pdf', required=True, help='PDF file to re-extract')
    ap.add_argument('--out', required=True, help='Output JSON path')
    args = ap.parse_args()
    s = reingest(Path(args.pdf), Path(args.out))
    print(f'  ✓ {s["paragraphs"]} paragraphs ({s["labelled"]} labelled)')
