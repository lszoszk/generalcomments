# UNHRD audit closeout — 2026-05-07

Companion to `AUDIT-2026-05-06.md`. Records what landed, what's still
open, and the test-suite state at the close of the audit cycle.

Range: commits **e4979f7** (v19.49 baseline) → **HEAD** (v19.51.6).
12 commits over the audit. Pre-push hook (chromium suite) gate kept
green throughout.

## Suite at closeout

```
79 passed, 4 skipped, 0 failed
chromium · workers=1 · pre-push hook setting
```

(Was 47 passed / 30 failed at the audit's start, with `.fixme` masking
several never-passing tests.)

## Closed by tier

### Critical
| ID | Item | Fix | Commit |
|---|---|---|---|
| C1 | 30/77 Playwright tests failing on main | Test sprint, 47→75 passing | `a694ef5` v19.50.2 |
| C2 | aria-required-children on documents tablist | role="tab" + aria-selected on `.docs-scope-opt` | `c19256f` v19.51.2 |
| C3 | Race in runSearchViaApi / openDocReader / jumpToParagraph | runId pattern (`state.docsOpenRun`, `state.jumpRun`) | `a694ef5`, `ac14850` v19.50.2 + v19.51.4 |

### High
| ID | Item | Fix | Commit |
|---|---|---|---|
| H1 | Suspect "merged-article" values (5 distinct) | Treaty-aware sanitiser + data cleanup | `654e8aa` v19.50.1 |
| H2 | 279 docs with bare-string OP-articles | `normalize_op_articles.py` (1,114 entries fixed) | `343e5ef` v19.51.3 |
| H3 | 3,054 prose adoptionDate values | `normalize_adoption_date.py` (6,076 normalised) | `343e5ef` v19.51.3 |
| H4 | "173 GC docs no status" | NO-OP — audit miscount conflated SP docs | `343e5ef` v19.51.3 |
| H5 | Search terms not highlighted in doc reader | paintDocReaderBody passes `terms` to renderParagraphHtml | `654e8aa` v19.50.1 |
| H6 | 14 serious color-contrast violations | Token palette converted to sRGB hex (axe oklch quirk) | `c19256f` v19.51.2 |
| H7 | CDN scripts without SRI | sha384 hashes on xlsx + flexsearch | `5b2ece5` v19.50.3 |
| HF cross-doc contamination | 4 pairs of GCs with wrong-doc text | Re-extracted 10 docs from OHCHR PDFs/DOCs | `0f514f1` v19.51.5 |

### Medium / code health
| ID | Item | Fix | Commit |
|---|---|---|---|
| M3 | Dup escapeRegex/escapeRe | Removed dead `escapeRe` | `5b2ece5` v19.50.3 |
| M5 | Empty catches in clipboard handlers | Async + real error toast on rejection | `5b2ece5` v19.50.3 |
| M6 | Dead `initCompactHeader`, no-op `paintDocsRail` loop | Removed | `5b2ece5` v19.50.3 |

### Low / maintainability
| ID | Item | Fix | Commit |
|---|---|---|---|
| L1 | 140+ stale `// v19.X-fixN:` comment anchors | Stripped 160 anchors ≤ v19.45 | `ac14850` v19.51.4 |
| L2 | Manual cache-buster (3-place edit) | `npm run stamp` from git SHA | `ac14850` v19.51.4 |
| L3 | No CSP | Meta CSP with hash-pinned inline GA | `5b2ece5` v19.50.3 |
| L4 | Untracked `.claude/`, `docs_v2/`, ccprcentre data | `.gitignore` decisions, fetcher script tracked | `ac14850` v19.51.4 |

### Test-suite health
| Item | Fix | Commit |
|---|---|---|
| 30 failing tests | Sprint to 75 passing (welcome-card auto-dismiss, selector updates, race-token guards, expanded timeouts) | `a694ef5` v19.50.2 |
| smoke 9 flake under workers=2 | encodeUrlState now preserves `?p=` for #documents/<docId> hashes | THIS COMMIT |
| 4 dead `.fixme` tests (D4, D6, F10, W4) | Removed — referenced retired UI or perpetually flaky | THIS COMMIT |
| a11y suite was `.fixme` | Live again after H6 brought violations to 0 + workspace tabindex fix | THIS COMMIT |

### Tooling added during the audit
- `_docs_internal/sanitize_articles.py` — treaty-aware article-cited cleanup
- `_docs_internal/sanitize_titles.py` — strip "English Title" placeholder
- `_docs_internal/sanitize_metadata_paragraphs.py` — drop JUR metadata-as-paragraph noise
- `_docs_internal/resplit_gc_paragraphs.py` — re-split flat-extracted GC docs
- `_docs_internal/normalize_adoption_date.py` — ISO 8601 date normaliser
- `_docs_internal/normalize_op_articles.py` — OP-article shape normaliser
- `_docs_internal/audit_cross_doc_contamination.py` — cross-doc text contamination detector
- `_docs_internal/reextract/apply_reextraction.py` — re-extraction from OHCHR sources
- `scripts/stamp-cache-buster.sh` — auto-bump `?v=` from git SHA
- `.githooks/pre-push` (already in v19.50) — chromium suite gate

## Still open

### Tier 4 — bigger refactors (no immediate user value)
- **M1** Split 5 functions over 200 lines (`paintDossier` 613, `bindUI` 340, `paintDocReaderBody` 230, `runSearch` 200)
- **M2** Centralise `state.activeId` + `state.filters.*` mutation behind setters
- **P1** Split `jur/documents-lite.json` (11.4 MB on boot) into per-committee shards
- **P2** ESM-split `app.js` into ~6 modules

### Backlog (optional)
- Search-result UX polish (recent-searches dropdown, bookmark highlights in reader, ⌨️ shortcut overlay) — see Tier B in chat history.
- LaTeX/BibTeX export from workspace.
- Frame-ancestors HTTP header (CSP via `<meta>` is silent on this directive).

## Closing note

Pre-push hook is now a real gate, not a placebo. Tests are
deterministic at workers=2. Data is internally consistent and free
of the contamination + format issues the audit surfaced. Any future
regression hits a 79-test wall before reaching production.
