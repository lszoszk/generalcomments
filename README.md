# UNHRDB — UN Human Rights Database

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.10495719.svg)](https://doi.org/10.5281/zenodo.10495719)
[![License: PolyForm Noncommercial](https://img.shields.io/badge/code-PolyForm%20Noncommercial-blue.svg)](LICENSE)
[![Dataset: CC BY-NC-SA 4.0](https://img.shields.io/badge/data-CC%20BY--NC--SA%204.0-green.svg)](LICENSE-DATA)
[![Hugging Face](https://img.shields.io/badge/dataset-Hugging%20Face-yellow.svg)](https://huggingface.co/datasets/lszoszk/treaty-bodies-general-comments)

UNHRDB is an open-source research environment for finding and citing what UN
human rights mechanisms actually wrote. It treats UN documents as structured,
paragraph-level research material while keeping every result connected to its
original document symbol and context.

- **Live application:** https://lszoszk.github.io/generalcomments/
- **General Comments dataset:** https://huggingface.co/datasets/lszoszk/treaty-bodies-general-comments
- **MCP integration:** https://github.com/lszoszk/mcp-unhrdb
- **Methodology:** [METHODOLOGY.md](METHODOLOGY.md)
- **Document status audit:** [STATUS_AUDIT.md](STATUS_AUDIT.md)

## Coverage

The July 2026 public build contains 320,018 searchable paragraphs across 6,081
documents:

| Collection | Coverage |
|---|---:|
| Treaty Body General Comments and Recommendations | 187 documents |
| Individual-communication jurisprudence | 4,334 cases from 8 mechanisms |
| Thematic Special Procedures reports | 1,560 reports from 46 mandates |

Coverage changes as the source collections are synchronised. The application
publishes build dates, collection-level provenance, and known gaps alongside
the data.

## What it does

- Searches legal text at paragraph level with exact phrases, implicit/explicit
  `AND`, `OR`, grouped exclusions (`A NOT B` or `A -B`), prefix wildcards, and
  filters. A positive term is required for exclusions so every query stays on
  the indexed path; negative-only searches are rejected with an explanation.
- Keeps General Comments, jurisprudence, and Special Procedures as distinct
  source collections rather than blending their authority or provenance.
- Opens results in a source-first document reader with paragraph identifiers,
  context, bookmarks, notes, and citation export.
- Reconstructs and audits document structure, OCR provenance, footnotes, and
  links to authoritative UN records.
- Provides an experimental extractive Ask workflow that returns verbatim
  Committee passages rather than generated legal answers.
- Exposes General Comments and UHRI recommendations to MCP-capable clients via
  the companion `mcp-unhrdb` server.

## Run locally

The published application is static and can be served directly from `docs/`:

```bash
git clone https://github.com/lszoszk/generalcomments.git
cd generalcomments
python3 -m http.server 8000 --directory docs
```

Then open http://127.0.0.1:8000. Corpus preparation and audit scripts use
Python; their dependencies are listed in `requirements.txt`.

## Data and reproducibility

The General Comments and Recommendations corpus is distributed as Parquet on
[Hugging Face](https://huggingface.co/datasets/lszoszk/treaty-bodies-general-comments).
The repository contains the preparation, ingestion, validation, and audit code
used to produce the public build. See [METHODOLOGY.md](METHODOLOGY.md),
[OCR_PIPELINE.md](OCR_PIPELINE.md), and the public coverage information in the
application for limitations and provenance.

The Hugging Face package covers General Comments and Recommendations. The
jurisprudence and Special Procedures collections are not currently distributed
as part of that dataset package.

## Citation

For the evolving software, use the concept DOI:

> Szoszkiewicz, Ł., & Kowalska, Z. (2026). *UNHRDB — UN Human Rights
> Database* (Version 2.0.1) [Computer software]. Zenodo.
> https://doi.org/10.5281/zenodo.10495719

GitHub also exposes machine-readable citation metadata from
[`CITATION.cff`](CITATION.cff). Cite a fixed Zenodo version when an exact
software snapshot is required for reproducibility.

When relying on a legal proposition or quoting a paragraph, cite the original
UN document symbol and printed paragraph number, for example `CRC/C/GC/25 ¶12`.
The database citation supplements rather than replaces the primary legal
source.

## Licensing

This repository contains distinct works under distinct terms:

- **Software:** PolyForm Noncommercial License 1.0.0; research, education,
  non-profit, and personal use are permitted, while commercial use requires a
  separate licence. See [LICENSE](LICENSE).
- **Curated dataset and annotations:** Creative Commons
  Attribution-NonCommercial-ShareAlike 4.0 International, see
  [LICENSE-DATA](LICENSE-DATA).
- **Underlying UN documents:** remain subject to United Nations content terms
  and are not re-licensed by this project.

See [NOTICE](NOTICE) for the detailed boundary between software, curation, and
source documents.

## Authors and contact

- Łukasz Szoszkiewicz, Adam Mickiewicz University,
  [ORCID 0000-0001-6671-2893](https://orcid.org/0000-0001-6671-2893)
- Zuzanna Kowalska, Adam Mickiewicz University

Issues, missing documents, and corrections can be reported through the GitHub
issue tracker. General contact: l.szoszkiewicz@amu.edu.pl.
