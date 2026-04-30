# Footnote restoration — migration plan
_(v19.8 · 2026‑04‑30 · last batch: P2)_

This document records how the footnote infrastructure was wired in v19.8 and
the work still pending to backfill footnote DATA across the existing 186-doc
corpus.

## Status snapshot

| Batch | Date | Docs | Footnotes | Cumulative |
|---|---|---|---|---|
| Infra + CAT/OP/GC/1 | 2026-04-30 | 1 | 63 | 1 doc · 63 fn |
| P0 | 2026-04-30 | 5 | 339 | 6 docs · 565 fn |
| **P2 (mass pass)** | **2026-04-30** | **37** | **1,762** | **43 docs · 2,327 fn** |

23 % of GCs (43 / 187) now carry footnotes. **Pending: 144 docs, broken down below.**

## What v19.8 ships

| Layer | Change | Backward-compatible? |
|---|---|---|
| Schema | Paragraphs gain optional `footnotes: [{n, text}]`; body `text` may carry `[[fn:N]]` markers. | Yes — paragraphs without footnotes are unchanged. |
| Build (`build_corpus.py`) | Reads `Footnotes` field from source items if present; sanity-checks `[[fn:N]]` ↔ `footnotes[].n`. | Yes — silent if source lacks the field. |
| Renderer (`paintDocReaderBody`) | `[[fn:N]]` → clickable `<button class="fn-marker">` with click-to-popover (singleton, ARIA-compliant, Escape closes). | Yes — paragraphs without markers render as before. |
| Search snippets | Markers stripped before snippet generation; "match in citation" pill appears when query hit lives only in footnote text. | Yes — no markers in current data → no pill. |
| FlexSearch index | Second field `fnText` indexes concatenated footnote bodies; AST verifier extended to consider footnote text. | Yes — `fnText: ''` for paragraphs without footnotes. |
| Tests | 7 specs (`tests/footnotes.spec.ts`) + 1 real-data smoke (CAT/OP/GC/1). | n/a |

## Done (real footnote data)

- **CAT/OP/GC/1** ingested from the OHCHR DOCX with all 63 footnotes preserved
  (`extract_docx_with_footnotes.py` → `json_data_gc_labeled/Annotated_CAT_OP_GC1_art4.json`).
- **P0 batch** (5 docs): CMW/C/GC/6, E/C.12/GC/27, CMW/C/GC/7+CERD/C/GC/38,
  CMW/C/GC/8+CERD/C/GC/39, CEDAW/C/GC/30/Add.1 — extracted from local PDFs via
  the new `extract_pdf_with_footnotes.py`.
- **P2 mass pass** (37 docs with footnotes, 64 successful extractions overall):
  bulk run of `p2_batch_runner.py` against the 160 standalone GC candidates.
  Picked the format (DOCX vs PDF) whose paragraph count was closest to the
  existing source. Coverage spans every committee.

## P3 backlog (144 docs)

The runner produced a per-doc result log at
`/tmp/p2_batch/p2_run_log.json` with one of these statuses:

| Status | Count | What it means | Path forward |
|---|---|---|---|
| `no-en-url` | 45 | OHCHR landing page has no downloadable English file | These are mostly the early `annotated-cedaw-gr*` and `annotated-cerd-gr*` series whose source documents existed only in committee report compilations (e.g. A/40/18, A/49/38). Need a per-committee compilation extractor that splits an annual report PDF into individual GR chapters. ~4 h work + per-doc QA. |
| `extract-empty` | 40 | File downloaded but no numbered paragraphs found | The downloaded file is typically the full annual report containing the GC as a chapter (e.g. `a-53-44` is the entire 1997 CAT annual report — GC1 is one section). Same fix as `no-en-url`: chapter-level splitting. |
| `divergent:>30%` | 12 | Extraction succeeded but ¶ count too far from existing source. **Source NOT overwritten** by the runner. | Per-doc tuning. Several known cases:<br>· `crc-c-gc-14`, `crc-c-gc-15`, `crc-c-gc-16` (CRC GCs with embedded sub-paragraphs the line-aware splitter doesn't handle)<br>· `e-c-12-2002-11`, `e-c-12-gc-26`, `e-1998-22` (CESCR docs with non-standard paragraph numbering)<br>· The OHCHR `Download.aspx` for these may also be returning the wrong file (annual report vs. GC). |
| `HRI/GEN/1` | 21 | Bundled compilation series (older CCPR GCs only published in HRI/GEN/1/Rev.9) | Full compilation PDF is downloadable; needs page-range splitting to extract the per-GC chapters. Lowest scholarly priority since most modern citations point at the post-Rev.1 standalone versions. |
| Already done | 43 | Footnotes present | — |
| **Total GC corpus** | **187** | | |

## When you re-run the P2 pass

The runner is *idempotent* — it caches downloads under `/tmp/p2_batch/{docId}/`
and writes one backup per source per "run version" (`*.json.bak.v19_8_p2`,
`*.json.bak.v19_8_p3`, etc.). You can safely:

```bash
rm -rf /tmp/p2_batch                                  # full re-fetch
python3 p2_batch_runner.py --only DOCID1,DOCID2       # spot-check
python3 p2_batch_runner.py --limit 10 --dry-run       # preview only
```

## Pending (181 docs)

The remaining 186 GCs were originally extracted via `clean_extract.py` with
its footnote-stripping pipeline. To restore footnotes we need to re-extract
from source. Options, in increasing order of completeness:

### Option A — DOCX-only re-extraction (recommended for new GCs)

For every doc that has a DOCX on the OHCHR docstore (most post-2010
documents do), use `extract_docx_with_footnotes.py`:

```bash
# 1. fetch the DOCX (English version) from the OHCHR landing page
curl -sL "https://docstore.ohchr.org/SelfServices/FilesHandler.ashx?enc=…" \
    -o cmw_gc_5.docx

# 2. extract paragraphs + footnotes
python3 extract_docx_with_footnotes.py cmw_gc_5.docx \
    mysite_pythonanywhere/json_data/Annotated_CMW_GC5.json --summary

# 3. rebuild
python3 build_corpus.py
```

Spot-check the first/last paragraph against the source PDF (the script
prints both with `--summary`). Numbering shifts and embedded headers are
the most common per-doc surprises.

### Option B — PDF re-extraction (fallback for legacy docs)

Older General Comments (HRI/GEN/1 series, pre-2005) often only ship as PDFs
where footnotes use a horizontal-rule separator and live in a column-bottom
zone that pdfminer flattens unreliably. `clean_extract.py` currently runs
in *strip mode*; a `--keep-footnotes` flag would need to:

1. Detect the `____` separator block (already done, see Rule B in
   `_clean_page_text`) but **capture** the text after it instead of
   discarding.
2. Extract leading-digit footnote markers (Rule D) but record their
   positions instead of stripping.
3. Reconcile body markers ↔ footnote bodies by matching numbers.

Estimated cost: ½–1 day to write the flag, plus per-document QA. Worth
deferring until DOCX coverage is exhausted.

### Option C — Manual annotation (one-offs)

For high-impact docs where automated extraction misfires (e.g. CCPR GC32
fair trial — the most-cited general comment in the corpus), it's faster to
hand-author the footnotes JSON than fight the extractor. The schema is
trivial:

```json
[
  { "ID": 33, "Labels": ["Persons deprived of their liberty"],
    "Text": "Adequate facilities…[[fn:1]] …Exculpatory material…",
    "Footnotes": [
      { "n": 1, "text": "Communication No. 1158/2003, Blanco Domínguez v. Spain, para. 9.3." }
    ]
  }
]
```

## Triage order (suggested)

| Priority | Bucket | Why |
|---|---|---|
| P0 | The 5 docs in `new_gcs_pdf/` (CMW GC6/7/8, CESCR GC27, CEDAW GC30 Add.1) | Already have local PDFs; modern DOCXes available; immediate UX payoff. |
| P1 | The 10 most-clicked GCs (CCPR GC32, CRC GC14, etc. — pull from `_LS.bookmarks` analytics if user-test data is available) | Highest reader-facing value. |
| P2 | All remaining post-2010 GCs (DOCX path) | Bulk pass through Option A. |
| P3 | Legacy HRI/GEN/1 docs (PDF path) | Implement Option B; hardest, lowest scholarly priority. |

## Validation

After every batch:

```bash
# 1. Build
python3 build_corpus.py

# 2. Audit — must show 0 critical findings
python3 docs/_audit/data_audit_gc.py

# 3. Tests — must pass clean
cd /Users/lszoszk/Desktop/generalcomments-repo
npx playwright test tests/footnotes.spec.ts --project=chromium
```

The build script's diagnostic report (`docs/build_report.txt`) lists
paragraphs whose `[[fn:N]]` markers don't have a matching `Footnotes`
entry — fix those before merging.

## UX recap (what the user sees)

- **Document reader.** Footnote markers appear as a small superscript
  number (¹) in the paragraph body, in garnet. Click → popover with the
  footnote body, Escape or click-outside closes. Below 600 px viewport
  the popover becomes a bottom sheet.
- **Search results.** Markers are stripped from snippets. When the query
  matches only the footnote text (not the visible snippet), a small
  `◇ match in citation` pill appears in the result row's headline.
- **Search index.** Footnote text is searchable (paragraph hits via
  citation are surfaced) but does not score higher than body matches.
- **Backwards compatible.** Paragraphs without footnotes (currently 100 %
  of the corpus minus CAT/OP/GC/1) render exactly as v19.7.

## Files of record

| File | Role |
|---|---|
| `extract_docx_with_footnotes.py` | DOCX→JSON extractor (Option A). |
| `build_corpus.py` | Preserves `Footnotes` field, validates marker↔text consistency. |
| `docs/assets/app.js` | Renders markers, popover, search hide, citation pill. |
| `docs/assets/app.css` | `.fn-marker`, `.fn-popover`, `.match-in-citation`. |
| `tests/footnotes.spec.ts` | F1–F7 specs (synthetic + CAT/OP/GC/1 real data). |
| `docs/_audit/data_audit_gc.py` | CAT-OP added to known-committee enum. |
