# Tests

Playwright suite for the UN Human Rights Database static frontend.
Adapted from the [HURIDOCS dashboard codex-pages](../) test rig
maintained by the same author.

## Layout

```
tests/
  _helpers.ts          shared bootApp / typeQuery / resetWorkspace
  smoke.spec.ts        12 boot + search + workspace regression checks
  dossier-toolbar.spec.ts  D1-D7   the v18 / v18.2 / v19.5 toolbar
  workspace.spec.ts    W1-W8   bookmarks / notes / pins / saved-searches
                                + Markdown / JSON export
  docs-reader.spec.ts  R1-R8   3-pane reader, deep-links, JUR shard load
  report.spec.ts       F1-F8   /api/feedback flow (mocked POST)
  api-mode.spec.ts     A1-A8   ?api=1 wiring + body= filter + pagination
  a11y.spec.ts                axe-core WCAG 2.2 AA on each top-level view
  contracts/api.spec.ts   C1-C12  LIVE VM endpoint contracts
```

## Run

```bash
npm test              # chromium only, headless — fast smoke gate
npm run test:headed   # chromium, watch the browser
npm run test:ui       # interactive Playwright UI

npm run test:firefox  # Firefox project
npm run test:webkit   # Safari/WebKit project
npm run test:mobile   # iPhone 13 viewport
npm run test:cross-browser  # all four

npm run test:contracts  # LIVE — hits https://150.254.115.204/unhrdb-api
```

## Why this exists

We've been hit by specific classes of regression that are easy to
write a test for:

| Regression                          | Spec                       |
|-------------------------------------|----------------------------|
| boot stalls at "Loading corpus…"    | smoke #1                   |
| 1-3 char search burns CPU on JUR    | smoke #3 (≥4-char gate)    |
| boolean parser drops NOT branches   | smoke #4                   |
| `"AI bias"` returns 0 (no synonyms) | api-mode A8                |
| Cite button visually shouty         | dossier-toolbar D6         |
| Reading mode "can't exit"           | smoke #9 + dossier D7      |
| Workspace bookmarks lose their text | workspace W3, W4           |
| API filter chip lumps 3 params      | api-mode A4                |
| Pagination across the 200-row API   | api-mode A7                |
| `/api/feedback` body annotation     | report.spec + contracts C11|

A green `npm test` is the floor. The contracts suite is a separate
script (it depends on the live VM) and runs less often.

## Adding a test

1. Pick the right file (or create a new one if the surface is new).
2. Use `bootApp(page)` so corpus-load timing is consistent across
   browsers.
3. Use `resetWorkspace(page)` in a `beforeEach` so localStorage
   state never leaks between tests.
4. Mock cross-origin requests with `page.route('**/unhrdb-api/...')`
   — only `tests/contracts/` should hit the live VM.

## CI

The suite is designed to run on `npm test` (chromium) in pull-request
gates. Cross-browser + contracts run nightly or on demand. None of
the tests need a live API; the api-mode suite mocks every endpoint.
