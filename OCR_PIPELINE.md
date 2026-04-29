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

3. Audit quality:

```bash
python3 ocr_jurisprudence.py audit --treaty CCPR
```

4. Run the full queue:

```bash
python3 ocr_jurisprudence.py run --treaty CCPR
python3 ocr_jurisprudence.py audit --treaty CCPR
```

5. Re-ingest CCPR after reviewing OCR quality:

```bash
python3 ingest_jurisprudence.py --treaty CCPR
python3 build_jurisprudence_shards.py --all
```

## Quality policy

Each page is rendered at 400 DPI and OCRed twice:

- Tesseract `--psm 3` for automatic layout
- Tesseract `--psm 6` for single-block text

The pipeline keeps the page result with the better confidence/text score. It stores:

- mean word confidence
- low-confidence word ratio
- word count
- character count
- chosen OCR profile
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
