# Ask tab — pipeline methodology

**Status: BETA** (experimental, deployed 2026-05-09).

## Scope and design intent

The Ask tab is an extractive RAG layer over the General Comments
corpus. It surfaces verbatim paragraphs in response to natural-language
questions. **No paraphrase, no synthesised answers, no LLM-generated
content displayed to the user.** The LLM operates only on:

1. The query side — rewriting the user's question into doctrinal
   language so dense retrieval can match (HyDE).
2. As a final-stage ranker — ordering the top-50 retrieved paragraphs
   by direct relevance to the original question.

This is fundamentally different from chatbot-style RAG. There is no
generation of legal claims; every visible sentence comes from a
specific Committee, identifiable by signature + paragraph number.

## Pipeline (as deployed)

```
Question
   │
   ├── Filter candidates (committee, year, superseded)
   │
   ├── Gemini Flash-Lite: HyDE + structured JSON output
   │      ↓ returns { paragraph, terms[3-5], expansions[3] }
   │      The "paragraph" is a 100-150 word hypothetical UN treaty body
   │      paragraph in doctrinal language; it is the dense-retrieval probe.
   │      "terms" surface in the UI as MATCHED ON chips.
   │      "expansions" become "Try a different angle" suggestions.
   │
   ├── Parallel retrieval:
   │     (a) Dense — Voyage law-2 embed of HyDE paragraph,
   │         cosine top-50 within filtered candidate set.
   │     (b) BM25 — SQLite FTS5 over paragraph text. Token min length
   │         4 chars (drops "non" / "the" noise). OR-joined query.
   │         Restricted to GC paragraph IDs (corpus has 132K paragraphs
   │         total — non-GC documents excluded from this branch).
   │
   ├── Reciprocal Rank Fusion (k=60, Cormack et al. 2009)
   │      score(d) = Σᵢ 1 / (k + rankᵢ(d))
   │      Output: top-50 fused candidates.
   │
   ├── Voyage rerank-2 cross-encoder against the ORIGINAL question
   │      (not the HyDE rewrite — preserves user intent in the rerank
   │      step, where the model can see whole-paragraph semantics).
   │      Scores 0-100 → "good"/"medium"/"weak" bands.
   │
   ├── Gemini Flash-Lite LLM-judge over top-10:
   │      • Receives candidate texts ([A] [B] [C] ...) + treaty article
   │        context (relevant articles from the source committee's
   │        treaty + protocols, max 5 articles per treaty).
   │      • Returns letter ranking by direct answer-fit.
   │      • Penalises: tangential matches, preambular language,
   │        candidates that mis-cite or contradict the treaty text.
   │      • If judge fails (rate limit, network), gracefully degrade
   │        to voyage rerank order.
   │
   └── Final order = judged_top10 + voyage_top11_to_50
```

## Treaty corpus for grounding

`api/treaties/*.json` — 18 instruments, 609 KB raw / ~126 KB gzipped:

| Abbr | Articles | Treaty body |
|---|---|---|
| ICCPR | 53 | CCPR |
| ICESCR | 31 | CESCR |
| CRC | 54 | CRC |
| CEDAW | 29 | CEDAW |
| CRPD | 50 | CRPD |
| CAT | 33 | CAT |
| CERD | 25 | CERD |
| CMW | 91 | CMW |
| CED | 45 | CED |
| ICCPR-OP1 | 16 | CCPR (individual complaints) |
| ICCPR-OP2 | 13 | CCPR (death penalty abolition) |
| ICESCR-OP | 23 | CESCR |
| CRC-OPSC | 18 | CRC (sale of children) |
| CRC-OPAC | 14 | CRC (armed conflict) |
| CRC-OPIC | 24 | CRC (communications) |
| CEDAW-OP | 21 | CEDAW |
| CRPD-OP | 18 | CRPD |
| OPCAT | 37 | CAT (preventive system) |

Source: OHCHR canonical HTML pages (manually saved; OHCHR is behind
Cloudflare and rejects automated fetches). Parsed via
`_docs_internal/treaties/build_treaties.py` — auditable, reproducible.

## Benchmark (commentary-grounded, 30 questions)

Eval set: `gc-rag-local-share/eval/questions_v2_30.jsonl`.
Anchored in pinpoint citations from Saul (Saul, Kinley & Mowbray on
ICESCR) and Joseph & Castan on ICCPR. 16 of 30 questions carry
paragraph-level `expectedParaIds`; all 30 have `expectedDocIds`.
Distribution: 10 doctrinal · 10 practical · 5 exclusion · 5 cross-cutting.

### Headline results (final pipeline, 2026-05-09)

| Metric | Value |
|---|---|
| **docHit@5** | **100.0%** (30/30) |
| **docHit@10** | **100.0%** (30/30) |
| **paraHit@5** | **81.2%** (13/16) |
| **paraHit@10** | **87.5%** (14/16) |
| Latency, median | 3.9 s |
| Latency, p95 | 6.1 s |

Per category — all 100% docHit@5:

| Category | n | docHit@5 |
|---|---|---|
| doctrinal | 10 | 100% |
| practical | 10 | 100% |
| exclusion | 5 | 100% |
| cross-cutting | 5 | 100% |

### Reference numbers from local prototype (pre-deployment)

For comparison, the `gc-rag-local-share` prototype (premium tier:
voyage hybrid + voyage rerank-2, no LLM-judge): paraHit@5 = 75.0%,
docHit@5 = 97.0%. Deployment exceeds both baselines:

| Metric | Local prototype | Deployed Ask | Δ |
|---|---|---|---|
| docHit@5 | 97.0% | 100.0% | **+3.0pp** |
| paraHit@5 | 75.0% | 81.2% | **+6.2pp** |

### Iteration history

| Configuration | docHit@5 | paraHit@5 | Notes |
|---|---|---|---|
| Tier 3 only (hybrid + rerank) | 100.0% | 68.8% | bottleneck: voyage rerank picks adjacent paragraph over canonical |
| + LLM-judge over top-10 | 100.0% | **81.2%** | +12.4pp paraHit@5 — the highest-impact addition |
| + multi-query expansion (Tier 2) | 100.0% | 81.2% | no benefit; added latency; reverted |
| + treaty-text augmentation (Phase 1) | 100.0% | 81.2% | metric unchanged; foundation for Phase 1.5 frontend |
| + token-min 4 BM25 tweak | 100.0% | 81.2% | metric unchanged; cleaner BM25 (drops "non"/"the" noise) |

The 3 stubborn paraHit@5 misses (B013, B014, B016) all locate the
correct GC document but rank an adjacent paragraph (off-by-1-2) over
the canonical one identified by the commentary author. They count
against the metric but in research practice the retrieved paragraphs
are typically substantively equivalent — a measurement-noise artefact
of single-canonical ground-truth, not a real failure.

### Faithfulness eval (answer-quality, added 2026-05-11)

Retrieval metrics (paraHit/docHit) measure *whether* the canonical
expected paragraph was retrieved. They do *not* measure *whether the
top-ranked paragraph actually answers the question.* For that we run
a separate faithfulness eval — Gemini Flash-Lite as judge over each
top-K paragraph the system returned:

> *"Does this paragraph DIRECTLY answer the question? yes / partial / no"*
> — where *directly* means the specific rule/test/elements the
> question asks about, not adjacent or background content.

Each verdict scored: yes = 1.0, partial = 0.5, no = 0.0.

**Headline (3-run mean ± stddev, 270 total judgments):**

| Metric | Mean | StdDev |
|---|---|---|
| **answerScore@1** | **0.888** | ± 0.017 |
| **answerScore@3** | 0.804 | ± 0.037 |

Variance across runs is low (CV ~2% for @1, ~4% for @3) — single-run
numbers are representative.

**Rank-1 verdict distribution (best of the 3 runs, n=30):**

| Verdict | Count | % |
|---|---|---|
| yes (directly answers) | 25 | 83% |
| partial (related but incomplete) | 4 | 13% |
| no (off-topic / tangential) | 1 | 3% |

**Why this matters more than paraHit@5:** the gap between
paraHit@5 = 81.2% and answerScore@1 = 88.8% (+7.6pp) is the system
returning a *different* paragraph than the commentary author picked
but one that nonetheless answers the question — a legitimate
alternative, not a failure. paraHit penalises that case; the
faithfulness eval rewards it. Both numbers point at retrieval
saturation: the residual ~12% of non-yes verdicts are mostly
substantive limits of the pipeline, not measurement noise.

### Stability across 3 runs (judge stochasticity)

| Bucket | Count | Question IDs |
|---|---|---|
| Always "yes" (stable, fully answered) | 23/30 | (the rest) |
| Always "partial" (consistent near-miss) | 4/30 | B008, B015, B021, B030 |
| Always "no" (consistent miss) | 1/30 | B006 |
| Flipping (judge varies) | 2/30 | B011, B020 |

**Always non-yes — these are the actual iteration targets:**

- **B006 — "What principal branches must an adequate social
  security system cover?"** System surfaces a paragraph stating
  *"the system shall cover nine principal branches"* without the
  enumeration; the canonical paragraph lists them. Meta-statement
  retrieved instead of the concrete list.
- **B008 — Art 2(1) ICESCR progressive realisation** — top-1 is a
  related but incomplete framing of progressive realisation.
- **B015 — HRC torture vs CIDT distinction** — surfaces general
  Art 7 ICCPR doctrine, not the specific HRC test for distinguishing
  torture from cruel/inhuman/degrading treatment.
- **B021 — right to health for women / adolescents** — surfaces
  general right-to-health language, not the women/adolescents-
  specific paragraph.
- **B030 — gender-based violence obligations** — broad obligations
  language vs the specific GBV-prevention paragraph.

**Iteration potential:** if we tune the LLM-judge prompt (or HyDE
prompt) to penalise meta-statements vs concrete-list paragraphs, we
might lift 2-3 of these from "partial" to "yes" — pushing
answerScore@1 toward ~0.95.

## Frontend annotations (Phase 1.5)

The Ask tab post-processes verbatim paragraph text to:

1. **Treaty-term tagging.** "the Covenant" / "the Convention" gets a
   small superscript abbr (`ICCPR`, `CRC`, etc.) based on the source
   committee. Verbatim text is unchanged — only annotated.
2. **Article references.** "Article 4", "article 4(2)", "articles 18(2)
   and 17" — wrapped in clickable buttons. Click → popover with the
   actual treaty article text from the cached treaty bundle.
3. **Multi-article lists.** Recognised: `articles N(P), M, K(P) and L`.
   Each number becomes a separate button; separators (commas, "and")
   stay as plain text. Descriptive parentheticals
   (`article 6 (right to life)`) are correctly excluded from the
   button — only numeric/paragraph qualifiers are absorbed.
4. **Protocol disambiguation palliative.** When `article N` is followed
   by `of (that|the) (Optional) Protocol`, the reference is left as
   plain text rather than wrong-linked to the source committee's main
   treaty. Example: GC29 ¶ saying "as prescribed in article 6 of that
   Protocol" — without disambiguation, "article 6" would link to ICCPR
   art 6 (right to life) instead of ICCPR-OP2 art 6 (Protocol entry).

## Known limitations

- **Cross-treaty references (partial).** Section A above's palliative
  catches the most common pattern. A GC paragraph that mentions another
  treaty by full name and then refers to "article 4(2)" with no `of
  that Protocol` cue will still be wrong-linked. Full disambiguation
  requires pre-tagged `cited_articles` metadata in `paragraphs.json`
  — see `cross_treaty_refs_followup.md` in the user's memory.

- **Off-by-one paragraph misses.** ~3 of 16 paragraph-graded benchmark
  questions return a paragraph adjacent to the canonical one. Source-
  document accuracy is 100%.

- **No author/translator metadata for treaty text.** OHCHR HTML doesn't
  encode this; for legal-citation correctness only the article numbers
  and paragraph numbers matter.

- **Scope.** Only General Comments and General Recommendations are in
  the Ask corpus. Concluding Observations, Views/decisions on individual
  communications, and Special Procedures reports are deliberately
  excluded — they are searchable separately under the Documents tab.

## Cost & throughput

Per query:
- Gemini Flash-Lite (HyDE): ~250 input + ~150 output tokens
- Gemini Flash-Lite (judge): ~3000 input (10 candidates × 1500 chars
  + treaty articles) + ~50 output tokens
- Voyage law-2 embed: 1 embedding (~200 tokens)
- Voyage rerank-2: 50 candidates against query

Approximate cost: < $0.001 per query at current Gemini/Voyage rates.

Per-IP rate limit (nginx): 15 requests/minute, burst 8. Caps automated
traffic without restricting individual researchers in normal usage.

## Architectural choices not made

- **No chatbot.** No multi-turn conversation. Each query is independent.
  This is deliberate — multi-turn easily drifts away from extractive
  grounding into synthesised answers.
- **No "summary" generation.** The Top Match section presents the
  first-ranked paragraph verbatim, not a synthesis.
- **No automatic re-querying.** The system does not silently retry a
  question with paraphrased terms. The user sees what the LLM judged
  most relevant for the exact question they asked.

## File map

| File | Role |
|---|---|
| `api/main.py` | FastAPI app, `/api/ask`, `/api/treaties`, `/api/health`, lifespan loaders |
| `api/hyde.py` | `GeminiKeyPool` class: `rewrite()` for HyDE, `judge()` for second-stage rerank |
| `api/hybrid.py` | BM25 search via SQLite FTS5, RRF fusion, FTS5 query helpers |
| `api/retrieval.py` | Voyage embed, rerank, cosine search, score banding |
| `api/treaties/*.json` | 18 treaty/protocol JSONs (deployed bundle) |
| `_docs_internal/treaties/build_treaties.py` | Reproducible build of treaty JSONs from OHCHR HTML |
| `_docs_internal/treaties/*.json` | Local copy of the deployed bundle (audit reference) |
| `docs/assets/app.js` | Ask tab UI: `runAsk()`, `_askRenderSourceCards()`, `annotateTreatyText()`, treaty popover |
| `docs/assets/app.css` | All styling, including BETA badges and treaty annotations |

## Ops checklist before declaring stable

- [ ] Run benchmark 3× and verify variance ≤ ±5pp on paraHit@5 (LLM-judge
      is mildly stochastic — a single run isn't authoritative)
- [ ] Spot-check 10 random queries from production logs for retrieval
      quality + UI correctness (annotations, popover content)
- [ ] Confirm rate limit triggers correctly under simulated bot load
- [ ] Implement Phase A `cited_articles` tagging pipeline → eliminates
      cross-treaty wrong-link risk
- [ ] (Optional) Add Cloudflare Turnstile if Layer 1+2 protection
      proves insufficient

When all four are checked, Ask tab can drop the BETA marker.
