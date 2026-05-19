import { type ConsoleMessage, type Page } from '@playwright/test';

/**
 * Console errors we know to ignore.  These come from the cross-origin
 * VM API (when offline), Google Fonts, and benign WebKit/Firefox
 * console noise that doesn't reflect a real bug.  Match these so the
 * "no console errors" assertion stays meaningful.
 */
export const TOLERATED_PATTERNS: RegExp[] = [
  /Failed to load resource/i,
  /net::ERR_/i,
  /\/unhrdb-api\//i,                              // VM API down during tests
  /150\.254\.115\.204/i,
  /Access-Control-Allow-Origin/i,
  /Cross-Origin Request Blocked/i,
  /due to access control checks/i,
  /downloadable font/i,
  /fonts\.gstatic\.com/i,
  /flexsearch/i,                                  // FlexSearch internal warnings
  /\[unhrdb-api\] (online|unreachable)/i,         // benign info logs from pingApi
  /\[unhrdb\]/i,                                  // any internal info logs
  /sentinel observer attached/i,
];

export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (msg: ConsoleMessage) => {
    if (msg.type() !== 'error') return;
    const text = msg.text();
    if (TOLERATED_PATTERNS.some((p) => p.test(text))) return;
    errors.push(text);
  });
  page.on('pageerror', (err) => {
    if (TOLERATED_PATTERNS.some((p) => p.test(err.message))) return;
    errors.push(`pageerror: ${err.message}`);
  });
  return errors;
}

/**
 * Boot the static site and wait for the corpus to be fully loaded
 * (paintResults has fired and the result list is no longer the
 * placeholder "Loading corpus…").
 */
export async function bootApp(
  page: Page,
  url: string = '/index.html?q=disability'
): Promise<void> {
  await page.goto(url, { waitUntil: 'commit' });
  // Two boot signals matter:
  //  1. mast-folio populates with "N ¶" — fires at line ~433 of app.js,
  //     mid-boot (before corpus loads).
  //  2. body[data-active-view] gets set — fires at line ~478, AFTER the
  //     full corpus + FlexSearch index are ready. The view-routing CSS
  //     hides every <section data-view> until this runs, so any test
  //     that touches search-view UI (#fn-toggle, .workspace-grid, etc.)
  //     can race the visibility flip on slow CI runs and assert
  //     "hidden" against an element whose ancestor is still display:none.
  // Wait for BOTH so the test only proceeds when search/workspace/docs
  // sections are actually visible per CSS.
  await page.waitForFunction(
    () => {
      const folio = document.getElementById('mast-folio')?.textContent || '';
      const ready = /\d+[\s ]*\d*\s*¶/.test(folio);
      // v19.50: guard against `document.body` being null on the very
      // first poll after `waitUntil: 'commit'`. Newer Playwright
      // surfaces predicate exceptions as fatal test failures (older
      // versions silently retried), so this null deref used to be
      // invisible and now blows up the entire suite.
      if (!document.body) return false;
      const viewSet = !!document.body.dataset.activeView;
      return ready && viewSet;
    },
    null,
    // Cold boot (IndexedDB cache wiped) parses the ~48 MB corpus.json
    // and builds the FlexSearch index — ~13 s idle, more under
    // parallel-suite load. Warm-cache boots still finish in well under
    // a second, so the generous ceiling only ever bites a genuine
    // cold start; it is a max, not a delay.
    { timeout: 30_000 }
  );
}

/**
 * Convenience: type into the search input and wait for the next
 * result-paint cycle.  Honours the v18.1 ≥4-char gate.
 *
 * Some specs trigger a reading-mode bar overlay, which can briefly
 * cover the search input. Waiting for #q to be visible AND editable
 * avoids the "element is not visible" timeout I saw in the first
 * suite run.
 */
export async function typeQuery(page: Page, q: string): Promise<void> {
  const input = page.locator('#q');
  await input.scrollIntoViewIfNeeded();
  await input.waitFor({ state: 'visible' });
  await input.fill('');
  await input.fill(q);
  // Debounce + render budget. 800 ms is generous for 25 k local paragraphs.
  await page.waitForTimeout(800);
}

/**
 * Reset all per-user state so each test starts clean.
 *
 * Implementation: addInitScript fires at the START of every page load
 * (well before the app's own boot reads from storage). For tests that
 * SEED localStorage between navigations, call resetWorkspace() once
 * in `beforeEach` BEFORE the first navigation — subsequent
 * `page.evaluate()` writes survive the same-origin navigations
 * because addInitScript is bound to subsequent loads but the
 * storage itself is per-origin and persists.
 */
export async function resetWorkspace(page: Page): Promise<void> {
  await page.addInitScript(() => {
    try {
      // Wipe ONLY on the very first run within this tab — sessionStorage
      // survives reloads, so a test that exercises a save+reload round-
      // trip doesn't lose its seeded state when boot fires the init
      // script again. window-scoped flags would reset on reload and
      // re-wipe the localStorage we just wrote.
      if (sessionStorage.getItem('__unhrdbResetDone') === '1') return;
      sessionStorage.setItem('__unhrdbResetDone', '1');
      Object.keys(localStorage)
        .filter((k) => k.startsWith('unhrdb_'))
        .forEach((k) => localStorage.removeItem(k));
      // v19.8: drop the cached FlexSearch index. Tests that seed synthetic
      // footnotes mutate corpus.json after fetch, but the cache key is the
      // upstream sha, so without this the seeded fnText would never be
      // indexed (the previous test run's index would be restored).
      try { indexedDB.deleteDatabase('gr-cache'); } catch {}
      // v19.50.1 (audit Step 3.B): pre-mark the first-visit welcome
      // card as already seen, otherwise it pops up on every test boot
      // and intercepts clicks on the dossier / search controls.
      // Without this every reset-then-click test races the welcome
      // overlay (visible 600ms after the loader fades) and times out
      // with "subtree intercepts pointer events".
      localStorage.setItem('unhrdb_welcome_seen_v1', '1');
    } catch {
      // about:blank or similar — ignore.
    }
  });
}

/**
 * Seed synthetic footnotes onto specific paragraphs by intercepting the
 * corpus.json fetch BEFORE the app reads it. Used by the v19.8 footnote
 * tests: production data has no footnotes yet, but the UX must still be
 * exercised end-to-end so we can catch render / popover / search regressions.
 *
 * Each entry mutates exactly one paragraph by id:
 *   - patches `text` to insert [[fn:N]] markers at the given offsets (or
 *     appends them if no anchor is given)
 *   - sets `footnotes: [{n, text}]`
 *
 * Pass `[]` to disable seeding without changing the call site.
 */
export interface FootnoteSeed {
  paraId: string;
  /** Footnote bodies. Each becomes a [[fn:n]] marker appended to text unless `anchor` is set. */
  footnotes: { n: number; text: string; anchor?: string }[];
}
export async function seedFootnotes(page: Page, seeds: FootnoteSeed[]): Promise<void> {
  await page.addInitScript((seeds) => {
    // Tell ensureSearchIndex() not to use the IDB-cached index — the cache
    // key is the upstream sha and our seeded fnText would otherwise be
    // missing from the restored (stale) index.
    (window as any).__unhrdbDisableIdxCache = true;
    const _fetch = window.fetch.bind(window);
    window.fetch = async (...args: Parameters<typeof fetch>) => {
      const resp = await _fetch(...args);
      const url = typeof args[0] === 'string' ? args[0] : (args[0] as URL | Request).toString();
      if (!/corpus\.json(\?.*)?$/.test(url)) return resp;
      try {
        const body = await resp.clone().json();
        const byId = new Map<string, any>();
        for (const p of body) byId.set(p.id, p);
        for (const s of seeds) {
          const p = byId.get(s.paraId);
          if (!p) continue;
          let text = String(p.text || '');
          for (const f of s.footnotes) {
            const marker = `[[fn:${f.n}]]`;
            if (f.anchor && text.includes(f.anchor)) {
              const idx = text.indexOf(f.anchor) + f.anchor.length;
              text = text.slice(0, idx) + marker + text.slice(idx);
            } else {
              text = text + marker;
            }
          }
          p.text = text;
          p.footnotes = s.footnotes.map(({ n, text }) => ({ n, text }));
        }
        return new Response(JSON.stringify(body), {
          status: resp.status,
          statusText: resp.statusText,
          headers: resp.headers,
        });
      } catch {
        return resp;
      }
    };
  }, seeds as any);
}
