---
language:
  - en
license: cc-by-nc-sa-4.0
license_name: "CC BY-NC-SA 4.0"
license_link: "https://creativecommons.org/licenses/by-nc-sa/4.0/"
multilinguality:
  - monolingual
size_categories:
  - 1K<n<10K
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

This dataset packages the JSON files from the project's `General Comments/`
folder as a Hugging Face-ready parquet dataset. Each row is a text segment
from a General Comment or General Recommendation, paired with zero or
more concerned-group labels and enriched with document metadata from
`GC_info.json`.

Current package statistics:

- 181 source JSON documents
- 6,608 text segments
- 4,206 segments with at least one label
- 19 distinct labels
- 110 General Comments and 71 General Recommendations
- 3 joint documents

Treaty bodies represented:

- `CAT`, `CCPR`, `CED`, `CEDAW`, `CERD`, `CESCR`, `CMW`, `CRC`, `CRPD`

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
  "row_id": "CAT_GC1_art.3_v1:1",
  "source_file": "Annotated_CAT_GC1_art.3_v1.json",
  "document_slug": "CAT_GC1_art.3_v1",
  "document_title": "General Comment No. 01: Implementation of article 3 of the Convention in the context of article 22",
  "document_title_short": "GC1: Implementation of Art. 3 in the context of Art. 22",
  "signature": "A/53/44",
  "adoption_date": "21 Nov 1997",
  "adoption_date_iso": "1997-11-21",
  "adoption_year": 1997,
  "committee": "CAT",
  "committee_codes": ["CAT"],
  "source_url": "https://tbinternet.ohchr.org/_layouts/15/treatybodyexternal/Download.aspx?symbolno=A%2F53%2F44&Lang=en",
  "treaty_body_codes": ["CAT"],
  "is_joint_document": false,
  "document_type": "general_comment",
  "document_number": 1,
  "segment_position": 1,
  "labels": [],
  "text": "Article 3 is confined in its application to cases where there are substantial grounds for believing that the author would be in danger of being subjected to torture as defined in article 1 of the Convention.",
  "text_length_chars": 207,
  "text_length_words": 36
}
```

### Data Fields

- `row_id` — synthetic unique identifier built from `document_slug` and `segment_position`
- `source_file` — source JSON filename
- `document_slug` — filename-derived document identifier
- `document_title`, `document_title_short` — titles from `GC_info.json`
- `signature` — official UN signature (e.g. `CRC/C/GC/25`)
- `adoption_date`, `adoption_date_iso`, `adoption_year` — adoption metadata
- `committee`, `committee_codes` — treaty body codes
- `source_url` — link to the original UN PDF
- `treaty_body_codes` — normalised codes parsed from the filename
- `is_joint_document` — boolean
- `document_type` — `general_comment` or `general_recommendation`
- `document_number` — document number parsed from the filename
- `segment_position` — 1-based position within the source file
- `labels` — zero or more concerned-group labels
- `label_count`, `has_labels` — label coverage flags
- `text` — normalised segment text
- `text_length_chars`, `text_length_words` — length statistics

## Dataset Creation

### Source Data

Annotated JSON files from the project's `General Comments/` folder, each
following the schema:

```json
{ "ID": 1, "Labels": ["Children"], "Text": "..." }
```

### Processing

The HF package is produced from the local preparation script
`scripts/prepare_treaty_bodies_hf.py`. The script:

1. Reads only `General Comments/*.json`
2. Uses `GC_info.json` as the document metadata source
3. Normalises line breaks and whitespace in `Text`
4. Preserves multi-label annotations in `Labels`
5. Joins source files to metadata by filename
6. Normalises committee codes and adoption dates
7. Validates that every source file has matching metadata and that
   committee codes agree across `GC_info.json` and filenames
8. Writes a row-level parquet split, `document_index.parquet`, and
   `dataset_metadata.json`

### Label Distribution

Most frequent labels in the current package:

- `Children`: 2,210
- `Women/girls`: 1,487
- `Persons with disabilities`: 687
- `Migrants`: 528
- `Indigenous peoples`: 335
- `Persons deprived of their liberty`: 316
- `Refugees & asylum-seekers`: 248
- `Adolescents`: 232
- `Persons living in rural/remote areas`: 220
- `Persons affected by armed conflict`: 209

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

- Labels are sparse: 2,402 rows have no labels in the current source files.
- `GC_info.json` contains one extra metadata entry,
  `Annotated_CRC-GC18-Harmful.json`, that does not correspond to a current
  file in `General Comments/`.
- Two metadata records contain a year/date mismatch in `GC_info.json`;
  the package preserves the raw source year in `adoption_year_source` and
  exposes the normalised year in `adoption_year`.
- Labels are generated through keyword matching, so false positives,
  false negatives, and missed contextual mentions are possible.
- Three rows are missing an `ID`; use `segment_position` or `row_id` as
  the stable row identifier.
- No predefined train/validation/test split.

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

dataset = load_dataset(
    "lszoszk/treaty-bodies-general-comments",
    split="train",
)

# Document-level metadata
document_index = pd.read_parquet(
    "hf://datasets/lszoszk/treaty-bodies-general-comments/document_index.parquet"
)
```
