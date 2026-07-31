# Measurement tools for article-reference resolution

Rebuilt from scratch twice during the 2026-07 work because they lived in a
session scratchpad that gets wiped. They live here now.

## harness.mjs — regression suite for `annotateTreatyText`

Every case is one mocked `/api/search` hit; the rendered result list is the
assertion surface, so it exercises the same path a real API result takes
(the API path carries no `citedArticles`, which is precisely the path the
heuristics matter on).

```bash
# serve docs/ on :8788 first, then:
BUNDLE=/tmp/treaties-bundle.json node artref-audit/tools/harness.mjs
```

Fetch a current bundle with:
`curl -sk "https://150.254.115.204/ask-api/api/treaties?v=x" -o /tmp/treaties-bundle.json`

Two traps this harness has fallen into, both now guarded:

* **Chunking.** The result list appends 20 rows per page and the reader has
  no loader function to call, so a suite longer than one page silently stops
  asserting on its tail. Cases run in chunks of 15.
* **Row matching.** Matching a row by a text prefix broke when two cases
  shared their first 40 characters ("…Optional Protocol on the sale…" vs
  "…on a communications procedure") — it read the wrong row and blamed the
  resolver. Rows are matched by delimited case id, whitespace-normalised.

## The audit data next to it

`verdicts.jsonl` (328 clean-context judgments), `findings.json`,
`c2-forms.jsonl`, `VERDICT-SUMMARY.md`, `instrument-census.json` and
`missing-instruments.md`. Every resolution rule from v19.67 onward was
scored against these before shipping; the census is what sized the bundle
work that took it from 18 instruments to 38.

Note the ground truth has aged in one direction: verdicts that read
"plain-text — instrument not in bundle" were authored when the bundle held
18 instruments. Several of those instruments have since been added, so the
correct answer today is a link. Score accordingly.
