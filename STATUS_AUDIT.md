# General Comment status audit

**Verified:** 13 July 2026  
**Scope:** 187 General Comments and General Recommendations in the public UNHRDB catalogue

## Method

A document is marked `superseded` only when an official UN text expressly says
that the earlier text is replaced or superseded. Similar subject matter, a newer
date, or a broader discussion of the same treaty article is not enough.

The audit keeps four other relationships distinct:

- `revised`: the record is an official revised version (`/Rev.1`);
- `corrected`: the record incorporates an official corrigendum (`/Corr.1`);
- `updatedBy`: later guidance expressly complements and updates the text, which
  remains relevant and should be read together with the update;
- `supplementedBy`: a later addendum supplements rather than replaces the text.

The reproducible metadata pass is `scripts/apply_gc_status_audit.py`. It updates
both the source metadata and the public `docs/documents.json` catalogue and can
be run with `--check` in validation workflows.

## Express supersessions

| Earlier text | Replacement | Official basis |
|---|---|---|
| CAT GC1 | CAT GC4 | [CAT/C/GC/4](https://docs.un.org/en/CAT/C/GC/4) |
| CRC GC10 | CRC GC24 | [CRC/C/GC/24](https://docs.un.org/en/CRC/C/GC/24) |
| HRC GC2 | Consolidated reporting guidelines | [CCPR/C/66/GUI/Rev.2](https://docs.un.org/en/CCPR/C/66/GUI/Rev.2) |
| HRC GC3 | HRC GC31 | [CCPR/C/21/Rev.1/Add.13](https://docs.un.org/en/CCPR/C/21/Rev.1/Add.13) |
| HRC GC4 | HRC GC28 | [CCPR/C/21/Rev.1/Add.10](https://docs.un.org/en/CCPR/C/21/Rev.1/Add.10) |
| HRC GC5 | HRC GC29 | [CCPR/C/21/Rev.1/Add.11](https://docs.un.org/en/CCPR/C/21/Rev.1/Add.11) |
| HRC GC6 and GC14 | HRC GC36 | [CCPR/C/GC/36](https://docs.un.org/en/CCPR/C/GC/36) |
| HRC GC7 | HRC GC20 | [HRI/GEN/1/Rev.9 (Vol. I)](https://docs.un.org/en/HRI/GEN/1/Rev.9(Vol.I)) |
| HRC GC8 | HRC GC35 | [CCPR/C/GC/35](https://docs.un.org/en/CCPR/C/GC/35) |
| HRC GC9 | HRC GC21 | [HRI/GEN/1/Rev.9 (Vol. I)](https://docs.un.org/en/HRI/GEN/1/Rev.9(Vol.I)) |
| HRC GC10 | HRC GC34 | [CCPR/C/GC/34](https://docs.un.org/en/CCPR/C/GC/34) |
| HRC GC13 | HRC GC32 | [CCPR/C/GC/32](https://docs.un.org/en/CCPR/C/GC/32) |

## Other version relationships

- CEDAW GR35 expressly **complements and updates** GR19 and says the two should
  be read together. GR19 therefore remains `final` with `updatedBy`, not
  `superseded` ([CEDAW/C/GC/35](https://docs.un.org/en/CEDAW/C/GC/35)).
- CEDAW GR30 has an official addendum and remains `final` with
  `supplementedBy` ([CEDAW/C/GC/30/Add.1](https://docs.un.org/en/CEDAW/C/GC/30/Add.1)).
- CRC GC7 and joint CEDAW GR31/CRC GC18 are official `/Rev.1` texts.
- CRC GC9 is represented by the corrected `/Corr.1` text.

## Result

The audited catalogue contains 13 `superseded`, 2 `revised`, 1 `corrected`,
and 171 `final` records. `updatedBy` and `supplementedBy` are relationships on
otherwise current records and are not counted as supersessions.
