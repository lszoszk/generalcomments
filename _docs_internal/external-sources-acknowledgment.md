# External sources — detailed acknowledgment (offline reference)

This document captures the *full* provenance details for fields that
were partially informed by external curated databases. The public
methodology section on the website intentionally summarises this in a
single short paragraph, because (a) our project's scope is broader
than either external resource and (b) we don't want to overstate our
reliance on them. This file exists so that we can answer specific
questions if a reviewer or collaborator asks.

## CCPR Centre — Geneva Centre for Civil and Political Rights

URL: <https://ccprcentre.org/database-decisions>
Crawled: 6 May 2026 (2,694 records).

### What we cross-checked / adopted (CCPR jurisprudence only)

- Substantive Covenant-article extraction: replaced or enriched
  **2,046** cases where our front-matter parse had pulled only the
  Optional-Protocol procedural articles.
- 119-keyword rights-based topic vocabulary: ingested into our dataset
  as a `rightsKeywords` field on **2,465** CCPR cases. **NOT exposed
  in the public UI** as a filter (would create CCPR-only asymmetry
  with the rest of the corpus). Available for downstream consumers
  who load the JUR dataset directly.
- Multilingual document URLs (EN + ES + FR + AR + RU + ZH where
  available) on **2,539** cases.
- ISO-3166 country codes; granular outcome classifications; clean
  ISO-8601 decision dates where our parser had garbled them.
- Case-name authority for **170** cases where ours was a stub
  ("Communication No. X") or front-matter junk.
- **59** CCPR decisions that were missing from our corpus entirely
  (mostly 1977–1996 Uruguay, Canada, Jamaica cases).

### What CCPR Centre does NOT cover (our additions)

- All other treaty bodies (CESCR, CRC, CEDAW, CRPD, CAT, CERD, CMW,
  CED) — CCPR Centre is CCPR-only.
- Concluding Observations, General Comments / Recommendations, Special
  Procedures reports — CCPR Centre is jurisprudence-only.
- Paragraph-level full-text search (CCPR Centre is decision-level).
- Submission-date coverage: **~99 %** for ours vs **41 %** for theirs.
- OCR recovery of 170 pre-1996 scanned-PDF cases.

## University of Minnesota Human Rights Library

URL: <http://hrlibrary.umn.edu/>

### What we cross-checked / adopted

- Reference text for several UN core treaties + optional protocols
  during the build of the Ask tab's treaty bundle (`api/treaties/`).
  OHCHR canonical pages were our primary source where accessible;
  UMN HRL's structured-text mirrors were used as a fallback for the
  treaties that OHCHR's Cloudflare protection blocked from automated
  fetching. See `_docs_internal/treaties/build_treaties.py` for the
  build script and per-treaty source URLs.
- Spot-checks during corpus QA — e.g., verifying article numbering
  conventions across older documents.

### What UMN HRL does NOT cover (our additions)

- General Comments / Recommendations corpus.
- Treaty body jurisprudence at the level of detail we ingest.
- Specific Procedures reports.
- Any of the deduplication, OCR repair, paragraph-level segmentation
  work specific to our project.

## Provenance tracking

Each ingested document carries a `metadataSources` field listing
which external source contributed which field (e.g., `outcome` may
be marked `ccprcentre` for CCPR cases and `ohchr` for others). This
makes the dependency graph auditable per record without needing this
document.
