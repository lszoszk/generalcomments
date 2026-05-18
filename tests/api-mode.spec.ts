import { expect, test } from '@playwright/test';
import { bootApp, resetWorkspace } from './_helpers';

/**
 * API-mode tests (?api=1). Mocks the API endpoints so we exercise the
 * frontend wiring without depending on the live VM.
 *
 *  A1. badgeAppears        — pingApi paints "API · NN ms" in the searchbar
 *  A2. fallbackOnError     — pingApi 500 → fallback to local; no infinite loop
 *  A3. searchRoutes        — JUR scope ?api=1&q=X hits /api/search
 *  A4. searchUsesBodyParam — chip filter sends body= (not committees+treaties+mandates)
 *  A5. snippetFromApi      — server <mark> snippet rendered as-is
 *  A6. apiTotalShown       — apiTotal > rendered → title says "showing first NN"
 *  A7. paginateAcrossApi   — scrolling triggers /api/search?page=2 fetch
 *  A8. alsoTryRendered     — 0-result + alsoTry → synonym buttons in empty state
 */

test.beforeEach(async ({ page }) => {
  await resetWorkspace(page);
});

// Tiny helper to build a mock /api/search response with a synthetic
// hit set sized to whatever the test wants.
function mockSearchPage(opts: {
  total: number;
  page: number;
  pageSize: number;
  alsoTry?: string[];
}) {
  const start = (opts.page - 1) * opts.pageSize;
  const hits = Array.from({ length: Math.min(opts.pageSize, Math.max(0, opts.total - start)) }, (_, i) => ({
    rowid: start + i + 1,
    para_id: `mock-${start + i + 1}`,
    doc_id: 'mock-doc',
    idx: start + i + 1,
    n: String(start + i + 1),
    section: null,
    text: `Mock paragraph #${start + i + 1} — substantive disability content goes here.`,
    type: 'jur',
    treaty: 'CRPD',
    committee: 'CRPD',
    mandate: null,
    country: 'TestLand',
    year: 2024,
    adoption_date: '2024-04-29',
    signature: `MOCK/${start + i + 1}`,
    outcome: 'violation_found',
    name: 'Mock Document',
    name_short: 'MockDoc',
    snippet: `<mark>disability</mark> mention #${start + i + 1}`,
    score: -10 - i * 0.1,
  }));
  return {
    query: 'disability',
    ftsExpr: '"disability"',
    scope: 'jur',
    total: opts.total,
    page: opts.page,
    pageSize: opts.pageSize,
    tookMs: 42,
    breakdown: { gc: 0, jur: opts.total, sp: 0 },
    hits,
    alsoTry: opts.alsoTry || [],
  };
}

const MOCK_STATS = {
  version: 'mock', manifest: {}, totalParagraphs: 132711,
  byType: { gc: { documents: 186, paragraphs: 7103 },
            jur: { documents: 2937, paragraphs: 106868 },
            sp: { documents: 173, paragraphs: 18740 } },
};

test('A1. badgeAppears · pingApi paints "API · NN ms" pill', async ({ page }) => {
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await bootApp(page, '/index.html?api=1');
  // pingApi() runs at the end of boot (after FlexSearch index build); on
  // CI with the v19.9-enriched JUR catalog this can take longer than the
  // default 5 s assertion timeout. Wait explicitly.
  await expect(page.locator('#api-badge')).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('#api-badge')).toContainText(/API · \d+ ms/);
});

test('A2. fallbackOnError · 500 from /api/stats → no infinite loop', async ({ page }) => {
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 500, body: 'oops' })
  );
  await page.route('**/unhrdb-api/api/search', (route) =>
    route.fulfill({ status: 500, body: 'oops' })
  );
  await bootApp(page, '/index.html?api=1&scope=jur&q=disability');
  // Local fallback kicks in: rows render OR an "unavailable" message
  // shows. Either way: no infinite recursion (page didn't hang).
  await page.waitForTimeout(2000);
  // Badge says "API · offline"
  await expect(page.locator('#api-badge')).toContainText(/offline/i);
});

test('A3. searchRoutes · scope=jur GETs /api/search', async ({ page }) => {
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(mockSearchPage({ total: 50, page: 1, pageSize: 200 })) })
  );
  // v19.11 added a 1.5 s ping-grace window inside runSearch which, on top
  // of corpus load + FlexSearch build, easily exceeds a fixed
  // waitForTimeout in CI. Wait on the actual request landing instead.
  const searchReq = page.waitForRequest(
    (req) => /unhrdb-api\/api\/search/.test(req.url()),
    { timeout: 15_000 },
  );
  await bootApp(page, '/index.html?api=1&scope=jur&q=disability');
  await searchReq;
});

test('A4. searchUsesBodyParam · chip filter sends body=, not lumped 3-way (v19.4)', async ({ page }) => {
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(mockSearchPage({ total: 50, page: 1, pageSize: 200 })) })
  );
  const searchReq = page.waitForRequest(
    (req) => /unhrdb-api\/api\/search/.test(req.url()),
    { timeout: 15_000 },
  );
  await bootApp(page, '/index.html?api=1&scope=jur&q=disability&tb=CRPD');
  const req = await searchReq;
  const capturedUrl = req.url();
  // Must contain body=CRPD and NOT contain treaties=CRPD&committees=CRPD&mandates=CRPD
  expect(capturedUrl).toContain('body=CRPD');
  expect(capturedUrl).not.toMatch(/committees=[^&]*CRPD[^&]*&treaties=[^&]*CRPD[^&]*&mandates=[^&]*CRPD/);
});

test('A5. snippetFromApi · server <mark> rendered verbatim', async ({ page }) => {
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(mockSearchPage({ total: 5, page: 1, pageSize: 200 })) })
  );
  await bootApp(page, '/index.html?api=1&scope=jur&q=disability');
  await page.waitForTimeout(1200);
  await expect(page.locator('.result-text mark').first()).toBeVisible();
  await expect(page.locator('.result-text mark').first()).toContainText('disability');
});

test('A6. apiTotalShown · title surfaces server total even past page slice', async ({ page }) => {
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(mockSearchPage({ total: 1844, page: 1, pageSize: 200 })) })
  );
  await bootApp(page, '/index.html?api=1&scope=jur&q=disability');
  await page.waitForTimeout(1500);
  await expect(page.locator('#result-count')).toContainText(/1.?844/);
  await expect(page.locator('#results-title')).toContainText(/showing first 200/i);
});

test('A7. paginateAcrossApi · second-page fetch on scroll', async ({ page }) => {
  let pages: number[] = [];
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) => {
    const url = new URL(route.request().url());
    const p = parseInt(url.searchParams.get('page') || '1');
    pages.push(p);
    route.fulfill({
      status: 200,
      body: JSON.stringify(mockSearchPage({ total: 600, page: p, pageSize: 200 })),
    });
  });
  // Wait for the page=1 request before kicking off scrolls — otherwise the
  // first scroll fires before the initial request lands and the scroll
  // handler bails because the result list is empty.
  const firstReq = page.waitForRequest(
    (req) => /unhrdb-api\/api\/search/.test(req.url()),
    { timeout: 15_000 },
  );
  await bootApp(page, '/index.html?api=1&scope=jur&q=disability');
  await firstReq;
  // Scroll the .results section to trigger pagination — keep scrolling
  // until the page=2 request shows up, with a hard cap so a regression
  // doesn't run forever.
  for (let i = 0; i < 20 && !pages.includes(2); i++) {
    await page.evaluate(() => {
      // Desktop: the .results pane is the scroll container. Mobile
      // (single-column): the whole page scrolls instead. Drive both so
      // the infinite-scroll sentinel enters the viewport either way.
      const sec = document.querySelector('.results') as HTMLElement | null;
      if (sec) {
        sec.scrollTop = sec.scrollHeight;
        sec.dispatchEvent(new Event('scroll', { bubbles: true }));
      }
      window.scrollTo(0, document.body.scrollHeight);
      window.dispatchEvent(new Event('scroll'));
    });
    await page.waitForTimeout(500);
  }
  expect(pages).toContain(1);
  expect(pages).toContain(2);
});

test('A9. jurResultClickOpensDossier · clicking a JUR row paints the dossier', async ({ page }) => {
  // Regression for v19.13: paintDossier looked up the active paragraph in
  // state.paragraphs (local GC corpus only), so clicking a JUR row
  // silently bailed — user lost the source link and metadata pane.
  // The dossier now consults state.paragraphById first (where JUR hits
  // are hydrated by runSearchViaApi).
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(mockSearchPage({ total: 5, page: 1, pageSize: 200 })) })
  );
  const searchReq = page.waitForRequest(
    (req) => /unhrdb-api\/api\/search/.test(req.url()),
    { timeout: 15_000 },
  );
  await bootApp(page, '/index.html?api=1&scope=jur&q=disability');
  await searchReq;
  // Click the first JUR result.
  const firstResult = page.locator('.result').first();
  await expect(firstResult).toBeVisible({ timeout: 8_000 });
  await firstResult.click();
  // Dossier should paint with the JUR-specific kind label and the
  // paragraph quote should be visible (NOT the empty "Click a paragraph…"
  // placeholder).
  const dossier = page.locator('#dossier');
  await expect(dossier.locator('blockquote .pn')).toBeVisible({ timeout: 4_000 });
  await expect(dossier.locator('.dossier-empty')).toHaveCount(0);
  // The dossier folio must reflect JUR provenance.
  await expect(dossier).toContainText(/JURISPRUDENCE/i);
});

test('A8. alsoTryRendered · 0-result + alsoTry → synonym buttons', async ({ page }) => {
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({
        ...mockSearchPage({ total: 0, page: 1, pageSize: 200 }),
        alsoTry: ['algorithmic discrimination', 'profiling'],
      }),
    })
  );
  await bootApp(page, '/index.html?api=1&scope=jur&q=AI+bias');
  await page.waitForTimeout(1500);
  await expect(page.locator('.empty-also-try')).toBeVisible();
  const suggestions = await page.locator('[data-empty-suggest]').allTextContents();
  expect(suggestions).toContain('algorithmic discrimination');
  expect(suggestions).toContain('profiling');
});
