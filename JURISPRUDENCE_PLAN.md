# Jurisprudence ingestion — plan & scoping

**Source folder:** `/Users/lszoszk/Desktop/AI/HURIDOCS/App/output/ohchr_jurisprudence/`
**Date:** 29 April 2026
**Status:** CRPD + CEDAW preview built — extractor + shard architecture in place

## 0. Current preview status — CRPD + CEDAW

Built on 29 April 2026:

- Published preview result: **256 documents**, **12,649 paragraphs**, **2 shards**.
- Treaty distribution:
  - **CEDAW:** 168 documents · 8,923 paragraphs · `jur_CEDAW.json`
  - **CRPD:** 88 documents · 3,726 paragraphs · `jur_small_treaties.json`
- Formats parsed: **238 DOCX**, **15 PDF**, **5 legacy DOC**.
- Outcome distribution:
  - `inadmissible`: 101
  - `violation_found`: 74
  - `discontinued`: 37
  - `other`: 34
  - `merits_no_violation`: 9
  - `decision`: 2
  - `views`: 1
- CEDAW ingestion note: **168/171** catalog records ingested; **1** record has no English file in the local dump; **2** OHCHR catalog rows were skipped because their treaty/symbol prefixes point to CRPD/CRC rather than CEDAW; extraction failures: **0**.

## 0.1 Pilot status — CRPD

Built on 28 April 2026:

- `ingest_jurisprudence.py` ingests the CRPD pilot from the OHCHR bulk dump.
- `build_jurisprudence_shards.py` publishes jurisprudence as lazy assets under `docs/jur/`.
- CRPD pilot result: **88 documents**, **3,726 paragraphs**, **1 shard**.
- Formats parsed: **83 DOCX**, **4 PDF**, **1 legacy DOC**.
- Outcome distribution:
  - `violation_found`: 37
  - `inadmissible`: 24
  - `discontinued`: 18
  - `merits_no_violation`: 7
  - `decision`: 1
  - `other`: 1 (`CRPD/C/6` guidelines)
- Output architecture:
  - `mysite_pythonanywhere/jurisprudence_info.json`
  - `json_jurisprudence/<docId>.json`
  - `docs/jur/documents.json`
  - `docs/jur/facets.json`
  - `docs/jur/manifest.json`
  - `docs/jur/shards/jur_small_treaties.json`
- Note: `CRPD/C/12/D/10/2013` had a broken legacy catalog URL in the first OHCHR dump; it was repaired manually through the modern `Download.aspx?symbolno=CRPD/C/12/D/10/2013` page and appended to `download_manifest.jsonl`.

---

## 1. What's in the dataset

| Asset | Size | Description |
|-------|-----:|-------------|
| `catalog.jsonl` | 4 626 records | Per-case metadata: `treaty`, `symbol_no`, `country`, `title`, `submitted_date`, language availability, OHCHR `download_page_url` |
| `download_manifest.jsonl` | 4 593 entries | Per-file: `download_url`, `format`, `language`, `sha256`, `content_type`, local `file_path` |
| `download_links.jsonl` | 74 746 links | Direct links to each language × format combination (most unused) |
| `raw/{en,fr,es,ar}/*.{pdf,docx,doc}` | ≈452 MB EN | The actual documents |

**Treaty distribution (catalog):**

| Treaty | Cases |
|--------|------:|
| CCPR | 2 927 |
| CAT |   956 |
| CRC |   200 |
| CESCR |   199 |
| CEDAW |   171 |
| CRPD |    88 |
| CERD |    75 |
| CED |     9 |

**Format distribution (downloads):** 3 704 DOCX · 824 PDF · 41 DOC · 24 other.

**Languages downloaded:** 4 503 EN · 48 ES · 41 FR · 1 AR.

**Title classification (auto from metadata):**

| Kind | n | Note |
|------|--:|------|
| "Communication No. X/Y" only | 2 471 | The catalog row has just the case ID — substantive outcome unknown until we read the doc |
| "Views" | 940 | Substantive merits decision |
| "Decision (other)" | 652 | Procedural or admissibility decision |
| "Other" / no recognizable form | 289 + 184 | |
| "Discontinued" | 46 | |
| "Violation" | 29 | Explicit |
| "Inadmissible" | 14 | |
| "No violation" | 1 | |

**Year range:** 1977 – 2028 (some forthcoming) · **Countries:** 122.

---

## 2. The scale problem (this is the headline)

Average DOCX file is 103 KB. Plain text after extraction is roughly 10–30 KB per
case. Conservatively estimating 25 numbered paragraphs/case × 4 626 cases:

> **≈ 115 000 paragraphs · ≈ 115 MB of paragraph JSON**

Compared with the current corpus:

| | Current | Add jurisprudence | Δ |
|---|--:|--:|--:|
| Documents | 359 | + 4 593 | × 13 |
| Paragraphs | 25 843 | + ≈ 115 000 | × 4.4 |
| `corpus.json` size | 24 MB | would balloon to ~140 MB | — |

**A single `corpus.json` no longer works.** 24 MB on first load is already
chunky on mobile; 140 MB would be unusable. Architecture has to change for
this stream.

---

## 3. Architecture proposal — tiered loading

The jurisprudence corpus splits into three tiers by access frequency.

### Tier 1 — *always-loaded* metadata catalog (~5 MB)

`docs/jurisprudence_documents.json` — one record per case, **no paragraph
text**:

```json
{
  "docId": "ccpr-c-141-d-jc3",
  "type": "jur",
  "treaty": "CCPR",
  "symbol": "CCPR/C/141/D/JC3",
  "country": "Belarus",
  "year": 2024,
  "title": "Communication No. JC3",
  "outcome": "views",          // derived from title + body scan
  "submittedDate": "19 Jul 2024",
  "languages": ["en", "es", "ru", "ar"],
  "link": "https://tbinternet.ohchr.org/.../Download.aspx?symbolno=CCPR%2FC%2F141%2FD%2FJC3&Lang=en",
  "paragraphCount": 42,
  "wordCount": 5780,
  "shardId": "jur_CCPR_2020-2024"   // tells the client which Tier-2 shard to fetch
}
```

Powers the **case browser** and **filter sidebar** without any text. Users
see the full list immediately and can filter by treaty/country/year/outcome.

### Tier 2 — *lazy-loaded* paragraph shards (chunked)

Sharding rules:

| Treaty | Cases | Strategy | Shards |
|--------|--:|----------|--:|
| CCPR | 2 927 | by adoption year (5-year buckets) | ≈10 shards × 7–15 MB |
| CAT | 956 | by 5-year bucket | ≈8 shards × 3–5 MB |
| CRC, CESCR, CEDAW | 570 total | one shard per treaty | 3 × ~5–8 MB |
| CRPD, CERD, CED | 172 total | one shard combined ("small treaties") | 1 × ~4 MB |

Total: ~22 shards, ~7 MB average. Loaded into IndexedDB the first time the
user opens a case from that bucket; cached forever (keyed by manifest sha).

Shard file shape — list of paragraph records:

```json
[
  { "id": "ccpr-c-141-d-jc3-0001", "docId": "ccpr-c-141-d-jc3", "n": 1, "section": null, "text": "..." },
  { "id": "ccpr-c-141-d-jc3-0002", "docId": "ccpr-c-141-d-jc3", "n": "1.1", "section": "The facts as submitted", "text": "..." }
]
```

Notice the new `section` field — jurisprudence has consistent court-style
section headings ("The facts", "The complaint", "Issues and proceedings",
"Views", "Conclusions") that we should preserve. Extracted from DOCX
heading styles (Heading 7/8/...).

### Tier 3 — *lazy-loaded* per-shard search index

FlexSearch index built per shard, serialised to IndexedDB, loaded on demand.
Same caching pattern as the current `flex-index` IndexedDB store.

Search across multiple shards = parallel index loads + result merge. The
keyword input gets a hint ("Searching CCPR 2020–2024 only — broaden scope to
include other treaty bodies?") when a user has the case browser filtered to a
single treaty.

---

## 4. Pipeline stages

Reuses our existing skeleton (`ingest_new_gcs.py`, `ingest_sp_mandate.py`,
`clean_extract.py`) with three new pieces:

```
catalog.jsonl  +  raw/en/*.docx
       │              │
       └──┬───────────┘
          ▼
  ┌─────────────────────────────────┐
  │ ingest_jurisprudence.py         │ ← new (DOCX-aware extractor + outcome classifier)
  │  • python-docx for .docx        │
  │  • clean_extract for .pdf       │
  │  • classify outcome from text   │
  │  • shard assignment             │
  └────────────┬────────────────────┘
               ▼
  json_jurisprudence/<shard_id>/<symbol_safe>.json   ← per-case files
  jurisprudence_info.json                            ← Tier-1 catalog
               ▼
  ┌─────────────────────────────────┐
  │ build_jurisprudence_shards.py   │ ← new (assembles tier-2 shards + indexes)
  │  • merge per-case files         │
  │  • compute paragraphCount etc.  │
  │  • emit jurisprudence_documents │
  │  • per-shard FlexSearch builds  │
  └────────────┬────────────────────┘
               ▼
  docs/jur/                        ← published to gh-pages
    ├── documents.json             (Tier 1)
    ├── shards/jur_CCPR_2020-2024.json
    ├── shards/jur_CAT_2010-2014.json
    └── indexes/jur_CCPR_2020-2024.flx.json
```

### 4.1 Document extractor

DOCX-specific logic (extending the PDF logic in `clean_extract.py`):

1. Open with `python-docx`.
2. Walk `doc.paragraphs`. State machine:
   - **Phase A — header**: until we hit `[See annex]` or "VIEWS" line ➝ skip
   - **Phase B — annex / metadata**: paragraphs introducing the case ➝ skip
   - **Phase C — body**: numbered paragraphs (`^(\d+(?:\.\d+)?)\s+`) ➝ keep
   - **Heading detection**: `p.style.name.startswith("Heading")` ➝ store as
     section label for subsequent paragraphs.
3. Strip footnote markers (already handled by trailing `__________` pattern).
4. Output `[{ID, Section, Labels, Text}]`.

PDFs (the 824 minority) go through `clean_extract.extract_paragraphs` with
the existing footer/footnote stripping; the section detection becomes
heuristic (e.g., capitalised lines).

### 4.2 Outcome classifier

Title-based first cut already covers ~70 %. For the rest we read the doc
body and look for explicit phrases:

- "the Committee finds that … constituted a violation of article …" → `violation`
- "the Committee declares the communication inadmissible" → `inadmissible`
- "the Committee decides to discontinue" → `discontinued`
- "the State party has not violated" → `no_violation`

The outcome lives in `jurisprudence_documents.json` so it's filterable
without ever loading the case body.

### 4.3 Build pipeline (extending `build_corpus.py`)

Two options — recommendation: **Option B**.

- **A)** Extend the existing build to mix jurisprudence into `corpus.json`. Bad — defeats sharding.
- **B)** Add a parallel `build_jurisprudence.py` script. Outputs go under
       `docs/jur/`. Existing GC/SP corpus stays at `docs/corpus.json`. The
       boot sequence loads GC/SP eagerly (as today), jurisprudence
       opportunistically.

---

## 5. UI integration

The current scope tabs are **General Comments / Special Procedures / All sources**.
Jurisprudence is a third category — "near-hard-law" but case-specific rather
than thematic. Three options for surfacing it:

| Option | Pros | Cons |
|--------|------|------|
| **A. Add 4th scope tab "Jurisprudence"** | Symmetric with GC/SP; same keyword input drives all three | "All sources" becomes huge, and most users want one scope at a time |
| **B. Separate top-level "Cases" tab next to "Documents"** | Different mental model — case browser, not paragraph search | Two parallel search experiences; inconsistent UX |
| **C. Add as new scope, but introduce required filter (treaty + year)** | Forces users to narrow before search, justifies lazy load | Mild friction |

**Recommendation: A + C** — add it as a 4th scope tab with a required
treaty body filter on first activation. The shard model means we need *some*
narrowing before issuing a search; UX-wise that's a banner ("Pick a treaty
body to begin — search across the entire corpus is also available but loads
~20 MB of additional data first").

Visual differentiator: jurisprudence cards in results show:
- Country chip (always)
- Outcome badge (`violation` / `inadmissible` / `views` / etc.)
- Case symbol + adoption year
- Section label of the matched paragraph (e.g., "Issues and proceedings")

### 5.1 New "Cases" sub-view

Documents tab today shows GC + SP rows. We add a third grouping —
**Cases by country** or **Cases by treaty** — toggleable. Clicking a
case opens its paragraph view in the right pane.

### 5.2 Filter sidebar additions (jurisprudence-only)

- **Outcome**: views / decision / inadmissible / violation / no-violation / discontinued
- **Country**: chip grid of 122 countries (sorted by case count)
- Treaty body filter is reused from the existing facet (auto-extends to
  cases when scope = jurisprudence)

---

## 6. Concerned-group labelling

Same 19-label taxonomy. Two questions:

1. **Should we re-label?** Yes — case law is rich in vulnerable-group
   content (asylum cases → refugees; many CRPD cases → persons with
   disabilities). Apply the v6 patterns at ingest time, exactly as for
   GC/SP.
2. **Should we label by section?** Optional — labels sit on paragraphs
   regardless of section, so this is automatic. We may want a per-case
   aggregate `caseLabels` for the Tier-1 metadata so the case browser
   shows "this case discusses children + women" without needing the
   full body.

Estimated label coverage: ~50–60 % of paragraphs (jurisprudence has more
procedural text than GCs, but a lot of substantive paragraphs hit
specific labels).

---

## 7. Phasing

| Phase | Scope | Effort | Output |
|-------|-------|-------:|--------|
| **1. Foundation** | Build extractor + 1 small treaty (CRPD = 88 cases) end-to-end. Verify schema, outcome classifier, label coverage. | 1 day | `ingest_jurisprudence.py`, `json_jurisprudence/CRPD_*/`, `jurisprudence_info.json` (CRPD only) |
| **2. Shard build** | `build_jurisprudence.py` — emit `docs/jur/documents.json` + `shards/` for the CRPD shard. Verify size. | 0.5 day | `docs/jur/` directory |
| **3. UI integration** | New scope tab, lazy shard loader, case browser with country + outcome + treaty filters, paragraph viewer. Test purely on CRPD's 88 cases. | 1 day | Working tab on the website |
| **4. Search index** | Per-shard FlexSearch indexes, in-memory result merge across loaded shards. KWIC + BM25 work the same. | 0.5 day | Search works on CRPD cases |
| **5. Scale** | Run the pipeline on the remaining 4 538 cases. Iterate on outcome classifier. Build all shards. | 1.5 days (mostly compute) | Full jurisprudence in production |
| **6. Polish** | Citation formats (APA/Bluebook/etc. for case law), jump-to-paragraph anchors, per-case "all paragraphs" view, multilingual previews | 1 day | Reference-quality case viewer |

**Total: ~5.5 working days** with most of the variance in phase 5 (compute time).

---

## 8. Open questions for you

Before phase 1 begins, four decisions are yours:

1. **Scope tab layout (Q5)** — Confirm option A + C ("4th scope tab + required treaty filter on first use")?
2. **Outcome taxonomy** — should we use the broad set in §4.2
   (`views / decision / inadmissible / violation / no_violation /
   discontinued / other`) or split `violation` into `violation_found` vs
   `merits_no_violation`? Bluebook-style citation needs the latter.
3. **Languages** — only `en` for v1? The catalog has a fair amount of
   `es` / `fr` / `ar` versions. Multilingual ingestion is doable but ×4
   storage and we don't yet handle non-English search.
4. **Case ID conventions** — DOCX symbols can be ugly
   (`CCPR_C_141_D_JC3.docx.docx`). The proposed `docId` is a
   slug from the OHCHR `symbol` (`ccpr-c-141-d-jc3`). OK?

Once these are answered I can start phase 1 immediately.
