# Data quality audit — General Comments

**Date:** 2026-04-29
**Scope:** `docs/documents.json` + `docs/corpus.json` filtered to `type=gc`
**Volume:** 186 documents · 7 103 paragraphs
**Tooling:** `data_audit_gc.py` (20 audit sections, ~7 s to run)

## TL;DR

The dataset is in **strong shape overall** — referential integrity holds end-
to-end (no orphan paragraphs, no missing docs, paragraph counts and word
counts and label counts all match between `documents.json` and `corpus.json`,
no idx gaps). Languages are uniformly all 6 UN official languages.

The findings cluster into seven categories:

| # | Category | Severity | Count | Effort to fix |
|---|---|---|---|---|
| **A** | Joint-document `alternativeSignatures` missing | 🔴 P0 | 4 docs | 5 min hand-edit |
| **B** | Stray `\r` / multi-space whitespace | 🟡 P1 | **2 152 ¶** (30 %) | 1 line in build_corpus.py |
| **C** | Trailing footnote markers (`.NN$`) | 🟡 P1 | 111 ¶ | 1 regex in build_corpus.py |
| **D** | Long paragraphs (>5 000 chars) | 🟢 P2 | 18 ¶ | source-PDF review |
| **E** | Signature format / collisions | 🟢 P2-P3 | 81 cases | mostly cosmetic |
| **F** | Missing `articles[]` references | 🟡 P1 | **62 docs (33 %)** | metadata-fill task |
| **G** | Per-paragraph data inconsistencies | 🟡 P1-P2 | a handful | small one-offs |

The audit also surfaces **distributional observations** worth knowing
(committee paragraph density, label coverage 74 %, status counts) that
aren't bugs but are useful baselines.

---

## A · Joint-document metadata gap (P0 · 4 of 5 joint docs)

The 5 joint General Comments / Recommendations have compound signatures
like `CMW/C/GC/7–CERD/C/GC/38`. The `jointWith` field correctly carries
the constituent dictionaries:

```json
"jointWith": [
  {"committee": "CMW",  "signature": "CMW/C/GC/7"},
  {"committee": "CERD", "signature": "CERD/C/GC/38"}
]
```

But **only one of five** has `alternativeSignatures` populated:

| docId | Has `alternativeSignatures`? |
|---|:-:|
| `cedaw-c-gc-31-rev-1crc-c-gc-18-rev-1` | ✅ yes |
| `cmw-c-gc-7cerd-c-gc-38` | ❌ |
| `cmw-c-gc-8cerd-c-gc-39` | ❌ |
| `crc-c-gc-22-cmw-c-gc-3` | ❌ |
| `crc-c-gc-23-cmw-c-gc-4` | ❌ |

**Why this matters.** When a researcher pastes `CMW/C/GC/7` into the search
or the rail filter, the document doesn't appear by signature — only by
its compound signature `CMW/C/GC/7–CERD/C/GC/38`. This is exactly the
case where someone reading a citation in a third-party paper hits a
"document not found" wall.

**Fix.** Add `alternativeSignatures: [...]` to the 4 missing docs by
flattening their `jointWith` entries:

```diff
 "docId": "cmw-c-gc-7cerd-c-gc-38",
 "signature": "CMW/C/GC/7–CERD/C/GC/38",
 "jointWith": [{"committee":"CMW","signature":"CMW/C/GC/7"},
               {"committee":"CERD","signature":"CERD/C/GC/38"}],
+"alternativeSignatures": ["CMW/C/GC/7", "CERD/C/GC/38"],
```

Effort: ~5 min hand-edit of `documents.json`. Even better: derive it
in `build_corpus.py` so future joint docs get it automatically.

---

## B · PDF-extraction whitespace artefacts (P1 · 2 152 ¶)

Stray control whitespace appears in **2 152 of 7 103 paragraphs** (30 %):

| Character | Count | Where |
|---|---:|---|
| `\r` (carriage return) | 2 152 | one-third of all paragraphs |
| `\x0b` (vertical tab) | 1 | `hri-gen-1-rev-9-vol-i-p-180-0002` |
| `\xad` (soft hyphen) | 1 | `e-c-12-gc-21-0073` |

The `\r` is preserving Windows line endings from the original PDF
extraction. Where it precedes `(a)`, `(b)` markers, the extractor saw
a soft break inside what's logically one paragraph:

```
cedaw-c-gc-38-0011: ...'Transnational Organized Crime: \r\n(a)"Trafficking in persons" sh'
cedaw-2009-wp-1-r-0004: ...'workers who migrate independently; \r\n(b) Women migrant workers'
cedaw-2009-wp-1-r-0023: ...'origin and destination include: \r\n(a) Formulating a comprehensive'
```

**Visible effect.** In KWIC snippets these render as a one-character
glitch where the line wraps unnaturally. Doesn't break search (FlexSearch
tokenises on whitespace anyway), but it shows in the dossier blockquote
and worsens readability.

**Fix.** One-liner in `build_corpus.py`:

```python
# Normalise whitespace: \r\n \r \v \xad → single space; collapse runs.
text = re.sub(r'[\r\v­]', ' ', text)
text = re.sub(r'\s+', ' ', text).strip()
```

`\xad` (soft hyphen) merits a stripping rule of its own — it should
disappear, not become a space, since it's an in-word hyphenation hint
that doesn't belong in plain text. So `text.replace('\xad', '')` first,
then the whitespace normalise.

---

## C · Trailing footnote markers (P1 · 111 ¶)

111 paragraphs end with a pattern like `.4`, `.27`, `.56`. Examples:

```
cedaw-c-gc-32-0007  → ...'y private persons and non-State actors.4'
cedaw-c-gc-32-0010  → ...'on the Reduction of Statelessness.6'
cedaw-c-gc-32-0029  → ...'making such complaints.27'
cmw-c-gc-6-0019     → ...'migrants and members of their families.6'
```

These were superscript footnote references in the source PDF (¹²³⁴ etc.)
that the extractor flattened into regular ASCII digits attached to the
sentence-final period. Two consequences:

1. **Cosmetic** — reads weirdly in citations the user copies (`actors.4`).
2. **Search-glitch** — searching `actors.` doesn't surface these because
   FlexSearch tokenises numbers as part of a word.

**Fix options.**

- **Strip + record.** Remove the trailing `.NN` from `text`; emit a
  parallel `footnoteRefs: [4, 27, 56]` field. Roughly:

  ```python
  m = re.search(r'\.(\d{1,3})\s*$', text)
  if m:
      ref = int(m.group(1))
      text = text[:m.start()] + '.'
      footnotes.setdefault(para_id, []).append(ref)
  ```

- **Keep in-line, normalise spacing.** `actors.4` → `actors. ⁴` (using
  the unicode superscript). Easier on the eye, preserves the reference.

I'd ship option 1 — it's the cleanest separation of concerns and
unblocks any future "show all footnote references" view.

The same regex could also catch mid-paragraph cases (footnote numbers
attached to internal sentences, not just the final), but those are
much harder to detect reliably and were not measured in this audit.

---

## D · Paragraphs with embedded subsections (P2 · 18 ¶)

18 paragraphs are >5 000 characters. Examples:

```
cat-c-gc-4-0029       6 782 chars   2× '(a)' + 1× '(b)' markers — single ¶ in source
crc-c-gc-7-rev-1-0036 9 319 chars
crc-c-gc-17-0058      9 062 chars
cedaw-2009-wp-1-r-0026 7 831 chars
crc-c-gc-13-0072      7 670 chars
```

Looking at `cat-c-gc-4-0029`:

```
HEAD: "In this connection, the Committee wishes to draw the attention of
       the States parties to some non-exhaustive examples of human rights
       situations that may constitute an indication of risk of torture…"
TAIL: "…the person's recruitment as a combatant participating directly
       or indirectly in hostilities or for providing sexual services."
```

The body has 2 `(a)` markers, 1 `(b)` — meaning embedded list items.
Two interpretations:

- **Honour the source PDF.** If the source treats this as one paragraph,
  our extraction is correct.
- **Split for usability.** A 6 782-char paragraph is a single search hit
  but no one reads it as a single thought; splitting on the lettered
  list would give 5-6 cleaner search results.

**Recommendation.** Manual review against the source PDF for each of
the 18. Where the source has them on separate lines (most likely), split
in `build_corpus.py` on a `(a)`-style marker pattern. Don't blindly
auto-split — some lists are mid-sentence and shouldn't be broken.

---

## E · Signature format / collision findings (P2-P3 · cosmetic)

### E1 · 68 signatures don't match the canonical regex
These are mostly older HRI/GEN/1/Rev.9 page-references that are valid UN
documentation but don't fit the modern `BODY/C/GC/N` format. Examples:

```
HRI/GEN/1/Rev.9 (Vol. I) p. 173
HRI/GEN/1/Rev.9 (Vol. I), p. 200    ← inconsistent comma
CCPR/C/21/Rev.1/Add. 4              ← space before number
CCPR/C/21/Rev.1/Add.5                ← no space
```

**Fix.** Two paths:
- Loosen the audit regex to accept these (cleanest). Update
  `data_audit_gc.py:_SIGNATURE_OK` to recognise the HRI/GEN/1 page-
  reference family.
- Normalise `signature` strings (collapse `Add. 4` ↔ `Add.4` to one form).
  Also normalise the dash variant: `, p. 200` vs ` p. 198`.

### E2 · 13 shared-signature clusters
Older CEDAW (A/42/38–A/47/38) and CERD (A/48/18–A/87/18) annual reports
contain multiple recommendations. Each recommendation has its own docId
but shares the parent annual-report symbol:

```
A/44/38 → 5 different CEDAW recommendations (GR9–GR13)
A/87/18 → 3 different CERD recommendations (GR1–GR3)
```

This is **correct semantically** (the parent report was published once),
but `signature` is now ambiguous for search-by-symbol.

**Fix.** Add a `paragraphRange` or `subsection` field — e.g.
`A/44/38 §VI` for CEDAW GR12. Or augment `alternativeSignatures` to
include the body-specific symbol if one exists (e.g.,
`CEDAW/A/44/38/GR12`).

---

## F · Missing `articles[]` references (P1 · 62 docs / 33 %)

A third of GC documents have no `articles[]` field listing the treaty
articles they interpret. The dossier reader's "Articles cited" widget
silently falls through to empty for these — which on the docs reader
reads as if the GC interprets nothing.

Distribution by committee:

| Committee | Docs missing `articles[]` |
|---|---:|
| CEDAW | 20 |
| CRC | 14 |
| CERD | 11 |
| CESCR | 7 |
| CMW | 6 |
| CRPD | 3 |
| CED | 1 |
| **Total** | **62 / 186** |

Examples:

```
cedaw-c-gc-36   GR36: the right of girls and women to education       → CEDAW Art. 10
cedaw-c-gc-39   GR39: Indigenous women and girls                       → CEDAW Art. 14
crpd-c-gc-3     GC3: women and girls with disabilities                  → CRPD Arts. 6, 16, 25
crpd-c-gc-4     GC4: the right to inclusive education                   → CRPD Art. 24
cmw-c-gc-1      GC1: migrant domestic workers                          → CMW multiple
ced-c-gc-1      GC1: enforced disappearance + migration                 → CED Art. 1
e-c-12-2002-11  GC15: The Right to water                                → ICESCR Arts. 11+12
```

**Effect.** "Articles cited" badge in the dossier and the docs reader
header is empty for ~33 % of GCs. Users browsing for a specific article
(e.g. "show me everything that interprets CRPD Article 24") cannot find
these GCs through the article-cite path — they have to know the GC by
number first.

**Fix.** This is a **metadata-fill task**, not a code bug. Two paths:

1. **Manual.** A subject-matter pass (≈ 30 sec / doc) lists the obvious
   primary articles. ~30 minutes of work for all 62.
2. **Auto-extract.** Most GCs cite the relevant articles in their body
   text. A regex pass over the first 5 paragraphs (the "introduction"
   block) for "article(s) NN" mentions, then keep the top 3-4 most-
   cited as the `articles[]` list. Risk: false positives (mentions of
   other treaties' articles, scope statements). Worth piloting.

I'd ship the manual pass — it's high-confidence and quick.

---

## G · Per-paragraph data inconsistencies (P1-P2 · small one-offs)

A few specific paragraphs/docs that need targeted fixes.

### G1 · Three paragraphs with `n=null` and number-glued-to-text

```
e-c-12-gc-21-0015 → "15.There are, among others, three interrelated…"
e-c-12-gc-23-0049 → "49. Human rights defenders should be able to…"
e-c-12-gc-23-0065 → "65. States parties have a core obligation to…"
```

The paragraph number was eaten into the `text` field instead of being
parsed into `n`. **Fix.** In `build_corpus.py`, before assigning text:
```python
m = re.match(r'^(\d+)\s*\.\s+(.*)$', text, re.DOTALL)
if m and n is None:
    n = int(m.group(1))
    text = m.group(2)
```

### G2 · `cat-c-gc-3` nameShort says "GC2" instead of "GC3"

```
docId:     cat-c-gc-3
signature: CAT/C/GC/3
name:      "General Comment No. 3 (2012): Implementation of article 14…"
nameShort: "GC2: Implementation of Art. 14 by States parties"   ← bug
```

The `nameShort` says GC2 but the doc is GC3. Likely a typo in the
metadata-prep script. Fix: `s/^GC2:/GC3:/` on this single doc.

### G3 · Older CAT GC1 nameShort uses `GC1` while name uses `No. 01`

```
a-53-44 name="General Comment No. 01: Implementation of article 3…"
        nameShort="GC1: Implementation of Art. 3  in the context…"
```

Cosmetic — zero-padded vs not. Either normalise both to `No. 1` /
`GC1`, or accept the variation. Also note: the `nameShort` has a
**double space** between "Art. 3" and "in" (`Art. 3  in the context`).
Same regex pass as B fixes this.

### G4 · CERD GC37 unbalanced parens — false positive

7 of the 17 unbalanced-bracket findings cluster in CERD/C/GC/37, where
the source text uses unmatched `i)`, `ii)`, `iii)` enumeration markers
without a leading `(`. These are **honest extraction** of how the source
PDF formats lists — not a bug. The audit's bracket-balance heuristic
shouldn't be tightened against this.

### G5 · Paragraph numbering of older docs

`e-c-12-2002-11` (CESCR GC15 on the Right to Water) etc. use older
CESCR docId conventions (`E/C.12/2002/11`). The current docs have
`docId="e-c-12-2002-11"` and `signature="E/C.12/2002/11"` — both
correct. Just flagging that the regex in §E doesn't recognise this
shape; suggest extending the canonical-signature regex to allow it.

---

## Summary of recommended changes

In priority order (with effort estimates):

| # | Change | File | Effort |
|---|---|---|---|
| **1** | **Add `alternativeSignatures` to 4 joint docs (A)** | `documents.json` | **5 min** |
| **2** | **Fix `cat-c-gc-3` nameShort GC2 → GC3 (G2)** | `documents.json` | **30 sec** |
| 3 | Strip `\r` `\xad` `\v` + collapse multi-space (B) | `build_corpus.py` | 10 min + rebuild |
| 4 | Salvage the 3 leading-number paragraphs (G1) | `build_corpus.py` | 10 min + rebuild |
| 5 | Extract trailing footnote markers into `footnoteRefs` (C) | `build_corpus.py` | 30 min + rebuild |
| 6 | Backfill `articles[]` for the 62 missing docs (F) | `documents.json` | 30 min manual |
| 7 | Manual split review for 18 long paragraphs (D) | source-PDF + `build_corpus.py` | 2-3 h |
| 8 | Normalise older `signature` strings (E1) | `build_corpus.py` | 30 min |
| 9 | Loosen audit regex to recognise HRI/GEN/1 + E/C.12 patterns (E1, G5) | `data_audit_gc.py` | 5 min |
| 10 | Document E2 collisions or add `subsection` field | `documents.json` schema | discuss |

Together these would land **0 critical / 0 warning / informational only**
on the next audit run.

The first two (A + G2) are five-minute hand-edits that fix real
researcher-impacting bugs: search-by-signature breaking on joint docs +
a wrong title number. They're the obvious "do this today" items. Items
3–5 are build-pipeline fixes that need a corpus rebuild but no
intervention. Item 6 is the largest by effort but is **the highest-
impact metadata improvement** — it lights up the "Articles cited" badge
on a third of the GC reader pages.

---

## Distributional snapshots (informational)

### Committee distribution
```
committee     #docs   #paras  avg ¶/doc
CAT               4      133       33.2
CCPR             37      697       18.8
CED               1       56       56.0
CEDAW            40    1 260       31.5
CERD             37      510       13.8
CESCR            27    1 225       45.4
CMW               6      543       90.5    ← outlier (CMW GCs are long)
CRC              26    2 092       80.5    ← longest body
CRPD              8      587       73.4
```

CMW + CRC + CRPD GCs are systematically longer than the rest. This is
expected — those bodies have produced fewer but more comprehensive
General Comments. Worth knowing for the search-result clustering UX:
all-scope queries naturally over-represent CRC.

### Paragraph length (chars)
```
min     26
median  633
mean    752
p95   1 608
p99   2 862
max   9 319    ← see §D
```

### Label coverage
- **74.3 %** of paragraphs carry ≥ 1 label (5 275 / 7 103)
- 19 unique labels, top: Children (2 548), Women/girls (1 792), PWD (822)
- All 19 labels are used at least 57 times — **no spelling drift /
  singletons** (the audit was watching for those, found none)

### Status
```
final         182
superseded      2    (CAT GC1 → GC4; CRC GC7 → GC7-Rev.1)
revised         2    (CRPD GC1 revised, CEDAW/CRC GC18 revised)
```

### Languages
All 186 docs publish in the same set of 6 official UN languages
(`ar/en/es/fr/ru/zh`). No coverage gaps.

---

## Reproducing the audit

```bash
cd /Users/lszoszk/Desktop/GC_Database
python3 data_audit_gc.py
```

Adapt for JUR / SP by replacing the type filter in the `load()` helper.
Same script structure, same output format, easy to compare across
collections.
