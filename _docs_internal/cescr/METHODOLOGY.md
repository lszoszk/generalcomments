# CESCR jurisprudence — sourcing methodology and coverage notes

*Last updated: 2026-05-08 (v19.53)*

This document explains how the **Committee on Economic, Social and Cultural
Rights** (CESCR) jurisprudence corpus was assembled, what was included, what
was **deliberately not included** because no public source carries it, and how
to verify or extend the coverage.

The pipeline lives at:

- `_docs_internal/cescr/extract_cescr.py` — discovery + docx fetch + OOXML walk
- `_docs_internal/cescr/apply_cescr.py` — JUR shard + catalogue stitching
- `_docs_internal/cescr/case_list.json` — discovery output (247 symbols)
- `_docs_internal/cescr/cescr.json` — extraction output (147 docs)
- `docs/jur/shards/jur_CESCR.json` — paragraph payload served to the SPA

---

## Sources, in order of preference

The corpus follows the same **docx-first** principle adopted in the SP
footnote work (v19.52). DOCX is the ground truth — Word's
`<w:footnoteReference>` element fixes inline marker placement that PDFs lose
and `pdftotext` routinely mangles. PDFs are not used for CESCR ingestion.

1. **`documents.un.org/api/symbol/access?s=<symbol>&l=en&t=docx`** — the UN
   Documentation Centre's content endpoint. Native DOCX for everything
   published since approximately 2015; pre-2015 responses arrive as Word
   97–2003 `.doc` (OLE compound binary) and are converted to DOCX with
   LibreOffice headless (`soffice --headless --convert-to docx`).
   `textutil` was tested and rejected: it converts the body but drops
   the `<w:footnoteReference>` runs. LibreOffice preserves them.

2. **`tbinternet.ohchr.org/_layouts/15/treatybodyexternal/Download.aspx`** —
   used for **discovery only** (paginated TBSearch) and as a fallback file
   source. In practice, when this endpoint serves a different file from
   `documents.un.org` it carries the same content under a different filename
   convention; cross-checking confirmed no additional decisions are
   recoverable here that aren't already on `documents.un.org`.

3. **`juris.ohchr.org`** — Blazor server SPA, no public REST endpoint.
   Catalog data we use comes via TBSearch HTML scraping rather than this
   surface.

---

## Discovery

`tbinternet.ohchr.org/_layouts/15/treatybodyexternal/TBSearch.aspx?Lang=en
&TreatyID=9&DocTypeID=17` is the OHCHR Treaty Body Database's paginated
listing of CESCR jurisprudence-type documents. Each page returns ~10 rows
through ASP.NET RadGrid pagination (`__EVENTTARGET=…radResultsGrid`,
`__EVENTARGUMENT=FireCommand:…;Page;Next` with full `__VIEWSTATE` round-trip).

Iterating to the end of pagination yielded **247 unique
`E/C.12/<sess>/D/<n>/<yr>` symbols** spanning sessions 55–79 (2014–2025).
Each row carries: title, treaty, country, symbol(s), and publication date.
Some titles bundle multiple comm-numbers under one decision document (eg
*"Communications Nº 258/2022, 259/2022, 263/2022, 270/2022, 273/2022 and
299/2023: Discontinuance"*); the discovery code captures all six symbols
even though OHCHR only renders one Download.aspx URL for the whole bundle.

Classification by title keyword:

| outcome bucket | rows |
| --- | --- |
| Views (substantive merits decision) | 39 |
| Inadmissibility | 12 |
| Discontinuance (individual + bundled) | 169 |
| Other / catalog rows | 27 |
| **total** | **247** |

---

## Extraction

For each discovered symbol the pipeline:

1. Fetches the DOCX from `documents.un.org/api/symbol/access`.
2. If the response is OLE (legacy `.doc`), converts it to OOXML with
   LibreOffice headless.
3. Walks `word/document.xml`, capturing per-paragraph rows.

For each paragraph the extractor records:

- **Body text** with `[[fn:N]]` markers inserted at the exact byte offsets
  where Word placed `<w:footnoteReference w:id="X"/>`.
- **Footnotes** — `[{n, text}, …]` lifted from `word/footnotes.xml`,
  numbered doc-wide in source-document order (continuous across paragraphs
  the way Word renders them).
- **Section path** — running stack of headings (`HCh / H1 / H23 / H4 /
  Heading1 / Heading2` Word styles), e.g.
  `["Annex", "Views under article 9, paragraph 1, of the Optional
  Protocol", "Facts and legal issues"]`.
- **Numbering** — multi-level `n` strings (`"1"`, `"1.2"`, `"2.1"`,
  `"12"`) preserved verbatim. UN Views use both flat and nested
  numbering; both forms are kept as strings rather than coerced to
  integers.
- **Style hint** — Word style name (`SingleTxt` / `H1` / etc.) for the
  renderer, in case downstream wants to differentiate body from chrome.

Front-matter ingestion handles two distinct UN treaty-body conventions:

- **Block form** (Views and most Inadmissibility decisions): unstyled
  paragraph `Subject:` followed by a separate unstyled paragraph carrying
  the value, then `Substantive issues:` / value, etc.
- **Inline form** (Discontinuance / shorter Inadmissibility decisions):
  one paragraph `Submitted by: <name>`, label and value on the same line.

Both are normalised into a single metadata dict per case:

```
submitted_by, alleged_victims, state_party, communication_date,
subject_matter, substantive_issues, procedural_issues,
covenant_articles, op_articles
```

---

## Coverage and the missing 100

After extraction:

| status | count |
| --- | --- |
| extracted (native DOCX or OLE → DOCX conversion) | 147 |
| symbol returned 404 from documents.un.org **and** tbinternet | 100 |
| **total discovered** | **247** |

The 100 missing decisions were probed across:

- `documents.un.org` × {`docx`, `pdf`} × {`en`, `es`, `fr`} — all 404
- `tbinternet.ohchr.org/Download.aspx` × {`en`, `es`, `fr`} — all
  return the literal HTML message *"Sorry there is no files available"*
- Cross-link via the bundle title (one document covers multiple
  comm-numbers): only **2 of 100** are bundled with a sibling whose
  document **was** extracted; for the remaining 98, every comm-number in
  the bundle returns 404
- CESCR Annual Reports `E/<yr>/22-E/C.12/<yr>/3` — these are 50–60 KB
  high-level reports that don't enumerate individual decisions
- CESCR session reports `E/C.12/<sess>/2` — sometimes available, but
  these cover State-party reporting status, not OP-ICESCR jurisprudence

The pattern: **88 of the 100 are bundled discontinuance decisions**
(authors withdraw, the Committee adopts a single transmittal letter
to the parties closing six to fourteen communications at once, but
no standalone document is published — only the symbol appears in
the OHCHR catalog). The remaining 12 are catalog rows with truncated
or empty titles, including duplicate symbols (one is a clear typo:
`E/C.12/77/D/82/018`, year missing the leading `2`).

These are not extraction failures of the pipeline. The text simply does
not exist as a public document on any UN endpoint we could reach. The
decision to **stop at 147 rather than create stub records for the 100**
was deliberate: a stub with no body text would dilute search quality
without adding citable content.

If you need to track a specific missing communication, the OHCHR
Treaty Body Database catalog row contains the symbol, country, session,
adoption date, and (where the decision is bundled) the related
comm-numbers. The annual report `E/<yr>/22` for the relevant
session-pair occasionally mentions the discontinuance in aggregate
("*During the seventy-fifth session, the Committee discontinued
twenty-four communications*…") without per-case detail.

---

## Reproducibility

The corpus rebuilds cleanly from these inputs:

```
python3 _docs_internal/cescr/extract_cescr.py --discover  # one-off
python3 _docs_internal/cescr/extract_cescr.py             # full run
python3 _docs_internal/cescr/apply_cescr.py --apply       # write JUR shard
```

`extract_cescr.py` is incremental — re-running with
`--no-fetch` reads from the on-disk `_docs_internal/cescr/docx/` cache.
With cache populated (147 files, ~9 MB), full extraction completes in
~30 seconds; without cache, the `0.3 s` per-doc HTTP throttle limits
the cold run to ~10 minutes.

`apply_cescr.py` is idempotent — it strips any existing
`treaty=CESCR` rows from `documents.json` / `documents-lite.json`
before re-appending, then refreshes `facets.json` (preserving the
`[{value, count}]` schema for treaties / countries / outcomes /
formats and the nested `{min, max, histogram}` shape for years) and
re-stamps `manifest.json` with sha + bytes for every changed file.

---

## Next steps if you ever want to push past 147

In rough order of expected yield:

1. **Manually inspect the 12 "other" orphans** — most are bundle
   secondaries, but `E/C.12/77/D/82/018` is a clear OHCHR catalog typo
   that can be fixed locally to `E/C.12/77/D/82/2018` and re-fetched
   (the corrected symbol does have a downloadable doc).
2. **Fetch the 2 missing-but-bundled-with-extracted-sibling cases**
   and cross-link to the sibling's body text, marking them as
   "covered by bundle decision under symbol X".
3. **Mine CESCR press releases** for session-end summaries — these
   are unstructured but sometimes carry a sentence per discontinuance.
   Low yield, high noise.
4. **Wait for OHCHR back-publication** — historically OHCHR has
   re-published older bundled discontinuances as standalone documents
   when comm-numbers were merged into thematic press releases. Re-run
   the full pipeline annually and the missing count should drift down.

None of these alone justifies a second pass — together they might
recover ~5–10 of the 100. The honest description of coverage is
**59% (147 of 247 discovered symbols) full-text; 41% catalog-only**.
