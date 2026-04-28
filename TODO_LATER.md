# Backlog — work deferred for later

## TopicTags taxonomy *(deferred 28 April 2026)*

**Status:** open · **Priority:** medium · **Effort:** 1–2 days

The metadata-audit pass added the `articles` field (treaty-article references)
to all 186 GC records. We deliberately deferred the parallel `topicTags` field
because it requires a *taxonomy decision* rather than just regex extraction.

### What this requires

A controlled vocabulary of thematic tags, complementary to the concerned-group
labels (which target *who* a paragraph is about). `topicTags` should target
*what* the GC is about: subject matter, not population.

Three options were on the table when we deferred this:

1. **Custom taxonomy** designed for the corpus.
   - Pros: tightest fit to actual content, fastest to navigate.
   - Cons: maintenance burden, less interoperable.
2. **UNESCO Thesaurus** — UN's own, well-maintained, multilingual.
   - Pros: official, interoperable, broad coverage.
   - Cons: ~7 000 terms, much broader than we need.
3. **EuroVoc** (EU's multilingual thesaurus).
   - Pros: well-curated, good legal/policy coverage.
   - Cons: EU-centric framing.
4. **AGROVOC / FAO** — overlap with food, water, environment GCs only.

### Recommended approach when picking this up again

- Start by clustering the 186 abstracts (now in metadata) and the article
  references — many obvious tag candidates will fall out.
- A first cut probably needs ~30–40 tags. Examples that recur in the corpus:
  *death penalty*, *armed conflict*, *non-refoulement*, *digital rights*,
  *enforced disappearance*, *fair trial*, *housing*, *food security*,
  *climate change*, *forced eviction*, *trafficking*, *informal economy*,
  *gender-based violence*, *language rights*, *self-determination*,
  *minority rights*, *temporary special measures*, *reservations*,
  *reporting obligations*, *international cooperation*.
- Generation strategy: assign tags through a hybrid pipeline — regex for
  obvious markers, then human review of the residual.

### When done

- Add `topicTags: string[]` to the GC metadata schema.
- Expose in `documents.json`.
- Add a tag filter in the website's Documents view.
- Cross-reference: a paragraph that triggers tag *T* in its document inherits
  the tag for filtering purposes? (decide on this.)

### Why we deferred

It's a project of its own, requiring taxonomy design and >1000 small
classification decisions. The articles field already gives us ~70% of the
filtering value, and the abstracts now provide a strong textual surface for
search. TopicTags can wait until a more focused session is set aside for it.

---

## Other deferred items *(add to this file as they come up)*

- **SP filename reconciliation** — 90 SP metadata records still reference
  `SR_belief_*.json` filenames, while files on disk are `*.json`. The
  `build_corpus.py` suffix-match fallback papers over this, but the canonical
  fix is to rename either the metadata or the files. Low priority.
- **SP `Mandate holder` backfill** — 88 of 153 SP records have an empty
  `Mandate holder`. Filling these requires a curated mapping of mandate
  symbols to mandate-holders' names. The website already infers committee
  affiliation from the file path, so this is non-blocking.
- **`languagesAvailable` per record** — currently defaulted to UN6 for GCs and
  `['en']` for SP. A scrape of OHCHR's per-document Download.aspx pages would
  let us record actual language availability per record (some older GCs are
  English-only; some recent ones are missing one or two languages).
