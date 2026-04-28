# Metadata Audit & Proposed Schema Extension

**Date:** 28 April 2026
**Audited:** GC corpus (`crc_gc_info.json`, 187 records) + SP corpus (`specialprocedures_info.json`, 153 records) + published `documents.json` (337 records)

---

## 1. Findings — issues to fix

### 1.1 GC metadata (`crc_gc_info.json`)

**All 187 records have all 8 fields filled.** No null values. But the *content* of those fields is inconsistent.

| # | Severity | Issue | Records affected |
|---|----------|-------|------------------|
| G1 | 🟥 high | `Adoption Year` mixed type — 148 int, 39 string | All recent CEDAW/CERD/CMW + new ingestion |
| G2 | 🟥 high | Typo in CCPR GC31 signature: `'CCPR/C/21/Rev.1/Add. 1326 May 2004'` (date got concatenated into the signature) | 1 |
| G3 | 🟧 medium | Orphan record: `CEDAW/C/GC/31/CRC/C/GC/18` (non-revised version) points to `Annotated_CRC-GC18-Harmful.json` which doesn't exist locally — only the `-REV` variant is on disk | 1 |
| G4 | 🟧 medium | Mixed `Link` providers — 168 use canonical `tbinternet.ohchr.org/Download.aspx`, 19 use other hosts (`ohchr.org/en/documents/`, `undocs.org/Home/Mobile`, `refworld.org`). Two `ohchr.org/documents/` links return **HTTP 403** (joint CRC22/CMW3 and CRC23/CMW4) | 2 broken + 17 non-canonical |
| G5 | 🟧 medium | `Committee` field for joint GCs lists only one of the two committees: `CRC/C/GC/22, CMW/C/GC/3` is filed only under "CRC" | ~5 joint GCs |
| G6 | 🟨 low | `Signature` is *not* unique — 13 signatures appear ≥2× (e.g. `A/48/18` carries 7 different CERD GCs from one annual report). The corpus build correctly falls back to filename slug, but downstream consumers expecting unique signatures will break. | 32 records |
| G7 | 🟨 low | `File PATH` baked to production-server path (`/home/lszoszk/mysite/json_data/...`) — not portable; `build_corpus.py` re-resolves via filename | All 187 |

### 1.2 SP metadata (`specialprocedures_info.json`)

**Severe field-level inconsistency.** Only 7 fields are filled in all 153 records; the others have ~50 % coverage and the year field exists in two casings.

| # | Severity | Issue | Records affected |
|---|----------|-------|------------------|
| S1 | 🟥 high | Year stored under TWO different keys: `Adoption Year` (88 records, integer) and `Adoption year` (65 records, integer). Same data, capitalisation split. Downstream code reading `r['Adoption Year']` will silently miss 65/153 records. | 153 |
| S2 | 🟥 high | `Mandate holder` empty/missing in 88 of 153 records | 88 |
| S3 | 🟥 high | `Presented` (e.g. "HRC 59th session") missing in 88 records | 88 |
| S4 | 🟧 medium | Filename mismatch between metadata and disk: 90 metadata records reference `SR_belief_A_50_440.json`-style names while files on disk are `A_50_440.json`. The corpus build uses a suffix-match fallback to paper this over, but it's fragile. | 90 |
| S5 | 🟧 medium | 95 SP files on disk have *no* metadata at all (mostly older SR Freedom-of-Religion country-visit reports + recent SR Privacy / SR Expression thematic reports) — they appear in the corpus with whatever `Committee` the build script can infer | 95 |

### 1.3 Cross-corpus

- The published `documents.json` already derives a clean schema: `docId`, `type`, `name`, `nameShort`, `signature`, `committee`, `committees[]`, `year`, `adoptionDate`, `link`, `sourceFile`, `paragraphCount`. This is the de-facto consumer contract.
- **No `paragraphCount`** in source metadata — only computed at build time. Same for any future word-count, label-count metrics.
- **No provenance trail**: no record of *when* a metadata entry was last edited, by whom or against which OHCHR snapshot.

---

## 2. Recommended fixes (do these first)

These are corrections to existing data — no schema change needed.

1. **Cast all `Adoption Year` to int.** One-liner over both metadata files.
2. **Merge SP `Adoption year` → `Adoption Year`.** Drop the lowercase variant after merging.
3. **Fix the CCPR GC31 signature typo:** `'CCPR/C/21/Rev.1/Add. 1326 May 2004'` → `'CCPR/C/21/Rev.1/Add. 13'` (the `26 May 2004` is the adoption date, already correctly stored in `Adoption Date`).
4. **Remove the orphan `CRC-GC18-Harmful` record** (non-REV) and consolidate with the `-REV` record. Keep both signatures (`CEDAW/C/GC/31` and `CEDAW/C/GC/31/Rev.1–CRC/C/GC/18/Rev.1`) as alternative identifiers.
5. **Standardise links to `tbinternet.ohchr.org/Download.aspx?symbolno=...`** for all 19 outliers. The two failing 403 links go away automatically. (`undocs.org/Home/Mobile?FinalSymbol=...` and `ohchr.org/en/documents/...` redirect there anyway.)
6. **Fill the `Committee` field for joint GCs with both committees,** comma-separated (matches the convention already used for `CRC, CEDAW`).
7. **Backfill `Mandate holder` for the 88 SP records** by parsing the document `Signature` against a hard-coded mapping of mandate symbols → mandate-holder names.
8. **Reconcile SP filename mismatches:** rename the 90 `SR_belief_*.json` references in metadata to match disk (or vice-versa). Pick one convention and stick to it.

A small `repair_metadata.py` script can apply 1–4 + 6 mechanically. 5 needs manual eyeballing for the few non-canonical patterns. 7–8 need a curated mapping.

---

## 3. Proposed new metadata fields

Each field has a clear purpose, a worked example, an acceptance criterion (when can we consider it complete?), and a low/medium/high cost estimate.

### 3.1 GC corpus — proposed additions

| Field | Type | Purpose | Example | Cost |
|-------|------|---------|---------|------|
| **`articles`** | `string[]` | Treaty articles the GC interprets — enables "show all GCs interpreting Article 6" filter | `["ICCPR Art. 6", "ICCPR Art. 6(2)"]` | 🟢 low — extractable from `Name` field with a regex per committee |
| **`topicTags`** | `string[]` | Controlled-vocabulary thematic tags, complementary to concerned-group labels (which target *who*, not *what*) | `["death penalty", "right to life", "armed conflict"]` | 🟡 medium — needs a taxonomy proposal + manual or assisted assignment |
| **`status`** | `enum` | `final` / `revised` / `superseded` / `draft` — distinguishes live from outdated GCs (e.g. CRC GC10 was *replaced* by GC24 in 2019) | `"superseded"` | 🟢 low — derivable from cross-references in OHCHR pages |
| **`supersedes`** | `string \| null` | Signature of the GC this one replaces | `"CRC/C/GC/10"` | 🟢 low — small list, ~10 cases |
| **`supersededBy`** | `string \| null` | Inverse pointer | `"CRC/C/GC/24"` | 🟢 low |
| **`jointWith`** | `string[]` | Co-issuing committees + signatures for joint GCs (cleaner than packing into `Signature`) | `[{"committee": "CMW", "signature": "CMW/C/GC/3"}]` | 🟢 low — handful of cases |
| **`languagesAvailable`** | `string[]` | UN language codes the document is published in | `["en", "fr", "es", "ar", "ru", "zh"]` | 🟢 low — scrape from OHCHR Download page |
| **`ohchrSymbol`** | `string` | The URL-encodable symbolno used by OHCHR (canonical UN identifier) | `"E/C.12/GC/27"` | 🟢 low — already implicit in `Signature` for most |
| **`refworldId`** \| **`undocsId`** | `string \| null` | External IDs for cross-referencing | `"refworld.org/legal/.../149163"` | 🟢 low |
| **`abstract`** | `string` | 1–2 sentence summary, distinct from the verbose `Name`, optimised for SERP/cards | `"Interprets ICESCR Art. 11 obligations on environmental protection in the context of land use, water and food security."` | 🟡 medium — need to write 187 of these |
| **`paragraphCount`** | `int` | Already computed at build time — promote into source metadata so it survives without a build | `90` | 🟢 low |
| **`wordCount`** | `int` | Same | `7842` | 🟢 low |
| **`labelCount`** | `int` | How many concerned-group labels the document carries (sum across paragraphs) | `45` | 🟢 low |
| **`firstAddedAt`** | `date (ISO)` | When this record was first ingested | `"2024-09-12"` | 🟢 low — backfill once with file-mtime fallback |
| **`lastVerifiedAt`** | `date (ISO)` | When metadata was last reconciled with OHCHR | `"2026-04-28"` | 🟢 low |

### 3.2 SP corpus — proposed additions

| Field | Type | Purpose | Example | Cost |
|-------|------|---------|---------|------|
| **`reportType`** | `enum` | `annual` / `country-visit` / `thematic` / `communications` / `addendum` — fundamental classification missing today | `"thematic"` | 🟢 low — inferrable from signature pattern (`A/HRC/X/Y/Add.1` = addendum, `A/HRC/X/Y` = thematic, `A/X/Y` = annual to GA) |
| **`country`** | `string \| null` | ISO-3166 country name for country-visit reports | `"Indonesia"` | 🟡 medium — extract from filename / document title |
| **`hrcSession`** | `int \| null` | HRC session number when document was presented | `59` | 🟢 low — parse `A/HRC/{N}/...` |
| **`gaSession`** | `int \| null` | UNGA session number | `78` | 🟢 low — parse `A/{N}/...` |
| **`mandateNumber`** | `string` | Specific mandate ID (HRC resolution that established it) | `"HRC/RES/16/4"` (FoE) | 🟢 low — small lookup table |
| (everything from §3.1 that is committee-agnostic) | — | abstract, paragraph/word/label counts, languages, lastVerifiedAt | — | — |

### 3.3 Why these specific fields?

The choices above cluster into four groups, each with a clear use case:

1. **Corrigibility** (`status`, `supersedes`, `supersededBy`, `jointWith`) — without these, users can't tell that CRC GC10 is no longer authoritative or that CMW GC3 is the same document as CRC GC22. Today the website silently lists both.

2. **Filterability** (`articles`, `topicTags`, `reportType`, `country`, `hrcSession`) — currently the only filters are *committee*, *concerned-group label* and *year*. A researcher wanting "everything CESCR has said about Art. 11" or "all SR-Privacy thematic reports to HRC sessions 40–60" cannot query that.

3. **Discoverability/SEO** (`abstract`, `topicTags`, `languagesAvailable`) — abstracts dramatically improve search-result UX (the current excerpt is the verbose `Name` field, often >100 chars). `languagesAvailable` enables a non-English researcher to spot French/Spanish editions.

4. **Provenance** (`firstAddedAt`, `lastVerifiedAt`, `ohchrSymbol`, `refworldId`) — answers "is this entry stale?", "where did we get this?" and "is the OHCHR canonical URL still resolving?".

### 3.4 Fields explicitly *not* worth adding

- ❌ **DOI** — UN Treaty Body GCs do not have DOIs as a class. Adding the field would have ~0 % fill rate.
- ❌ **Citation count / academic impact metrics** — interesting but expensive (Google Scholar scraping is fragile and rate-limited). Defer until we have a research-tool integration.
- ❌ **Full-text search index pointer** — already handled at build time (FlexSearch). Storing it in metadata would couple metadata to a specific index version.
- ❌ **Author/Drafter** — Treaty Bodies adopt GCs collectively; individual rapporteurs are listed in OHCHR annexes only.

---

## 4. Suggested implementation order

To keep the cost low and preserve backward-compat with the current `documents.json` consumers:

```
Phase 1 (1 hour, automatic):
  - repair_metadata.py applies fixes 1, 2, 3, 4, 6 from §2
  - adds firstAddedAt (file mtime fallback), lastVerifiedAt (today)
  - adds paragraphCount, wordCount, labelCount (recompute from json files)
  - adds ohchrSymbol (extract from Link query string)
  - rebuilds corpus → no behavioural change

Phase 2 (half day, semi-automatic):
  - articles: regex from Name, manual cleanup
  - status / supersedes / supersededBy: small manual list
  - jointWith: small manual list
  - languagesAvailable: scrape from OHCHR Download.aspx pages

Phase 3 (1-2 days, manual + AI-assisted):
  - abstract: 1-2 sentence summary per GC. Best produced as a draft by Claude
    against the document text, then reviewed by a human. Same applies to topicTags.

Phase 4 (after Phase 1-3 settle):
  - Update build_corpus.py to expose the new fields in documents.json
  - Update website Documents view to surface abstracts, articles, status badge
  - Add filter UI for articles, topicTags, reportType, country
```

Phases 1 and 2 are pure data-quality improvements with no schema changes downstream. Phase 3 is where the corpus becomes *substantially* more useful.

---

## 5. Questions for you

Before any of the above is implemented, three decisions are yours:

1. **`topicTags` taxonomy** — do you want to design one, reuse an external one (e.g. UNESCO Thesaurus, EuroVoc, FAO AGROVOC), or skip thematic tagging in favour of just `articles`?
2. **`abstract` voice** — first-person Committee voice (`"The Committee considers that..."`) or neutral encyclopaedic (`"This General Comment interprets..."`)?
3. **Joint GC display** — list as one combined record (cleaner) or keep two records with cross-references (current behaviour, preserves committee-filter symmetry)?
