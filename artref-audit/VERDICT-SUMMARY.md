# Article-reference audit — verification results

Verifier: Opus 5. Date: 2026-07-27. Sources read: `docs/corpus.json`, all 40 `docs/jur/shards/*`,
all 46 `docs/sp/shards/*` (320,018 paragraph records indexed; all 476 flagged items resolved,
0 missing), plus the 18-instrument treaty bundle from `https://150.254.115.204/ask-api/api/treaties`.

Outputs: `verdicts.jsonl` (328 verdicts), `c2-forms.jsonl` (148 written-form records).

**Nothing outside these two files and this summary was modified.**

## Coverage

| Category | In findings.json | Verified | Note |
|---|--:|--:|---|
| A-HIGH | 108 | **108** | every item |
| C1 | 9 | **9** | every item, every occurrence of the article number in each paragraph |
| A-LOW | 211 | **211** | the required 20-item seeded random sample **plus a full pass** (see below) |
| C2 | 148 | **148** | written-form catalogue |

No item was truncated or skipped.

## Verdict counts

| Category | home-correct | relink | plain-text | total |
|---|--:|--:|--:|--:|
| A-HIGH | 10 | 2 | 96 | 108 |
| A-LOW | 168 | 13 | 30 | 211 |
| C1 | 8 | 1 | 0 | 9 |
| **All** | **186** | **16** | **126** | **328** |

Relink targets: **ICCPR-OP1 ×12**, ICCPR ×2, ICESCR ×2. Every relink target is present in the
treaty bundle, so each one becomes a working `citedArticles` entry.

Where the 126 `plain-text` references actually belong:

| Instrument | count |
|---|--:|
| national constitution | 70 |
| national statute / code / decree / royal decree | 28 |
| European Convention on Human Rights | 11 |
| American Convention on HR / Protocol of San Salvador | 4 |
| Minsk Convention (CIS legal assistance) | 3 |
| 1951 Refugee Convention | 2 |
| Hague Convention on Civil Aspects of International Child Abduction | 2 |
| UNCLOS, Geneva Convention III, VCLT, ILO C169, UN Model Treaty on Extradition | 1 each |
| OCR phantom number (no such article exists) | 1 |

## A-LOW sample result — **the LOW bucket needed a full pass, and got one**

Seeded random sample (seed 20260727) of 20 of the 211 A-LOW items:
indices `3, 6, 13, 18, 20, 22, 31, 50, 63, 64, 82, 86, 89, 104, 137, 143, 153, 162, 198, 206`.

**16 correct, 4 wrong** — over the threshold of 3. The four:

| item | flagged home | actually |
|---|---|---|
| `e-1991-23-0005` art 2 | ICESCR | ICCPR ("…of *that* Covenant" = ICCPR) |
| `cat-c-67-d-813-2017-0044` art 99 | CAT | Third Geneva Convention of 1949, arts 99–108 |
| `ccpr-c-88-d-1187-2003-0017` art 5 | ICCPR | ICCPR-OP1 art 5(2)(a) |
| `crpd-c-21-d-34-2015-0005` art 23 | CRPD | Spanish Constitution |

I therefore verified **all 211** A-LOW items rather than stopping at the sample.

**Full A-LOW result: 168 correct, 43 wrong (20.4 %)** — 30 `plain-text`, 13 `relink`.
The sample's 20 % error rate held across the whole bucket almost exactly.

## Systematic patterns

**1. A-HIGH is essentially a domestic-law bucket, and it is heavily duplicated boilerplate.**
96 of 108 A-HIGH items (89 %) are national constitutions or statutes. A single State-party
paragraph — Algeria's standard admissibility submission, *"…in accordance with the Constitution
(arts. 87 and 91), precautionary measures were implemented…"* — accounts for **26 verdict rows**
(13 near-identical paragraphs × 2 articles) across `ccpr-c-107…` to `ccpr-c-122-d-2398-2014`.
Spanish Constitution references in CRPD communications account for another 13. Roughly half of
A-HIGH could be cleared by de-duplicating recurring State-party boilerplate before review.

**2. The `A-HIGH`/`A-LOW` split misses the tail of a parenthetical series — this is the main
reason A-LOW is 20 % wrong.** The heuristic flags only the article number *adjacent* to the
instrument word; the rest of the same series drops into LOW as "bare Convention/Covenant matches
home term". `crpd-c-21-d-34-2015-0005` is the clean example: *"(arts. 35 and 40 of the
Constitution), the inclusion of persons with disabilities **(art. 49)**, access to and retention of
public employment **(art. 23)** and respect for human dignity **(art. 10)**"* — art 49 was flagged
A-HIGH, arts 23 and 10 were not. Same pattern in `crpd-c-26-d-48-2018-0010/0012`,
`crpd-c-29-d-47-2018-0011`, `e-c-12-79-d-222-2021-0043`. **Any priority scoring should propagate an
instrument anchor forward across a whole comma/`and` series, not just to the next number.**

**3. Two error families dominate the A-LOW misses, and both are cheap to fix.**
 - *Out-of-bundle international instruments read as the home treaty* (17 items): ECHR (incl. its
   formal title *"Convention for the Protection of Human Rights and Fundamental Freedoms"*, which
   the heuristic does not recognise as ECHR), ACHR / Protocol of San Salvador, the 1951 Refugee
   Convention, VCLT art 31, Geneva Convention III, the Hague Abduction Convention, ILO C169.
   This is exactly the Tier-1 list in `missing-instruments.md`: **adding ECHR, ACHR, UDHR, the
   Refugee Convention and the Geneva Conventions to the bundle would convert most of these
   `plain-text` verdicts into correct links with zero frontend change.**
 - *"the Optional Protocol (article N)" read as ICCPR* (12 items, the single largest relink
   target). Article 1 (Committee competence), article 2 and article 5 (2)(a)/(b) (admissibility)
   of ICCPR-OP1 are the standard admissibility citations and recur verbatim across Belarus and
   Netherlands communications. ICCPR-OP1 is already in the bundle, so this is a pure
   anaphora-resolution fix: inside a CCPR document, *"the Optional Protocol"* is never the Covenant.

**4. One genuine false positive worth keeping.** `cerd-c-109-d-63-2018-0009` arts 1/2/5/6 were
flagged as CEDAW because the source text truncates CERD's own name to *"the International
Convention on the Elimination of All Forms of Discrimination"* — a prefix of CEDAW's full title.
The case is racial discrimination, and arts 1/2/5/6 map exactly onto CERD (definition, State
obligations, equality before the law, effective remedies). Verdict: `home-correct` (CERD).
Prefix matching against `name_full` needs a word-boundary/completeness guard.

**5. OCR damage manufactures article numbers.** `ccpr-c-38-d-275-1988-0019` reads
*"(articles 6, 7, 9`5 1 5 2 5 7 1330 3516 102 43 94.358917` and 10)"* — the audit picked up
**"article 95"**, which does not exist (ICCPR has 53 articles). A sanity check "article number ≤
the home treaty's article count" would catch this class outright.

## C1 — citedArticles queue misalignment (all 9 verified)

8 of 9 are `home-correct`: every occurrence of the affected article number in the paragraph belongs
to the home treaty, but the `citedArticles` queue has fewer entries than the text has occurrences.
**The uncovered occurrence is a compound reference in every single case** —
`"arts. 2 (1) (d) and 4"`, `"arts. 7 and 69"`, `"arts. 4 and 45 of the Convention"`,
`"arts. 29 and 40"`, `"arts. 18.1 and 27.2"`, `"arts. 40, 37 and 39"`. The companion articles in
those compounds (4, 7, 45, 28, 32, 34, 40, 42, 44, 27.2, 37, 39, 2(1)) are missing from
`citedArticles` altogether, so this is the same defect as the C2 `list-nonfirst` blind spot.

The ninth, `e-1991-23-0005` art 2, is a **`relink` to ICCPR**: the CESCR general comment cites
*"arts. 2 (paras. 1 and 3), 3 and 26) of that Covenant"* and *"(art. 2 (3) (a))"*, both referring to
the ICCPR, not the home ICESCR. That paragraph also contains a genuine same-number collision —
**ICCPR art 3 and ICESCR art 3 in the same sentence** — which no per-paragraph default treaty can
resolve.

## C2 — how the 148 references are actually written

| written form | count | what it means |
|---|--:|---|
| `lead-in-colon` | 46 | paragraph is a colon lead-in ("…the Committee recommends that States parties:"); the enumerated sub-items carrying the reference are **separate paragraph records**, but `citedArticles` was computed over the whole list |
| `list-nonfirst` | 38 | number is a later item in a multi-article list — `"articles 2 (c), 3, 5 (a) and 15"`, `"articles 10 (h) and 12"`, `"articles 1, 2, 5 (a) and 12"` — only the first number after the article word is linked |
| `truncated-text` | 24 | the stored paragraph text is cut off mid-sentence; the reference sits in the missing tail (e.g. `e-c-12-2000-4-0002` ends "…the most comprehensive article on the right to") |
| `head-of-ref-overcount` | 22 | reference is written normally and *is* linked; `citedArticles` simply holds more entries for the article than the text has occurrences (paragraph-level over-tagging, mostly `crc-c-gc-12`/`crc-c-gc-17`) |
| `implicit-anaphora` | 14 | no literal number at all; the tag was inferred from a named right ("the best interests of the child" → CRC art 3, "the following articles in the Convention" → arts 2/6/12) |
| `repeat-bare-number` | 3 | the number repeats without a fresh article word: `"article 16 (1)(a) and 16 (1)(b)"`, `"articles 2 (e), 2 (f) and 5"` |
| `paragraph-number-collision` | 1 | the only literal occurrence is the leading paragraph number (`"29. Parental and public responsibilities…"` tagged as CRC art 29) |
| `range` | 0 | no C2 item turned out to be a numeric range or roman numeral |

**Headline for C2: it is mostly not a regex blind spot.** 70 of 148 (47 %) are corpus-segmentation
artefacts — list lead-ins split from their items (46) plus truncated paragraph text (24) — where
`citedArticles` was computed over a larger text unit than the one the reader renders. Fixing the
renderer will not help those; re-joining lead-ins with their sub-items (or attaching the tags to the
sub-item records) will. The genuinely fixable renderer blind spot is **`list-nonfirst` (38) +
`repeat-bare-number` (3) = 41 items**: continue scanning after the first number in an
`articles X (a), Y and N` construction, and treat a bare `N (x)` after `and`/`,` inside an active
article reference as a further reference. That single change also fixes 8 of the 9 C1 items.

Expected forms that did **not** appear anywhere in C2: numeric ranges, roman numerals, footnote-only
references. Ranges do occur in the corpus (`"arts. 19–20 and 24"`, `"arts. 13–14"`, `"articles 6 to
27"`) but always with the endpoints tagged, so they never surfaced as a C2 mismatch.
