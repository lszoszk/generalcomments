# Methodology — Concerned-Group Annotation Pipeline

**Project:** The Geneva Reporter — paragraph-level corpus of UN human rights interpretation
**Maintainers:** Łukasz Szoszkiewicz, Zuzanna Kowalska
**Last revision:** 2026-04-28
**Pipeline version:** v6
**Live corpus:** https://github.com/lszoszk/generalcomments

---

## 1. Purpose & scope

The Geneva Reporter exposes 23,440 paragraphs from 332 documents (181 General Comments
issued by UN Treaty Bodies + 151 Special Procedures reports) as a paragraph-level search
interface. Beyond plain-text search, every paragraph carries zero or more **concerned-group
labels** drawn from a controlled 19-category taxonomy of vulnerable populations. These
labels power faceted filtering ("show me all CESCR paragraphs about persons with
disabilities", etc.).

Historically these labels were applied manually paragraph by paragraph, leaving a large
fraction of the corpus unlabelled. This document describes the labelling pipeline used to
fill that gap and the quality assurance procedure surrounding it.

The pipeline is **deterministic and pattern-based**, not generative. No paragraph label
in the published corpus was produced by an LLM as free-form output. The role of generative
AI in this project is limited to *designing and stress-testing* the pattern set — see §6.

## 2. Concerned-group taxonomy

All labels come from a fixed 19-category vocabulary aligned with how UN treaty bodies
typically describe vulnerable groups:

1. Children
2. Women/girls
3. Persons with disabilities
4. Migrants
5. Indigenous peoples
6. Persons deprived of their liberty
7. Refugees & asylum-seekers
8. Adolescents
9. Persons living in rural/remote areas
10. Persons affected by armed conflict
11. Persons living in poverty
12. Internally displaced persons
13. Persons in street situations
14. Children in alternative care
15. Non-citizens and stateless
16. Persons living with HIV/AIDS
17. LGBTI+
18. Roma, Gypsies, Sinti and Travellers
19. Persons affected by natural disasters

Categories that recur in the underlying texts but are *not* in the taxonomy
(older persons, persons of African descent, religious minorities, ethnic minorities in
general) are deliberately left unlabelled rather than forced into a near-fitting category.
A paragraph that discusses only such a group will appear as `Labels: []` in the data.

## 3. Pipeline design

### 3.1 What gets labelled

For each paragraph `p` in the corpus:

- If `p` already had labels assigned manually in the prior dataset, those labels are
  **preserved verbatim** — the pipeline never overrides human annotation.
- If `p` is unlabelled, the pipeline runs every regex pattern from §4 against the
  paragraph text. Each pattern is associated with exactly one taxonomy label.
- Every label whose patterns match is added to `p.Labels`. Labels are deduplicated
  and sorted alphabetically for consistency.
- Paragraphs that match no pattern remain `Labels: []`.

### 3.2 Inputs and outputs

```
Input:
  mysite_pythonanywhere/json_data/*.json    (181 GC files, paragraph lists)
  json_labeled/, json_data_sp/*.json        (151 SP files)

Output:
  json_data_gc_labeled/*.json               (GC files with augmented Labels)
  json_labeled_v2/*.json                    (SP files with augmented Labels)
  → consumed by build_corpus.py to produce docs/corpus.json
```

### 3.3 Determinism

The same source files plus the same pattern set always produce the same output.
The pipeline uses Python's `re` module with case-insensitive matching and word-boundary
anchors. It is offline, has no network calls, and reads no environment-dependent state.

## 4. Pattern engineering

Each taxonomy label has a hand-crafted list of regex patterns. Patterns target unambiguous
linguistic markers — full terms, fixed phrases, and inflected forms — rather than generic
synonyms. A representative selection (full list lives in the labelling scripts referenced
in §8):

| Label | Examples of patterns |
|-------|----------------------|
| Children | `\bchild(?:ren)?\b`, `\bjuvenile justice\b`, `\bchild marriage\b`, `\bcorporal punishment\b`, `\bage of criminal responsibility\b` |
| Women/girls | `\bwom(?:an\|en)\b`, `\bdomestic violence\b`, `\bsexual and reproductive health\b`, `\bfemale genital\b`, `\btraffick(?:ing\|ed)\b` |
| Persons with disabilities | `\bdisabilit(?:y\|ies)\b`, `\bmental(?:ly)?\s+(?:ill\|disorder\|illness)\b`, `\breasonable accommodat`, `\bwheelchair\b` |
| Persons deprived of their liberty | `\bprison(?:ers?\|s)\b`, `\bdetain(?:ee\|ment)\b`, `\bconvict(?:ed\|s)\b`, `\bpretrial detent`, `\bpersons? deprived of (?:their\|his\|her) liberty\b` |
| Persons living in poverty | `\bpoverty\b`, `\bindigent\b`, `\bextreme poverty\b`, `\bdestitut`, `\bdisadvantaged groups?\b` |
| LGBTI+ | `\bLGBT(?:I\|Q)?\+?\b`, `\bsexual orientation\b`, `\bgender identity\b`, `\btransgender\b`, `\bsame.sex\b` |
| Indigenous peoples | `\bindigenous\b`, `\btribal\b`, `\bFPIC\b`, `\bfree,?\s*prior\s*and\s*informed\s*consent\b`, `\btraditional\s+(?:knowledge\|land\|territory)\b` |

### 4.1 Conservatism principle

Patterns are intentionally narrow. Where two readings are plausible, we prefer to miss the
label (false negative) over assigning it incorrectly (false positive). For example,
`\bcitizenship\b` alone does **not** trigger "Non-citizens and stateless" because the term
appears in many neutral contexts; `\bstateless(?:ness)?\b` and `\bnon.citizen\b` do.

Some borderline patterns proved unreliable in practice and were removed during quality
review (see §5):

- `\bsocial security\b` → was wrongly mapped to "Persons living in poverty"; removed because
  it fires on every reference to general social-security obligations, not poor people.
- `\bsocial protection\b` → same issue, removed.
- `\bforced displacement\b` → originally on Refugees, moved to Persons affected by armed
  conflict where it fits better contextually.
- `\bsexual violence\b` → originally on Women/girls, replaced with `\bviolence against women\b`
  and `\bsexual and gender\b` after observing false positives in armed-conflict text where
  sexual violence affects all genders.
- `\balien\b` → too ambiguous in legal English, removed from "Non-citizens and stateless".
- `\bmarginali[sz]ed\b` → removed from "Persons living in poverty" (SP corpus only) because
  in SR Freedom-of-Religion reports it overwhelmingly describes religious minorities, not
  poor populations.
- `\bcorporal punishment\b` (standalone) → audited in v6.1 against the full GC corpus.
  Of 63 paragraphs containing the phrase, 61 had explicit child context (school, student,
  juvenile justice, alternative care, family, parents, etc.) and 2 did not. One of those
  two (`CCPR_GC28 ¶13`, on women's clothing regulations) was already labelled `Women/girls`
  by hand and was therefore untouched by the pipeline. The other (`CCPR_GC34 ¶26`, on
  general restrictions of freedom of expression) had been newly labelled `Children` by the
  pipeline solely because of the `corporal punishment` trigger — this is a clear false
  positive (the paragraph discusses penalties for expression-related offences, not
  children) and was removed manually. The pattern is therefore retained but the
  recommended best practice (documented in the pipeline source) is to require co-occurrence
  with a child-context word (`child`, `juvenile`, `school`, `student`, `pupil`, `family`,
  `home`, `parent`, `teacher`) within the same paragraph. This brings standalone-precision
  on the GC corpus to 100 % at the cost of ~1 paragraph of recall, which is an acceptable
  trade.

## 5. Quality assurance procedure

The pipeline was run in six iterations, each followed by a manual audit of a sample of
newly-applied labels. The audit looks for:

1. **False positives** — labels assigned where the surrounding context shows the matched
   term refers to something other than the intended group.
2. **Coverage gaps** — paragraphs that clearly discuss a taxonomy group but were missed.
3. **Pattern over-broadness** — patterns that fire on ≥10 % unrelated paragraphs.

When a false-positive pattern is identified, two repairs run:

- The pattern is removed or tightened in the script.
- All paragraphs whose label was *only* triggered by the broken pattern (i.e. no other
  valid pattern fires on the same text) have that label removed. Paragraphs with multiple
  triggers keep the label, since other valid evidence remains.

Concretely, in the v5 → v6 cleanup, 40 SP paragraphs had "Persons living in poverty"
removed because they had been triggered exclusively by `\bmarginali[sz]ed\b` in
freedom-of-religion contexts where the phrase referred to marginalised religious minorities.

### 5.1 Spot-check examples

A random sample of pipeline-added labels reviewed during v4–v6 audits:

| File | Label added | Trigger | Accept? |
|------|-------------|---------|---------|
| CCPR_GC32_article14 ¶51 | Persons living in poverty | "indigent convicted person" | ✓ valid (legal aid context) |
| CCPR_GC32_article14 ¶51 | Persons deprived of their liberty | "convicted person" | ✓ valid |
| CCPR_GC36_life ¶29 | Persons deprived of their liberty | "loss of life occurring in custody" | ✓ valid |
| CRPD_GC2 ¶17 | Persons with disabilities | "disability" + accessibility list | ✓ valid |
| CEDAW_GR19 ¶15 | Persons living in poverty | "Poverty and unemployment force many women" | ✓ valid |
| ESCR-GC13 ¶41 | Children | "corporal punishment" + "school discipline" | ✓ valid (school-context discipline) |
| CCPR_GC34 ¶26 | ~~Children~~ | "corporal punishment" alone, no child context | ✗ removed in v6.1 |
| A_64_159 ¶7 (SP) | ~~Persons living in poverty~~ | "marginalized" alone, religious context | ✗ removed in v6 |
| A_66_156 ¶51 (SP) | ~~Persons living in poverty~~ | "marginalized" alone, religious context | ✗ removed in v6 |

## 6. Role of generative AI

This is a question authors and reviewers reasonably want a precise answer to. The honest
breakdown:

**Generative AI is *not* used to generate labels.** Every label in the published corpus
either (a) was applied manually before the pipeline existed, or (b) is the result of a
deterministic regex match. Re-running the same pipeline on the same input produces
byte-identical output. There is no model-in-the-loop at corpus-build time.

**Generative AI *is* used in pattern engineering and quality review.** The pattern set in §4
was designed in dialogue with Claude Sonnet 4.6 (Anthropic) acting as a coding assistant
inside Claude Code:

- Claude proposed candidate patterns drawn from each label's typical vocabulary.
- Claude flagged likely-broad patterns (e.g. `\bmarginali[sz]ed\b`, `\byouth\b` as a sole
  Adolescents trigger) and suggested the conservatism rules in §4.1.
- During quality audits, Claude was asked to read samples of newly-applied labels and
  identify probable false positives. The human author then decided which patterns to keep,
  tighten or remove.
- Claude wrote the iteration scripts that apply patterns and audit the output.

The boundary is therefore: **AI assists with the design of the rules; the rules themselves
are human-readable, human-auditable regular expressions, and they alone touch the data.**

If a future maintainer wishes to reproduce the corpus from scratch, they need only the
source paragraph files and the labelling scripts (linked in §8); they do not need API
access to any LLM and no model weights are involved in the published artefact.

## 7. Quantitative results

### 7.1 General Comments (181 documents, 6,608 paragraphs)

| State | Paragraphs | Coverage |
|-------|------------|----------|
| Originally human-labelled | 4,207 | 63.7 % |
| Newly labelled by pipeline | 687 | 10.4 % |
| Remain unlabelled | 1,714 | 25.9 % |
| **Total labelled** | **4,894** | **74.1 %** |

The 25.9 % that remain unlabelled split roughly into:

- General procedural / framework text (definitions, obligations of states parties, monitoring
  and reporting clauses) — these legitimately reference no specific concerned group.
- Documents whose primary subject is a non-taxonomy group (e.g. CERD GR34 on people of
  African descent, ESCR GC6 on older persons). Coverage in those documents is therefore
  expected to be low.

### 7.2 Special Procedures (151 documents, 17,564 paragraphs)

| State | Paragraphs | Coverage |
|-------|------------|----------|
| Originally labelled (preserved) | 4,081 | 23.2 % |
| Newly labelled by pipeline | 1,704 | 9.7 % |
| Remain unlabelled | 11,779 | 67.1 % |
| **Total labelled** | **5,785** | **32.9 %** |

The SP coverage is materially lower for two structural reasons. First, the largest SP
sub-corpus (≈10,500 paragraphs) consists of country-by-country annual reports of the
Special Rapporteur on Freedom of Religion or Belief — these often discuss religious
minorities, which are not in the taxonomy. Second, country-visit and communications-status
addenda contain large amounts of administrative text that should not carry any concerned-group
label. SP coverage is therefore presented as a preview rather than as exhaustive.

### 7.3 Combined corpus changes vs. last published version

Compared to the corpus before this annotation pass (commit `3b4833c`), the published
corpus (commit `6063370`) has the following net label deltas across both streams:

| Label | Δ |
|-------|---|
| Persons deprived of their liberty | **+271** |
| Persons with disabilities | +187 |
| Refugees & asylum-seekers | +95 |
| Women/girls | +86 |
| Children | +23 |
| Indigenous peoples | +7 |
| LGBTI+ | +3 |
| Persons living in rural/remote areas | +20 |
| Persons affected by armed conflict | +15 |
| Persons affected by natural disasters | +12 |
| Internally displaced persons | +6 |
| Non-citizens and stateless | +8 |
| Persons in street situations | +2 |
| Children in alternative care | +1 |
| Adolescents | +1 |
| **Persons living in poverty** | **−81** |
| Migrants | +4 |

The negative delta for "Persons living in poverty" is intentional: the previous version
contained 81 false positives caused by the `\bsocial security\b` / `\bsocial protection\b` /
`\bmarginali[sz]ed\b` patterns described in §4.1. Removing those is a precision improvement,
not a regression.

## 8. Reproducibility & artefacts

| Artefact | Location |
|----------|----------|
| Pattern definitions and labelling logic | `quality_pipeline.py` (reference design with optional Claude API integration) and the inline scripts described in §3 |
| Final GC labels | `json_data_gc_labeled/*.json` |
| Final SP labels | `json_labeled_v2/*.json` |
| Corpus build script | `build_corpus.py` (auto-prefers labelled directories; deterministic) |
| Published flat corpus | `docs/corpus.json` (in `lszoszk/generalcomments`) |
| Build manifest with sha256 of every output | `docs/manifest.json` |
| Build diagnostics (orphans, mismatches) | `docs/build_report.txt` |
| Public-facing methodology summary | website *About* page → *Methodology* block, links to this file |

To rebuild the corpus from sources:

```bash
# 1. (optional) re-run the labelling pipeline if patterns changed
#    — see quality_pipeline.py for the canonical reference; the inline
#      scripts used in this revision are committed with the labelled
#      output dirs.

# 2. rebuild flat corpus from labelled paragraph files + metadata
python3 build_corpus.py --out /path/to/generalcomments-repo/docs

# 3. inspect diagnostics
cat /path/to/generalcomments-repo/docs/build_report.txt
```

## 9. Versions and revision history

| Version | Commit | Date | Headline change |
|---------|--------|------|-----------------|
| v1 | `4cd6847` | 2026-04 | First mass keyword pass: +624 GC paragraphs, +1006 SP paragraphs labelled |
| v2 (internal) | — | — | Tightened patterns; never published |
| v3 (internal) | — | — | Removed `social_security`, `social_protection`, `forced_displacement`, `sexual_violence`, `alien` from problematic labels |
| v4 | `904c80b` | 2026-04-28 | First published clean-up: +78 high-precision GC labels; net −79 false-positive Poverty labels |
| v5 | `527cf75` | 2026-04-28 | Comprehensive SP pass: +673 SP labels; large gains for Persons deprived of their liberty (+245), Disabilities (+169), Refugees (+93) |
| v6 | `6063370` | 2026-04-28 | Pattern refinement: `corporal_punishment`→Children, `disadvantaged groups`→Poverty, `insufficient means`→Poverty, `sexual and reproductive freedom`→Women/girls; SP `marginalized`-only Poverty labels removed (40 paragraphs) |
| v6.1 | `a96094b` | 2026-04-28 | Audit of `corporal punishment` pattern: removed false-positive `Children` label from `CCPR_GC34 ¶26` (general expression-law context, no child reference); pattern documented as requiring child-context co-occurrence going forward |
| v7 | `acfc52c` | 2026-04-28 | Synchronised with OHCHR catalogue. Ingested 5 new GCs adopted 2024–2026: `E/C.12/GC/27` (environment), `CMW/C/GC/6` (Global Compact), joint `CMW/C/GC/7 + CERD/C/GC/38` and `CMW/C/GC/8 + CERD/C/GC/39` (xenophobia), `CEDAW/C/GC/30/Add.1` (Women, Peace and Security). +497 paragraphs, +5 documents. Fixed wrong year on `CED/C/GC/1` (2003 → 2023). Added "last synchronised" date on the website About page. |
| v8 | (this commit) | 2026-04-28 | Metadata audit and schema enrichment. Phase 1 fixes: cast all `Adoption Year` to int (39 GC + 65 SP), merged SP `Adoption year` lowercase variant, fixed CCPR GC31 signature typo, removed orphan CRC-GC18-Harmful (non-Rev), standardised 18 outlier links to canonical `tbinternet.ohchr.org/Download.aspx`. Phase 2 adds: `paragraphCount`, `wordCount`, `labelCount`, `ohchrSymbol`, `firstAddedAt`, `lastVerifiedAt`, `articles`, `status`, `supersedes`/`supersededBy`, `jointWith`, `languagesAvailable`, `alternativeSignatures`. Phase 3 adds: hand-written one-sentence Committee-voice `abstract` for all 186 GCs. `topicTags` deferred to backlog (TODO_LATER.md). Net: GC count 187 → 186, schema gains 12 optional fields. |

## 13. Synchronisation with OHCHR (v7, April 2026)

The corpus is not auto-pulled from OHCHR; new General Comments must be ingested
manually as they are adopted. The procedure used in v7 is recorded here for
future synchronisations.

### 13.1 Discovering gaps

1. Browse the OHCHR Treaty Body database
   ([TBSearch.aspx](https://tbinternet.ohchr.org/_layouts/15/treatybodyexternal/TBSearch.aspx?Lang=en))
   and the per-committee General Comments pages on `ohchr.org/en/treaty-bodies/{committee}/general-comments`.
2. Compare the latest signature on each committee's page against
   `mysite_pythonanywhere/crc_gc_info.json` — the file holds the canonical
   metadata index of every document we ingest.
3. Joint General Comments are listed under both committees' numbering. We treat
   them as a single document but add it once per committee in the metadata so
   that committee-filtered searches return them under either filter.

### 13.2 Document format on OHCHR

Each document has a permanent landing page at
`tbinternet.ohchr.org/_layouts/15/treatybodyexternal/Download.aspx?symbolno={URL-ENCODED-SIGNATURE}&Lang=en`.
That page is plain HTML and contains, for each language, links to PDF, DOCX and
HTML versions hosted at `docstore.ohchr.org/SelfServices/FilesHandler.ashx?enc=...`.
The `enc=` token is per-document and rotates if the document is republished.

We use the **PDF** version because it is the layout-fixed, citable form that
matches our paragraph numbering. DOCX is occasionally cleaner but uses
inconsistent paragraph styles across committees.

### 13.3 Ingestion pipeline

Driver: `ingest_new_gcs.py` (in the repository root).

```
1. For each new GC:
   a. Fetch Download.aspx HTML.
   b. Parse with the regex
        title="English[^"]*pdf"[^>]*href="(https://docstore[^"]+)"
      to extract the English PDF URL.
   c. Download the PDF to new_gcs_pdf/.

2. Convert PDF → paragraphs:
   a. Open with PyMuPDF (fitz). Read text page by page.
   b. Strip running headers/footers (UN doc symbols, page numbers).
   c. Repair hyphenated line breaks and soft-wrapped lines.
   d. Split on `^\s*(\d{1,3})\.\s+` to recover numbered paragraphs.
   e. Drop empty/short fragments (TOC artefacts).

3. Apply v6 labelling patterns to each paragraph.

4. Write outputs to:
     - mysite_pythonanywhere/json_data/<output>.json     (raw paragraph file)
     - json_data_gc_labeled/<output>.json                (with labels)

5. Append metadata records to mysite_pythonanywhere/crc_gc_info.json with:
     File PATH, Name, Simplified Name, Signature, Adoption Date, Adoption Year,
     Committee (comma-separated for joint GCs), Link.

6. Rebuild the flat corpus with `python3 build_corpus.py --out <docs/>`.
```

### 13.4 v7 results

| Document | Paragraphs | Auto-labelled |
|----------|-----------:|--------------:|
| `E/C.12/GC/27` (environment) | 90 | 55 |
| `CMW/C/GC/6` (Global Compact) | 90 | 64 |
| `CMW/C/GC/7 + CERD/C/GC/38` (xenophobia general) | 108 | 100 |
| `CMW/C/GC/8 + CERD/C/GC/39` (xenophobia thematic) | 105 | 73 |
| `CEDAW/C/GC/30/Add.1` (WPS addendum) | 104 | 99 |
| **Total** | **497** | **391 (78.7 %)** |

The unusually high label rate on the xenophobia GCs is expected: they are
explicitly about migrants and non-citizens, so almost every paragraph triggers
those patterns.

### 13.5 Recommended cadence

OHCHR adopts roughly 5–10 General Comments per year across all nine treaty
bodies. We propose re-running the synchronisation step every six months.

## 10. Known limitations

- Patterns operate on isolated paragraph text. They cannot use cross-paragraph context
  (e.g. a paragraph that says "such persons" referring to migrants discussed two paragraphs
  earlier will not receive the Migrants label).
- Multi-word phrases broken across line boundaries by the original PDF-to-text pipeline
  may not match. We have not attempted to repair those line breaks.
- Negation is not handled. A sentence saying "this General Comment does not address
  refugees" would still receive the Refugees label.
- Coverage targets recall, not absolute precision. For research uses requiring
  near-zero false-positive labels (e.g. case-law style citation), spot-checking
  individual paragraphs is recommended.

## 11. How to cite this dataset

> Szoszkiewicz, Ł., & Kowalska, Z. (2026). *The Geneva Reporter — A paragraph-level search
> interface for UN Treaty Body General Comments*. Annotation pipeline v6, commit `6063370`.
> Available at https://github.com/lszoszk/generalcomments.

When citing an individual paragraph, please cite the underlying UN document
(e.g. `CRC/C/GC/25 ¶12`), not this database.

## 12. Contact and corrections

Issues, missing documents, suspected mislabels and pattern suggestions are very welcome:

- GitHub issues: https://github.com/lszoszk/generalcomments/issues
- Email: l.szoszkiewicz@amu.edu.pl

Corrections to individual paragraph labels are best filed as issues with the document
identifier and paragraph number; the maintainers will investigate whether the cause is a
broken pattern (fix the pattern, re-run pipeline) or a pattern gap (add a new pattern).

## 14. Document metadata schema (v8, April 2026)

After the v8 metadata audit, every General Comment record exposes the
following structured fields in `documents.json`. Fields are present whenever
known; consumers should treat them as optional. SP records expose the same
core fields but most of the new ones are GC-only.

| Field | Type | Origin | Description |
|-------|------|--------|-------------|
| `docId` | string (slug) | derived | Stable identifier for cross-referencing. |
| `type` | `"gc"` \| `"sp"` | derived | Document stream. |
| `name` | string | source | Full title. |
| `nameShort` | string | source | Compact title for cards. |
| `signature` | string | source | UN document signature (`E/C.12/GC/27`, `CCPR/C/GC/37` …). Not unique on its own — old CEDAW/CERD GCs share session-report signatures. |
| `committee` / `committees` | string / `string[]` | source | Issuing committee(s). For joint GCs, both committees are listed in `committees`. |
| `year` / `adoptionDate` | int / string | source | Year is always `int` after v8. |
| `link` | URL | source (standardised) | Canonical OHCHR download page. After v8, all are `tbinternet.ohchr.org/.../Download.aspx`. |
| `sourceFile` | filename | derived | The paragraph JSON used to build the corpus. |
| `paragraphCount` | int | computed | Count of paragraph entries in the source file. |
| `wordCount` | int | computed | Sum of word counts across all paragraphs. |
| `labelCount` | int | computed | Sum of concerned-group labels across all paragraphs (a single paragraph with three labels contributes 3). |
| `abstract` | string | hand-written | One-sentence summary in Committee voice (§14.1). |
| `articles` | `string[]` | regex from name + first paragraphs | Treaty-article references the GC interprets, e.g. `["Art. 12"]`. Populated for 124 of 186 GCs (titles of older procedural GCs do not name an article). |
| `status` | `"final"` \| `"revised"` \| `"superseded"` \| `"draft"` | curated | Defaults to `final`. Cross-references via `supersedes` / `supersededBy`. |
| `supersedes` / `supersededBy` | string \| null | curated | Signatures of the preceding/replacing GC. Currently used for `CRC GC10 → GC24` and `CAT GC1 → GC4`. |
| `jointWith` | `[{committee, signature}]` | curated | Structured cross-reference for joint GCs. Avoids parsing the awkward dual-signature into the `signature` field. |
| `alternativeSignatures` | `string[]` | curated | Earlier (non-revised) signatures kept as identifiers, e.g. CRC18 / CEDAW31. |
| `languagesAvailable` | `string[]` (UN codes) | curated default | Defaults to UN6 (`en, fr, es, ar, ru, zh`) for GCs and `["en"]` for SPs. Per-document scrape of OHCHR pages is on the backlog. |
| `ohchrSymbol` | string | derived | Canonical UN doc symbol used to construct the OHCHR Download URL. Pulled from the `Link` query string when available, otherwise from `Signature`. |
| `firstAddedAt` / `lastVerifiedAt` | ISO date | derived / today | Provenance trail: when this record was first ingested and when it was last reconciled with OHCHR. |
| `mandate` / `presented` | string (SP only) | source | Mandate-holder and presentation context for SP reports. 88 SP records still have these empty (backlog). |

### 14.1 Abstract authoring guidelines

The 186 abstracts were written by the maintainer in **Committee voice** —
each abstract describes what the Committee (or the joint Committees) "considers",
"recalls", "clarifies", "recommends", "affirms" or "elaborates", mirroring the
self-presentation conventions of UN treaty bodies.

Constraints applied during authoring:

- **Length:** 1–2 sentences, typically 30–55 words.
- **Voice:** Active, third-person Committee. No "this General Comment" framing.
- **Specificity:** Name the legal anchor (treaty article, principle, predecessor)
  whenever the document does. Avoid generic openers like "This document is about…".
- **Supersession honesty:** Where a GC has been replaced by a later one
  (e.g. CCPR GC6 → GC36), the abstract notes this in a parenthetical at the end.
- **Scope:** What the GC is about, not what it endorses. The abstract is a
  *navigational* aid, not editorial commentary on the underlying obligations.

The full set is stored under version control as `abstracts_data.py` for
reproducibility and for later editing.

### 14.2 Repair script

The deterministic Phase 1+2 repair (everything except abstracts) is performed
by `repair_metadata.py` and is idempotent — running it twice on the same input
produces the same output.

Phase 3 (abstracts) is loaded from `abstracts_data.py` and applied to the
metadata via a one-shot script at the end of v8 ingestion.

### 14.3 What is *not* in the schema

- `topicTags` — subject-matter tags. Deferred (see `TODO_LATER.md`).
- `country` — country-visit tag for SP reports. Deferred (SP-only).
- `hrcSession` / `gaSession` — session number for SP reports. Deferred.
- `reportType` (SP) — `annual` / `country-visit` / `thematic` / `communications`.
  Deferred.
- DOIs and academic citation counts — deliberately not added (see audit §3.4).
