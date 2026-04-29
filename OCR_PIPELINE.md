# OCR pipeline for scanned jurisprudence PDFs

This pipeline is for the old scanned Treaty Body jurisprudence PDFs that have no embedded text. It is intentionally quality-first: OCR output is stored separately, audited, and only then allowed into the paragraph-level JSON pipeline.

## Current CCPR target

After the CCPR import, the remaining OCR target is:

- 170 English scanned CCPR PDFs
- 1,476 PDF pages
- mostly older Human Rights Committee decisions from the 1980s and 1990s

The pipeline is generated from the live local OHCHR dump plus `jurisprudence_info.json`, so it only targets cases not already extracted.

## Dependencies

Required command-line tools:

```bash
pdftoppm
tesseract
```

Current local status:

- `pdftoppm` is available
- `tesseract` is available with `eng`, `osd`, `snum`
- `ocrmypdf` is not required

Python dependencies already used by the project:

- `PyMuPDF`
- `Pillow`

## Files

Source script:

```bash
python3 ocr_jurisprudence.py
```

Generated local OCR artefacts:

```text
ocr_jurisprudence/
  queue_ccpr.jsonl
  audit_ccpr.json
  ccpr/<docId>/
    ocr.json
    document.txt
    page-001.txt
    page-002.txt
```

Generated OCR artefacts are local working files and should not be committed unless we intentionally decide to publish OCR provenance.

## Workflow

1. Build the OCR queue:

```bash
python3 ocr_jurisprudence.py plan --treaty CCPR
```

2. Run a small sample:

```bash
python3 ocr_jurisprudence.py run --treaty CCPR --limit 5
```

3. For a difficult page/document, compare the full candidate set:

```bash
python3 ocr_jurisprudence.py experiment --treaty CCPR --symbol CCPR/C/37/D/244/1987
```

This writes `ocr_jurisprudence/experiments/<docId>/experiment.json` and
`best_document.txt` for side-by-side review.

4. Audit quality:

```bash
python3 ocr_jurisprudence.py audit --treaty CCPR
```

5. Run the full queue:

```bash
python3 ocr_jurisprudence.py run --treaty CCPR
python3 ocr_jurisprudence.py audit --treaty CCPR
```

6. Re-ingest CCPR after reviewing OCR quality:

```bash
python3 ingest_jurisprudence.py --treaty CCPR
python3 build_jurisprudence_shards.py --all
```

## Quality policy

Each page is rendered at 400 DPI and OCRed with multiple profiles. The default
mode is `quality`:

- `fast`: autocontrast image, Tesseract `--psm 3` and `--psm 6`
- `quality`: autocontrast + sharpened image, Tesseract `--psm 3`, `--psm 4`, and `--psm 6`
- `max`: quality candidates plus thresholded image and `--psm 11`, intended for experiments rather than full production runs

The pipeline keeps the page result with the better confidence/text score. The
score uses:

- mean word confidence
- low-confidence word ratio
- text volume
- paragraph-order penalty, so an output that moves `7.` before `6.2.` loses even if raw confidence is slightly higher

Tesseract also receives a small project word list from
`ocr_resources/tess_user_words_eng.txt`, covering recurring UN, treaty-body,
country, and legal vocabulary.

After OCR, the script applies a narrow set of safe post-corrections for recurring
legacy-scan errors, for example `Optionel Prcetocol` to `Optional Protocol`,
`Racision` to `Decision`, and dashed standalone page footers such as `-135-`.
The number of applied fixes is stored as `correctionCount`.

For each page and document it stores:

- mean word confidence
- low-confidence word ratio
- word count
- character count
- chosen OCR profile and preprocessing variant
- safe correction count
- alternative profile metrics

Document statuses:

- `pass`: good enough for automated ingestion
- `review`: usable but needs human spot-checking
- `fail`: do not ingest

Default quality gates:

- mean confidence at least `70`
- low-confidence ratio no more than `0.35`
- minimum text volume checks
- expected HRC/communication vocabulary checks

## Ingestion behavior

`ingest_jurisprudence.py` now looks for sidecar OCR at:

```text
ocr_jurisprudence/<treaty>/<docId>/ocr.json
```

Only OCR records with status `pass` or `review` are eligible. If a scanned PDF has no embedded text and a sidecar OCR exists, the OCR text is parsed with the same jurisprudence paragraph parser and can enter the dataset as `sourceFormat: "pdf_ocr"`.

## Review before publication

Before publishing OCR-expanded CCPR:

1. Read `ocr_jurisprudence/audit_ccpr.json`.
2. Spot-check a sample from `pass`, all or most `review`, and every `fail` that looks recoverable.
3. Re-ingest and verify:

```bash
python3 ingest_jurisprudence.py --treaty CCPR
python3 build_jurisprudence_shards.py --all
```

4. Run structural checks:

- no missing source JSON
- paragraph counts match
- new `sourceFormat: "pdf_ocr"` count is plausible
- shard sizes remain acceptable

OCR output is not a silent replacement for official text. It should be treated as a documented recovery layer for scanned legacy PDFs.
