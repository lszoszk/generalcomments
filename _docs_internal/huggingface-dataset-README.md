---
language:
  - en
license: cc-by-nc-sa-4.0
multilinguality:
  - monolingual
size_categories:
  - 1K<n<10K
viewer: true
source_datasets:
  - original
task_categories:
  - text-classification
  - text-retrieval
task_ids:
  - multi-label-classification
pretty_name: "Treaty Bodies General Comments"
tags:
  - treaty-bodies
  - general-comments
  - human-rights
  - international-law
  - legal
  - policy
annotations_creators:
  - expert-generated
language_creators:
  - found
configs:
  - config_name: default
    data_files:
      - split: train
        path: data/train-00000-of-00001.parquet
---

# Treaty Bodies General Comments

A paragraph-level dataset of General Comments and General Recommendations
adopted by the nine UN human-rights Treaty Bodies, with concerned-group
labels and document metadata. Companion to the
[UNHRD search interface](https://lszoszk.github.io/generalcomments/).

## Licence

The curated dataset (paragraph segmentation, label annotation, document
metadata enrichment, footnote and section work) is released under
[**Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)**](https://creativecommons.org/licenses/by-nc-sa/4.0/).

You are free to:

- **Share** — copy and redistribute the material in any medium or format
- **Adapt** — remix, transform, and build upon the material

Under the following terms:

- **Attribution** — give appropriate credit (see Citation below), provide
  a link to the licence, and indicate if changes were made.
- **NonCommercial** — you may not use the material for commercial purposes
  without prior written permission from the authors.
- **ShareAlike** — if you remix, transform, or build upon the material,
  you must distribute your contributions under the same licence.

The underlying General Comments and General Recommendations are issued
by United Nations Treaty Bodies and remain under the
[UN's content terms](https://www.un.org/en/about-us/copyright);
the curation work — segmentation, labelling, metadata enrichment — is
the licensable contribution to which CC BY-NC-SA 4.0 applies.

For commercial licensing enquiries: <l.szoszkiewicz@amu.edu.pl>.

## Dataset Summary

This is the **v2** package built from the live UNHRD corpus
(`https://lszoszk.github.io/generalcomments/`). Each row is a paragraph
from a UN Treaty Body General Comment / General Recommendation, with
section path, footnotes, footnote cross-reference resolutions
(Ibid./op. cit./"see paragraph N above"), preamble flag, concerned-group
labels, and document-level metadata.

What's new in v2 vs. the previous package:

- **Footnotes** — full text + inline references, present on 3,520
  paragraph-level footnote entries (~96% of GC paragraphs that
  originally had footnotes are now reconstructed and verified).
- **Section path** — every paragraph is annotated with its section
  hierarchy (e.g. `["II. Substantive issues", "B. Right to inclusive
  education"]`). 6,346 / 7,185 paragraphs have section info; 187 / 187
  documents have `footnotes_verified: true` with explicit
  `footnotes_source` provenance (PDF extraction, HRI compilation, OHCHR
  DOCX, user-verified, etc.).
- **Cross-reference resolution** — 249 footnotes annotated as
  `is_ibid`, `is_cross_ref`, or `is_self_ref`, each paired with
  `resolved_text` so downstream pipelines can hop between references
  without re-parsing "Ibid., para. 12 above".
- **Preamble flag** — 26 paragraphs that sit outside the numbered
  sequence (resolution-style preambles) carry `is_preamble: true` and
  `preamble_source`.
- **Six new General Comments** added since v1: re-extracted CESCR GC5
  from HRI Vol I (the prior package contained the wrong text — GC20
  body); recovered footnotes for CAT GC4, CRC GC15, GC16, GC17, GC22
  (joint with CMW GC3), GC23 (joint with CMW GC4); CAT-OP GC1; CEDAW
  GC29, GC31 (joint with CRC GC18) and the Indigenous Women addendum
  CEDAW GR39 (re-extracted from DOCX, 61 ¶ + 66 footnotes).

Current package statistics:

- **187** GC source documents (was 181)
- **7,185** paragraph-level segments (was 6,608)
- **5,060** segments with at least one concerned-group label (was 4,206)
- **3,520** footnote entries across **2,310** paragraphs
- **26** preamble paragraphs (`is_preamble: true`)
- **6,346** paragraphs with section path
- 19 distinct concerned-group labels

Treaty bodies represented:

- `CAT`, `CAT-OP`, `CCPR`, `CED`, `CEDAW`, `CERD`, `CESCR`, `CMW`,
  `CRC`, `CRPD`

## Supported Tasks

- Multi-label classification of concerned-group labels in treaty body text segments
- Semantic search and retrieval over segmented general comments
- Weak supervision, label enrichment, taxonomy alignment work on human-rights text

## Languages

English (the source UN documents in this package are English-language editions).

## Dataset Structure

Single `train` split stored as parquet. Supplemental files:

- `document_index.parquet` — one row per source document with title,
  signature, committee metadata, adoption date, source URL, and
  document-level label coverage statistics
- `GC_info.json` — bundled source metadata used to enrich the dataset
- `scripts/prepare_treaty_bodies_hf.py` — preparation script

### Data Instances

```json
{
  "row_id": "cat-op-gc-1::1",
  "paragraph_id": "cat-op-gc-1-0001",
  "document_id": "cat-op-gc-1",
  "document_title": "General comment No. 1 (2024) on places of deprivation of liberty (article 4)",
  "document_title_short": "SPT GC1: places of deprivation of liberty (Art. 4)",
  "signature": "CAT/OP/GC/1",
  "adoption_date": "11 February 2024",
  "adoption_year": 2024,
  "committee": "CAT-OP",
  "committees": ["CAT-OP"],
  "source_url": "https://tbinternet.ohchr.org/...",
  "is_joint_document": false,
  "footnotes_verified": true,
  "footnotes_source": "ohchr-pdf-no-fn-zone",
  "segment_position": 1,
  "paragraph_number": 1,
  "section": ["I. Introduction"],
  "is_preamble": false,
  "text": "The Subcommittee considers that to advance the prevention…",
  "labels": ["Persons deprived of their liberty"],
  "footnotes": [
    {
      "n": 2,
      "text": "Optional Protocol, preamble.",
      "is_ibid": false,
      "is_cross_ref": false,
      "is_self_ref": false,
      "resolved_text": ""
    },
    {
      "n": 3,
      "text": "Ibid., art. 1.",
      "is_ibid": true,
      "is_cross_ref": false,
      "is_self_ref": false,
      "resolved_text": "Optional Protocol, preamble."
    }
  ],
  "footnote_count": 3
}
```

### Data Fields

**Identity**

- `row_id` — synthetic stable identifier `<document_id>::<segment_position>`
- `paragraph_id` — UNHRD canonical id (e.g. `crc-c-gc-25-0042`)
- `document_id` — UNHRD doc slug (e.g. `crc-c-gc-25`)

**Document metadata** (denormalised on every row)

- `document_title`, `document_title_short`, `signature`, `ohchr_symbol`,
  `source_url`
- `adoption_date`, `adoption_year`
- `committee`, `committees` — single-string + list (joint comments
  carry both committee codes)
- `is_joint_document` — boolean
- `alternative_ids` — additional docId slugs (some joint comments are
  reachable via two docIds)
- `articles` — convention articles cited in the front matter
- `languages_available` — ISO codes for available official translations
- `status` — `final` or revision marker
- `first_added_at`, `last_verified_at` — ISO date strings
- `footnotes_verified` — boolean (true on 187/187 docs)
- `footnotes_source` — provenance of the footnote layer
  (`pdf-extraction-pipeline`, `ohchr-docx`, `user-verified`,
  `hri-compilation-pdf`, `ohchr-pdf-no-fn-zone`, `verified-by-pattern-analogy`)

**Paragraph fields**

- `segment_position` — 1-based position within the document
- `paragraph_number` — official ¶ number (may differ from segment
  position when the doc has unnumbered preamble entries; preamble rows
  are `paragraph_number: 0`)
- `text` — normalised paragraph text
- `text_length_chars`, `text_length_words` — length stats
- `labels` — zero or more concerned-group labels
- `label_count`, `has_labels` — label coverage flags

**v2 enrichment**

- `section` — list of strings, the section hierarchy this paragraph
  sits under (root → leaf). Empty list for documents without sections.
- `is_preamble` — true for the 26 paragraphs that sit outside the
  numbered sequence (resolution-style preambles)
- `preamble_source` — provenance of the preamble extraction
- `footnotes` — list of struct entries:
  - `n` — footnote number as printed in the source
  - `text` — footnote body
  - `is_ibid`, `is_cross_ref`, `is_self_ref` — boolean flags
  - `references_note`, `references_para` — when set, point at the
    referenced footnote / paragraph for cross-references
  - `resolved_text` — for ibid./op.cit./inline cross-references, the
    materialised text of the original target (so downstream pipelines
    can read "Optional Protocol, preamble." instead of "Ibid.")
- `footnote_count` — convenience count of `footnotes` length

## Dataset Creation

### Source Data

The v2 package is built directly from the live UNHRD curated corpus
(`docs/corpus.json` + `docs/documents.json` in the
[lszoszk/generalcomments](https://github.com/lszoszk/generalcomments)
repository). The corpus is the same data the dashboard at
<https://lszoszk.github.io/generalcomments/> serves at search time.

Provenance per document is exposed in `footnotes_source`:

- `pdf-extraction-pipeline` — extracted from OHCHR PDF via PyMuPDF
- `ohchr-docx` — extracted from OHCHR DOCX (e.g. CEDAW GR39)
- `hri-compilation-pdf` — recovered from HRI/GEN/1/Rev.9 Vol. I/II
- `user-verified` — manually checked against the source by a curator
- `ohchr-pdf-no-fn-zone` — PDF has no inline footnotes
- `verified-by-pattern-analogy` — pattern matched against a sister GC

### Processing

The HF v2 package is produced from `_docs_internal/build_hf_dataset.py`
(in the source repo). The script:

1. Reads `docs/corpus.json` (the unified UNHRD corpus) and
   `docs/documents.json` (per-document metadata)
2. Filters to `type == "gc"` (this dataset covers General Comments
   only — JUR / SP previews are separate)
3. Sorts paragraphs by `(docId, idx)` for stable parquet output
4. Maps each paragraph onto the v2 schema (above), denormalising the
   document metadata onto every row
5. Builds a per-document `document_index.parquet` with paragraph
   counts, footnote counts, and provenance
6. Writes a `dataset_metadata.json` build summary

### Label Distribution

Top concerned-group labels in the v2 package (full distribution in
`dataset_metadata.json`):

- `Children`: 2,390
- `Women/girls`: 1,678
- `Persons with disabilities`: 800
- `Migrants`: 667
- `Persons deprived of their liberty`: 365
- `Indigenous peoples`: 281
- `Persons affected by armed conflict`: 262
- `Refugees & asylum-seekers`: 259
- `Adolescents`: 233
- `Persons living in rural/remote areas`: 215

### Labels and Annotation Process

Concerned-group labels are generated through rule-based keyword matching.
The repository script `labels_annotation.py` defines a mapping from each
label to a curated list of keywords and phrases, then assigns every label
whose keyword list matches a paragraph's text. These labels are best
understood as **heuristic weak labels** for search, filtering, and
exploratory analysis — not exhaustive expert annotations.

Full label inventory (19):

`Adolescents`, `Children`, `Children in alternative care`,
`Indigenous peoples`, `Internally displaced persons`, `LGBTI+`,
`Migrants`, `Non-citizens and stateless`, `Persons affected by armed conflict`,
`Persons affected by natural disasters`, `Persons deprived of their liberty`,
`Persons in street situations`, `Persons living in poverty`,
`Persons living in rural/remote areas`, `Persons living with HIV/AIDS`,
`Persons with disabilities`, `Refugees & asylum-seekers`,
`Roma, Gypsies, Sinti and Travellers`, `Women/girls`.

## Considerations for Use

- **Labels are weak/heuristic.** Concerned-group labels are generated
  through curated keyword matching (see `labels_annotation.py` in the
  source repository). False positives, false negatives, and missed
  contextual mentions are possible. Treat them as a starting point for
  faceted search and weak supervision, not as gold-standard expert
  annotations.
- **Labels are sparse on some documents.** 2,125 / 7,185 paragraphs
  have no labels (29%). This includes most pre-2000 CCPR Comments and
  some procedural / definitional paragraphs.
- **Footnote provenance varies.** All 187 documents are
  `footnotes_verified: true`, but the `footnotes_source` differs:
  some are PDF-extracted with strong OCR confidence, some recovered
  from the HRI compilation, some manually verified by a curator. For
  high-stakes uses, consult the `footnotes_source` field.
- **Cross-reference resolution is partial.** 249 of 3,520 footnotes
  carry `is_ibid` / `is_cross_ref` / `is_self_ref` annotations with
  `resolved_text`. The remaining footnotes are presented verbatim from
  the source PDF and may include un-resolved "Ibid." or "op. cit."
  references that downstream pipelines should treat with care.
- **Section paths are auto-extracted.** Some documents (notably CERD
  GR31, CESCR GC13) have rich Roman+Letter+Arabic 3-level hierarchies
  that the auto-extractor handles ~95% correctly with occasional wrap
  artifacts on multi-line headings.
- **No predefined train/validation/test split.** Users should split
  by `document_id` to avoid leakage if training models.
- **Source UN documents are not under this licence.** The CC BY-NC-SA
  4.0 covers the curation work; the underlying General Comments
  remain under United Nations content terms.

## Citation

When citing the dataset:

```
Szoszkiewicz, Ł. & Kowalska, Z. (2026). UNHRD — Treaty Bodies General
Comments dataset (paragraph-level corpus with concerned-group labels).
https://huggingface.co/datasets/lszoszk/treaty-bodies-general-comments.
Licensed under CC BY-NC-SA 4.0.
```

```bibtex
@dataset{szoszkiewicz_kowalska_unhrd_2026,
  author    = {Szoszkiewicz, Łukasz and Kowalska, Zuzanna},
  title     = {UNHRD — Treaty Bodies General Comments dataset
               (paragraph-level corpus with concerned-group labels)},
  year      = {2026},
  publisher = {Hugging Face},
  url       = {https://huggingface.co/datasets/lszoszk/treaty-bodies-general-comments},
  license   = {CC BY-NC-SA 4.0}
}
```

When citing individual paragraphs in academic work, please reference the
**original UN document signature** (e.g. `CRC/C/GC/25 ¶12`), not this
dataset.

## Companion Software

The interactive search dashboard built on this corpus is open-source
under AGPL-3.0:

- Live: <https://lszoszk.github.io/generalcomments/>
- Code: <https://github.com/lszoszk/generalcomments>

## Direct Use

```python
from datasets import load_dataset
import pandas as pd

# Paragraph-level dataset
ds = load_dataset(
    "lszoszk/treaty-bodies-general-comments",
    split="train",
)
print(ds)
# Dataset({
#   features: ['row_id', 'paragraph_id', 'document_id', ...,
#              'section', 'is_preamble', 'footnotes', 'footnote_count'],
#   num_rows: 7185
# })

# Filter to paragraphs about a specific concerned group
children = ds.filter(lambda r: "Children" in r["labels"])
print(len(children), "child-related paragraphs")

# Document-level metadata
documents = pd.read_parquet(
    "hf://datasets/lszoszk/treaty-bodies-general-comments/document_index.parquet"
)
print(documents.shape)
```

### Recipes

```python
# Cross-references resolved (Ibid./op.cit./see para N)
xrefs = ds.filter(
    lambda r: any(
        f["is_ibid"] or f["is_cross_ref"] or f["is_self_ref"]
        for f in r["footnotes"]
    )
)

# Paragraphs in a specific section
women_in_conflict = ds.filter(
    lambda r: r["document_id"] == "cedaw-c-gc-30-add-1"
              and r["section"]
              and "Recovery" in r["section"][0]
)
```
