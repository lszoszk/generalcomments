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
  // The mast-folio shows "LOADING…" until paintMastFolio runs at the end
  // of boot. Wait for the actual count instead.
  await page.waitForFunction(
    () => {
      const folio = document.getElementById('mast-folio')?.textContent || '';
      return /\d+[\s ]*\d*\s*¶/.test(folio);
    },
    null,
    { timeout: 15_000 }
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
    } catch {
      // about:blank or similar — ignore.
    }
  });
}
