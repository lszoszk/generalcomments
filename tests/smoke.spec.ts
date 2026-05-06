import { expect, test } from '@playwright/test';
import { bootApp, collectConsoleErrors, resetWorkspace, typeQuery } from './_helpers';

/**
 * Smoke tests — catch the regression classes we've actually been hit by:
 *
 *  1. boot              — app.js throws early and the page sits on
 *                         "Loading corpus…" forever (we've seen this
 *                         from a botched edit to runSearchViaApi)
 *  2. searchWired       — typing in #q produces results (≥4 chars)
 *  3. fourCharGate      — 1-3 chars short-circuit with a hint
 *  4. boolean           — AND / OR / NOT / paren / phrase parser
 *  5. wildcard          — prefix* expands stems
 *  6. emptyState        — 0-result query renders the tailored card
 *  7. clickToDossier    — click result → dossier paints with toolbar
 *  8. dossierToolbar    — 7 buttons in the right order, equal width
 *  9. openInDocFromR    — R opens the active ¶ in the full-doc reader
 * 10. workspaceBadge    — bookmarking flips the masthead badge count
 * 11. saveSearchPersists — saved search survives a tab reload
 * 12. shareUrlRoundTrip — ?q=X&p=Y opens to the right paragraph
 *
 * The dataset numbers asserted below are bounds, not exact counts —
 * the corpus changes over time and exact-equality assertions are
 * the most common false-positive class in these suites.
 */

test.beforeEach(async ({ page }) => {
  await resetWorkspace(page);
});

test('1. boot · page reaches "ready" without console errors', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await bootApp(page);
  // Mast folio reads e.g. "VOL. I · NO. 1 · 29 APRIL 2026 · 132 711 ¶ · 3296 DOCUMENTS"
  // The number includes a NARROW NO-BREAK SPACE (toLocaleString output) so
  // we match permissively — \s alone may not catch every thin-space variant.
  // v19.43+: #mast-folio also wraps a progress-bar child, so the textContent
  // is followed by whitespace. Assert against the inner #mast-folio-text
  // span instead of the wrapper to avoid the trailing whitespace problem.
  await expect(page.locator('#mast-folio-text')).toContainText(/¶/);
  await expect(page.locator('#mast-folio-text')).toContainText(/DOCUMENTS\s*$/);
  expect(errors, errors.join('\n')).toEqual([]);
});

test('2. searchWired · typing 4+ chars renders rows', async ({ page }) => {
  await bootApp(page, '/index.html');
  await typeQuery(page, 'disability');
  // Result-list has ≥1 .result li
  const rows = page.locator('.result');
  await expect(rows.first()).toBeVisible({ timeout: 5_000 });
  expect(await rows.count()).toBeGreaterThanOrEqual(10);
  // Result count badge updates
  await expect(page.locator('#result-count')).toContainText(/\d+\s*¶/);
});

test('3. fourCharGate · 1-3 chars show the "keep typing" hint', async ({ page }) => {
  await bootApp(page, '/index.html');
  await page.locator('#q').fill('di');           // 2 chars
  await page.waitForTimeout(400);
  await expect(page.locator('#results-title')).toContainText(/Keep typing/i);
  await expect(page.locator('#result-count')).toContainText(/chars/);
  // No rows rendered yet
  expect(await page.locator('.result').count()).toBe(0);
});

test('4. boolean · trafficking AND children NOT (sexual)', async ({ page }) => {
  await bootApp(page, '/index.html');
  await typeQuery(page, 'trafficking AND children NOT (sexual)');
  // We expect a non-trivial result count (>10 in the GC corpus)
  const count = await page.locator('#result-count').textContent();
  const n = parseInt((count || '').replace(/[^\d]/g, ''));
  expect(n).toBeGreaterThan(5);
  // Top hit's snippet must contain "trafficking" and "children", and
  // explicitly not the word "sexual" (the NOT clause).
  const firstSnippet = (await page.locator('.result-text').first().textContent()) || '';
  expect(firstSnippet.toLowerCase()).toContain('trafficking');
  expect(firstSnippet.toLowerCase()).toMatch(/children?/);
  // (We can't reliably assert "not sexual" — boolean NOT is doc-level
  // not snippet-level — but the FTS5 boolean parser already covers that
  // in tests/contracts/api.spec.ts.)
});

test('5. wildcard · discriminat* expands stems', async ({ page }) => {
  await bootApp(page, '/index.html');
  await typeQuery(page, 'discriminat*');
  const count = await page.locator('#result-count').textContent();
  const n = parseInt((count || '').replace(/[^\d]/g, ''));
  expect(n).toBeGreaterThan(50);                  // discrimination, discriminate, discriminatory…
  // Snippet should contain a discrimin* token highlighted
  const highlights = await page.locator('.result-text mark').count();
  expect(highlights).toBeGreaterThan(0);
});

test('6. emptyState · 0-result query renders the tailored card', async ({ page }) => {
  await bootApp(page, '/index.html');
  await typeQuery(page, 'xyzzy quux');
  await expect(page.locator('.result-empty')).toBeVisible();
  await expect(page.locator('.empty-title')).toContainText(/No paragraph matches/i);
  // The syntax cheatsheet must always be present in the empty card.
  await expect(page.locator('.empty-syntax')).toContainText(/exact phrase/);
});

test('7. clickToDossier · click row → dossier paints', async ({ page }) => {
  await bootApp(page, '/index.html');
  await typeQuery(page, 'disability');
  await page.locator('.result').first().click();
  await expect(page.locator('.dossier-title')).toBeVisible();
  // v19.43-fix8: the loose toolbar was replaced by a sticky footer that
  // carries role="toolbar". The class renamed to `.dossier-footer`;
  // update the assertion accordingly.
  await expect(page.locator('.dossier-footer')).toBeVisible();
});

test('8. dossierFooter · primary Cite + 3 quick-icons + More menu', async ({ page }) => {
  // v19.43-fix8: the loose 7-button toolbar was replaced by a sticky
  // footer with a primary "Cite" CTA, three quick-action icon buttons
  // (Save / Note / Copy), and a "⋯ More" overflow that holds the
  // less-frequent actions (permalink, open-in-reader, cite-other,
  // flag-a-problem).
  await bootApp(page, '/index.html');
  await typeQuery(page, 'disability');
  await page.locator('.result').first().click();
  // Primary CTA visible + carries a Cite label.
  await expect(page.locator('.dossier-cta')).toBeVisible();
  await expect(page.locator('.dossier-cta-label')).toContainText(/Cite/i);
  // Three quick-action icon buttons by id (matches the markup).
  for (const id of ['#ws-bookmark', '#ws-note-toggle', '#ws-copy']) {
    await expect(page.locator(id)).toBeVisible();
  }
  // More menu summary visible (collapsed by default).
  const moreSummary = page.locator('#dossier-more summary');
  await expect(moreSummary).toBeVisible();
  // Toggle the <details> element directly — Playwright's click on a
  // <summary> element occasionally times out on stability when the
  // dossier is mid-animation; flipping the parent's `open` attribute
  // is the same user-visible effect with no synthetic-click flakiness.
  await page.locator('#dossier-more').evaluate((el: Element) =>
    (el as HTMLDetailsElement).open = true
  );
  for (const id of ['#ws-permalink', '#ws-read', '#cite-other-trigger', '#ws-flag']) {
    await expect(page.locator(id)).toBeVisible();
  }
});

test('9. openInDocFromR · R navigates to full-document reader', async ({ page }) => {
  // v19.15: the styling-only "reading mode" overlay was retired. Pressing
  // R (or clicking 📖 Read) now opens the active paragraph inside the
  // full document reader (the existing #documents/<docId>?p=… deep
  // link). The R5 docs-reader test verifies the underlying landing page;
  // this one verifies the keyboard shortcut wiring from the dossier.
  //
  // v19.43-fix3: the search-view URL no longer carries `?p=<paraId>` —
  // the active paragraph is per-session state, not a share param. Read
  // the active row's `data-para-id` instead, then assert that pressing
  // R produces a `?p=<that>` URL on the documents view (where ?p IS
  // intentional, since you DO share a deep link to a paragraph).
  await bootApp(page, '/index.html');
  await typeQuery(page, 'disability');
  await page.locator('.result').first().click();
  const paraId = await page.locator('.result.is-active').first().getAttribute('data-para-id');
  expect(paraId).toBeTruthy();
  await page.locator('body').press('r');
  await page.waitForFunction(() => window.location.hash.startsWith('#documents/'));
  expect(page.url()).toContain(`p=${paraId}`);
  await expect(page.locator('.docs-reader-para.is-active'))
    .toHaveAttribute('data-para-id', paraId!);
});

test('10. workspaceBadge · ★ flips the badge count', async ({ page }) => {
  await bootApp(page, '/index.html');
  await typeQuery(page, 'disability');
  // Initially: badge text is empty / element hidden via the [hidden]
  // attribute. Some browsers in headless mode still report element as
  // present in the layout — assert the rendered count is "" instead.
  expect(await page.locator('#workspace-badge').textContent()).toBe('');
  // Click the first result's ☆ mark.
  await page.locator('.result .ws-mark-bm').first().click();
  await expect(page.locator('#workspace-badge')).toContainText(/^1$/);
});

test('11. saveSearchPersists · ?q + filters survive reload', async ({ page }) => {
  await bootApp(page, '/index.html?q=disability&scope=gc');
  await page.waitForTimeout(800);
  // Reload with the same URL
  await page.reload({ waitUntil: 'commit' });
  await page.waitForFunction(() => /\d+\s*¶/.test(document.getElementById('mast-folio')?.textContent || ''));
  await page.waitForTimeout(800);
  await expect(page.locator('#q')).toHaveValue('disability');
  await expect(page.locator('.scope-opt[data-scope="gc"]')).toHaveClass(/is-active/);
  // Plus the result list rebuilt — at least one row.
  expect(await page.locator('.result').count()).toBeGreaterThan(0);
});

test('12. shareUrlRoundTrip · ?q=X opens with that query', async ({ page }) => {
  await bootApp(page, '/index.html?q=reasonable+accommodation');
  await page.waitForTimeout(800);
  await expect(page.locator('#q')).toHaveValue('reasonable accommodation');
  // Result count must be > 0 — this term is well-attested in CRPD GCs.
  const txt = await page.locator('#result-count').textContent();
  const n = parseInt((txt || '').replace(/[^\d]/g, ''));
  expect(n).toBeGreaterThan(0);
});

test('13. themePersists · dark mode survives reload (v19.6 B3)', async ({ page }) => {
  await bootApp(page, '/index.html');
  // Initial state: light theme (default in HTML).
  expect(await page.locator('html').getAttribute('data-theme')).toBe('light');
  // Toggle ◐.
  await page.locator('#theme-toggle').click();
  expect(await page.locator('html').getAttribute('data-theme')).toBe('dark');
  // Reload — must still be dark.
  await page.reload({ waitUntil: 'commit' });
  await page.waitForFunction(() => /¶/.test(document.getElementById('mast-folio')?.textContent || ''));
  expect(await page.locator('html').getAttribute('data-theme')).toBe('dark');
  // Toggle back to light + reload + verify the round-trip.
  await page.locator('#theme-toggle').click();
  await page.reload({ waitUntil: 'commit' });
  await page.waitForFunction(() => /¶/.test(document.getElementById('mast-folio')?.textContent || ''));
  expect(await page.locator('html').getAttribute('data-theme')).toBe('light');
});

test('14. apiBreakdownPills · server total wins over page-slice (v19.6 U2)', async ({ page }) => {
  // Mock /api/search with total=1844 + breakdown = {gc:300, jur:1500, sp:44}.
  // The 200-row page slice we render only contains GC rows; without U2
  // the JUR + SP pills would read 0.
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify({ version: 'mock', byType: {gc:{},jur:{},sp:{}}, totalParagraphs: 1844 }) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({
        query: 'disability', ftsExpr: '"disability"', scope: 'all',
        total: 1844, page: 1, pageSize: 200, tookMs: 50,
        breakdown: { gc: 300, jur: 1500, sp: 44 },
        // Only return GC rows in the page slice — to verify the pills
        // come from breakdown, not the rendered set.
        hits: Array.from({ length: 50 }, (_, i) => ({
          rowid: i + 1, para_id: `m-${i+1}`, doc_id: 'mock', idx: i+1, n: String(i+1),
          section: null, text: 'mock', type: 'gc', treaty: null, committee: 'CAT',
          mandate: null, country: null, year: 2020, adoption_date: '2020', signature: 'M',
          outcome: null, name: 'M', name_short: 'M',
          snippet: '<mark>disability</mark>', score: -10,
        })),
        alsoTry: [],
      }),
    })
  );
  await bootApp(page, '/index.html?api=1&scope=all&q=disability');
  await page.waitForTimeout(1500);
  await expect(page.locator('#rb-gc')).toContainText(/^GC 300\s*¶/);
  await expect(page.locator('#rb-jur')).toContainText(/^JUR 1.?500\s*¶/);
  await expect(page.locator('#rb-sp')).toContainText(/^SP 44\s*¶/);
});
