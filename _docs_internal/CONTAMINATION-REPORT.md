# Cross-doc text contamination

Detected by `_docs_internal/audit_cross_doc_contamination.py`.
Each pair below shares ≥200 contiguous characters of paragraph text.
These need re-extraction from the authoritative OHCHR source PDFs in
the next ingest batch — the splitter cannot fix them from corpus.json
alone because the wrong-doc text is already serialised.

Pairs found: **4**

| Doc A | Doc B |
| --- | --- |
| `a-41-38` | `annotated-cedaw-gr2-reporting` |
| `a-49-18` | `annotated-cerd-gr17-national-institutions` |
| `annotated-cedaw-gr10-tenth-anniversary` | `annotated-cedaw-gr9-statisticaldata` |
| `annotated-cerd-gr16-article9` | `annotated-cerd-gr17-national-institutions` |

## How to fix

For each affected doc, re-extract paragraph text from the OHCHR PDF (link is on each `documents.json` record), drop the bogus paragraph(s), and re-run `_docs_internal/resplit_gc_paragraphs.py` to re-derive preamble + items. The dossier metadata fields (`name`, `signature`, `committee` etc.) are correct — only the paragraph body needs replacing.