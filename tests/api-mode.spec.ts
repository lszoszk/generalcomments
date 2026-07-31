import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import { bootApp, resetWorkspace, typeQuery } from './_helpers';

/**
 * API-mode tests (?api=1). Mocks the API endpoints so we exercise the
 * frontend wiring without depending on the live VM.
 *
 *  A1. badgeAppears        — pingApi paints "API · NN ms" in the searchbar
 *  A2. fallbackOnError     — pingApi 500 → fallback to local; no infinite loop
 *  A2b. spRecoversAfterBootFailure — SP retries after a transient ping failure
 *  A2c. spOutageIsNotZeroResults   — SP outage never masquerades as 0 matches
 *  A2d. spDossierHydratesFootnotes — API hit loads its static citation bodies
 *  A3. searchRoutes        — JUR scope ?api=1&q=X hits /api/search
 *  A4. searchUsesBodyParam — chip filter sends body= (not committees+treaties+mandates)
 *  A5. snippetFromApi      — server <mark> snippet rendered as-is
 *  A6. apiTotalShown       — apiTotal > rendered → title says "showing first NN"
 *  A7. paginateAcrossApi   — scrolling triggers /api/search?page=2 fetch
 *  A8. alsoTryRendered     — 0-result + alsoTry → synonym buttons in empty state
 */

test.beforeEach(async ({ page, context }) => {
  try {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  } catch { /* WebKit does not expose these permissions. */ }
  await resetWorkspace(page);
});

async function copyDossierCitation(page: any, format: string) {
  await page.locator('#dossier-more').evaluate((el: Element) =>
    (el as HTMLDetailsElement).open = true
  );
  await page.locator('#cite-other-trigger').click();
  await page.locator(`#cite-pop .cite-opt[data-cite-key="${format}"]`).click();
  return page.evaluate(() => navigator.clipboard.readText());
}

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

test('A1. badgeAppears · pingApi paints "API · NN ms" pill (debug only)', async ({ page }) => {
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  // v19.59: the happy-state API badge is developer diagnostics — hidden
  // by default (Hick's-law declutter), surfaced with ?debug=1. pingApi()
  // still paints it; boot with the flag so the assertion can see it.
  await bootApp(page, '/index.html?api=1&debug=1');
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

test('A2b. spRecoversAfterBootFailure · SP retries API instead of showing zero matches', async ({ page }) => {
  let statsCalls = 0;
  await page.route('**/unhrdb-api/api/stats', (route) => {
    statsCalls++;
    if (statsCalls === 1) return route.fulfill({ status: 500, body: 'temporary outage' });
    return route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) });
  });
  await page.route('**/unhrdb-api/api/search**', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({
        query: 'opinion AND hold', ftsExpr: '"opinion"* AND "hold"*', scope: 'sp',
        total: 1, page: 1, pageSize: 200, tookMs: 12,
        breakdown: { gc: 0, jur: 0, sp: 1 },
        hits: [{
          rowid: 1, para_id: 'a-hrc-29-32-0020', doc_id: 'a-hrc-29-32',
          idx: 20, n: '20', section: null,
          text: 'The right to hold opinions without interference applies online and offline.',
          type: 'sp', treaty: null, committee: 'SR Freedom of Expression',
          mandate: 'Freedom of opinion and expression', country: null, year: 2015,
          adoption_date: '2015', signature: 'A/HRC/29/32', outcome: null,
          name: 'Encryption and anonymity', name_short: 'Encryption and anonymity',
          snippet: 'The right to <mark>hold</mark> <mark>opinions</mark>.', score: -1,
        }],
        alsoTry: [],
      }),
    })
  );

  await bootApp(page, '/index.html?api=1&scope=gc&q=disability');
  await expect(page.locator('#api-badge')).toContainText(/offline/i);
  await page.locator('.scope-opt[data-scope="sp"]').click();
  await typeQuery(page, 'opinion AND hold');

  await expect(page.locator('.result').first()).toBeVisible({ timeout: 10_000 });
  await expect(page.locator('#result-count')).toContainText(/1.*¶/);
  expect(statsCalls).toBeGreaterThan(1);
});

test('A2c. spOutageIsNotZeroResults · SP shows unavailable state when retry fails', async ({ page }) => {
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 500, body: 'offline' })
  );
  await page.route('**/unhrdb-api/api/search**', (route) => route.abort('failed'));

  await bootApp(page, '/index.html?api=1&scope=gc&q=disability');
  await expect(page.locator('#api-badge')).toContainText(/offline/i);
  await page.locator('.scope-opt[data-scope="sp"]').click();
  await typeQuery(page, 'opinion AND hold');

  await expect(page.locator('.empty-title')).toContainText('not a zero-result search', { timeout: 10_000 });
  await expect(page.locator('#results-title')).toContainText('temporarily unavailable');
  await expect(page.locator('#sp-api-retry')).toBeVisible();
});

test('A2d. spDossierHydratesFootnotes · API hit loads citation text from its shard', async ({ page }) => {
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({
        query: '"hold opinions" AND reasoning',
        ftsExpr: '"hold opinions" AND "reasoning"',
        scope: 'sp', total: 1, page: 1, pageSize: 200, tookMs: 8,
        breakdown: { gc: 0, jur: 0, sp: 1 },
        hits: [{
          rowid: 23, para_id: 'a-73-348-0023', doc_id: 'a-73-348',
          idx: 23, n: '23', section: ['II. Understanding artificial intelligence', 'B. Right to freedom of opinion'],
          text: '23. An essential element of the right to hold an opinion is the “right to form an opinion and to develop this by way of reasoning”.[[fn:22]]',
          type: 'sp', treaty: null, committee: 'SR Freedom of Expression',
          mandate: 'David Kaye', country: null, year: 2018,
          adoption_date: '29 August 2018', signature: 'A/73/348', outcome: null,
          name: 'Artificial Intelligence technologies and implications for the information environment',
          name_short: 'Artificial Intelligence and implications for the information environment',
          snippet: 'The right to hold an opinion includes <mark>reasoning</mark>.[[fn:22]]', score: -1,
        }],
        alsoTry: [],
      }),
    })
  );

  await bootApp(page, '/index.html?api=1&scope=sp&q=%22hold%20opinions%22%20AND%20reasoning');
  const result = page.locator('.result[data-para-id="a-73-348-0023"]');
  await expect(result).toBeVisible({ timeout: 15_000 });
  await result.click();

  const marker = page.locator('#dossier button.fn-marker[data-fn-n="22"]');
  await expect(marker).toBeVisible({ timeout: 15_000 });
  await marker.click();
  await expect(page.locator('.fn-popover-body')).toContainText('Nowak, U.N. Covenant on Civil and Political Rights');
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

test('A5b. jurDecisionYear · results use adoption year and retain communication year', async ({ page }) => {
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) => {
    const body = mockSearchPage({ total: 1, page: 1, pageSize: 200 });
    body.hits[0] = {
      ...body.hits[0],
      year: 2021,
      adoption_date: '29 August 2024',
      signature: 'CRPD/C/31/D/94/2021',
    };
    return route.fulfill({ status: 200, body: JSON.stringify(body) });
  });

  await bootApp(page, '/index.html?api=1&scope=jur&q=disability');
  const result = page.locator('.result').first();
  await expect(result).toBeVisible({ timeout: 15_000 });
  await expect(result.locator('.result-date-label')).toHaveText('Decision adopted 2024');
  await result.click();

  const grid = page.locator('#dossier .dossier-grid');
  await expect(grid).toContainText('29 August 2024');
  await expect(grid).toContainText(/Communication\s*2021/);
});

test('A5c. jurCitation · legal citation identifies the case and communication', async ({ page, browserName }) => {
  test.skip(browserName === 'webkit', 'WebKit headless blocks clipboard read');
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) => {
    const body = mockSearchPage({ total: 1, page: 1, pageSize: 200 });
    body.hits[0] = {
      ...body.hits[0],
      para_id: 'citation-jur-23', doc_id: 'citation-jur-doc', n: '23', idx: 23,
      committee: 'CRPD', treaty: 'CRPD', country: 'Sweden', year: 2024,
      adoption_date: '29 August 2024', signature: 'CRPD/C/31/D/94/2021',
      name: 'Svensson v. Sweden', name_short: 'Svensson v. Sweden',
      text: 'The Committee considered the merits of the communication.',
      snippet: 'The Committee considered the <mark>merits</mark>.',
    };
    return route.fulfill({ status: 200, body: JSON.stringify(body) });
  });

  await bootApp(page, '/index.html?api=1&scope=jur&q=merits');
  const result = page.locator('.result[data-para-id="citation-jur-23"]');
  await expect(result.locator('.source-kind-label')).toHaveText('Treaty-body decision');
  await expect(result.locator('.result-date-label')).toHaveText('Decision adopted 2024');
  await expect(result.locator('.sig-link')).toHaveAttribute(
    'href',
    /tbinternet\.ohchr\.org\/.*symbolno=CRPD%2FC%2F31%2FD%2F94%2F2021/,
  );
  await result.click();
  await expect(page.locator('#dossier .dossier-sig-link')).toHaveAttribute(
    'href',
    /tbinternet\.ohchr\.org\/.*symbolno=CRPD%2FC%2F31%2FD%2F94%2F2021/,
  );
  await expect(page.locator('#dossier .dossier-authority-note')).toContainText(
    'Outcome of an individual communication examined by a UN treaty body',
  );
  const citation = await copyDossierCitation(page, 'unfn');

  expect(citation).toContain('Committee on the Rights of Persons with Disabilities');
  expect(citation).toContain('Svensson v. Sweden');
  expect(citation).toContain('Communication No. 94/2021');
  expect(citation).toContain('U.N. Doc. CRPD/C/31/D/94/2021');
  expect(citation).toContain('¶ 23');
  expect(citation).not.toContain('General Comment');
});

test('A5d. spCitation · report citation identifies author, title, symbol, and paragraph', async ({ page, browserName }) => {
  test.skip(browserName === 'webkit', 'WebKit headless blocks clipboard read');
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({
        query: 'reasoning', ftsExpr: '"reasoning"', scope: 'sp',
        total: 1, page: 1, pageSize: 200, tookMs: 8,
        breakdown: { gc: 0, jur: 0, sp: 1 },
        hits: [{
          rowid: 1, para_id: 'a-73-348-0023', doc_id: 'a-73-348',
          idx: 23, n: '23', section: null, type: 'sp', treaty: null,
          committee: 'SR Freedom of Expression', mandate: 'David Kaye', country: null,
          year: 2018, adoption_date: '29 August 2018', signature: 'A/73/348', outcome: null,
          name: 'Artificial Intelligence technologies and implications for the information environment',
          name_short: 'Artificial Intelligence and implications for the information environment',
          text: 'An essential element of opinion is reasoning.',
          snippet: 'An essential element of opinion is <mark>reasoning</mark>.', score: -1,
        }],
        alsoTry: [],
      }),
    })
  );

  await bootApp(page, '/index.html?api=1&scope=sp&q=reasoning');
  const result = page.locator('.result[data-para-id="a-73-348-0023"]');
  await expect(result.locator('.source-kind-label')).toHaveText('Special Procedures report');
  await expect(result.locator('.result-date-label')).toHaveText('Issued 2018');
  await result.click();
  await expect(page.locator('#dossier .dossier-sig-link')).toHaveAttribute(
    'href',
    'https://docs.un.org/en/A/73/348',
  );
  await expect(page.locator('#dossier .dossier-authority-note')).toContainText(
    'not a court judgment or a treaty-body decision',
  );
  const citation = await copyDossierCitation(page, 'oscola');

  expect(citation).toContain('David Kaye');
  expect(citation).toContain('Artificial Intelligence and implications for the information environment');
  expect(citation).toContain('UN Doc A/73/348');
  expect(citation).toContain('para 23');
  expect(citation).not.toContain('General Comment');
});

test('A5e. askSpSource · Special Procedures source opens docs.un.org', async ({ page }) => {
  await page.route('**/ask-api/api/health', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify({ status: 'ok' }) })
  );
  /* Trailing ** is load-bearing: the bundle fetch carries a ?v= cache-buster
     (app.js _loadTreaties), and a glob ending at "treaties" does not match a
     URL with a query string — verified, not assumed. Without it the request
     escapes the mock and this test silently depends on the live VM. */
  await page.route('**/ask-api/api/treaties**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify({}) })
  );
  await page.route('**/ask-api/api/ask**', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({
        query: 'freedom of opinion',
        answer: 'The report addresses freedom of opinion.',
        retrieval: {},
        sources: [{
          paraId: 'ask-sp-23', docId: 'ask-sp-doc', type: 'sp',
          signature: 'A/73/348', committee: 'SR Freedom of Expression', year: 2018,
          title: 'Artificial Intelligence and implications for the information environment',
          text: 'An essential element of the right to hold an opinion is reasoning.',
          match: { bandLabel: 'Strong' },
        }],
      }),
    })
  );

  await bootApp(page, '/index.html#ask');
  await page.locator('#ask-q').fill('freedom of opinion');
  await page.locator('#ask-go').click();

  await expect(page.locator('.ask-source-act-link')).toHaveAttribute(
    'href',
    'https://docs.un.org/en/A/73/348',
  );
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

test('A7b. exportAllApiPages · JSON export is complete and reproducible', async ({ page }) => {
  const pages: number[] = [];
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) => {
    const url = new URL(route.request().url());
    const pageNumber = Number(url.searchParams.get('page') || '1');
    pages.push(pageNumber);
    return route.fulfill({
      status: 200,
      body: JSON.stringify(mockSearchPage({ total: 450, page: pageNumber, pageSize: 200 })),
    });
  });

  await bootApp(page, '/index.html?api=1&scope=jur&q=disability');
  await expect(page.locator('.result').first()).toBeVisible({ timeout: 10_000 });
  await page.locator('#export-menu').evaluate((el: Element) =>
    (el as HTMLDetailsElement).open = true
  );
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('#export-menu [data-format="json"]').click(),
  ]);
  const path = await download.path();
  expect(path).not.toBeNull();
  const payload = JSON.parse(await readFile(path!, 'utf8'));

  expect([...new Set(pages)].sort()).toEqual([1, 2, 3]);
  expect(payload.results).toHaveLength(450);
  expect(payload.provenance).toMatchObject({
    completeness: 'complete',
    exportedResultCount: 450,
    totalMatchingResults: 450,
    resultSource: 'api',
  });
  expect(payload.provenance.searchUrl).toContain('q=disability');
  expect(payload.provenance.searchUrl).toContain('scope=jur');
  expect(payload.provenance.database.apiVersion).toBe('mock');
  expect(payload.results[0]).toMatchObject({
    source_category: 'Treaty-body decision',
    document_status: 'not_applicable',
    date_type: 'Decision adopted',
  });
  expect(payload.results[0].legal_character).toContain('individual communication');
});

test('A7c. exportPageFailure · failed API page never creates a partial export', async ({ page }) => {
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) => {
    const url = new URL(route.request().url());
    const pageNumber = Number(url.searchParams.get('page') || '1');
    if (pageNumber === 2) return route.fulfill({ status: 500, body: 'temporary failure' });
    return route.fulfill({
      status: 200,
      body: JSON.stringify(mockSearchPage({ total: 450, page: pageNumber, pageSize: 200 })),
    });
  });

  await bootApp(page, '/index.html?api=1&scope=jur&q=disability');
  await expect(page.locator('.result').first()).toBeVisible({ timeout: 10_000 });
  await page.locator('#export-menu').evaluate((el: Element) =>
    (el as HTMLDetailsElement).open = true
  );
  const dialogMessage = new Promise<string>((resolve) => {
    page.once('dialog', async (dialog) => {
      resolve(dialog.message());
      await dialog.dismiss();
    });
  });
  await page.locator('#export-menu [data-format="json"]').click();
  expect(await dialogMessage).toMatch(/Export failed.*API \/api\/search.*500/i);
  await expect(page.locator('#export-menu [data-format="json"]')).toBeEnabled();
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

test('A9. artRefResolution · v19.67-75 rules — OP anaphora, compound lists, domestic guards, soft law, Geneva', async ({ page }) => {
  /* Distilled from the 2026-07-27 verification-agent audit
     (artref-audit/VERDICT-SUMMARY.md). Each hit is one rule:
       op-lead   — "under the Optional Protocol (article 2)" in a CCPR case
                   → ICCPR-OP1 (12 of the agent's 16 relink verdicts were
                   exactly this admissibility boilerplate).
       letters   — "articles 2 (c), 3, 5 (a) and 15 of the <CEDAW title>"
                   → all four numbers link CEDAW: letter qualifiers no longer
                   cut the list short, and a full-name TAIL now resolves
                   instead of merely plain-texting.
       constit   — "in accordance with the Constitution (art. 41)" → plain
                   text (national constitutions were 96 of 108 verified
                   wrong links).
       neg-law   — "equality before the law (art. 26)" → still a HOME link;
                   the domestic guard is case-sensitive and word-limited
                   precisely so this stays clickable. */
  const CASES = [
    { id: 'op-lead', committee: 'CCPR',
      text: 'The communication is inadmissible under the Optional Protocol (article 2) for lack of substantiation.',
      expect: [['2', 'ICCPR-OP1']] },
    { id: 'letters', committee: 'CCPR',
      text: 'As guaranteed by articles 2 (c), 3, 5 (a) and 15 of the Convention on the Elimination of All Forms of Discrimination Against Women, women enjoy equality.',
      expect: [['2', 'CEDAW'], ['3', 'CEDAW'], ['5', 'CEDAW'], ['15', 'CEDAW']] },
    { id: 'constit', committee: 'CCPR',
      text: 'In accordance with the Constitution (art. 41), everyone may acquire property.',
      expect: [] },
    { id: 'neg-law', committee: 'CCPR',
      text: 'Equality before the law (art. 26) is guaranteed to all persons.',
      expect: [['26', 'ICCPR']] },
    /* v19.68 — qualifier text between the number and its instrument. */
    { id: 'bridge-op', committee: 'CCPR',
      text: 'The claim is inadmissible under article 5, paragraph 2 (a), of the Optional Protocol as submitted.',
      expect: [['5', 'ICCPR-OP1']] },
    { id: 'bridge-home', committee: 'CCPR',
      text: 'The State party violated article 19, paragraph 3, of the Covenant in this matter.',
      expect: [['19', 'ICCPR']] },
    /* v19.68 — instrument named a little before the parenthetical, and the
       negative control that keeps the rule honest: " to " starts a new
       clause, so the Act does NOT own the (art. 13) that follows it. */
    { id: 'lead-near', committee: 'CCPR',
      text: 'The Korean Constitution contains a provision (article 37, paragraph 2) stipulating that freedoms may be restricted.',
      expect: [] },
    { id: 'lead-near-neg', committee: 'CRPD',
      text: 'he has not made a complaint under section 24 of the Anti-Discrimination Act to request special accommodation (art. 13) and never challenged it.',
      expect: [['13', 'CRPD']] },
    /* v19.69 — series propagation. The real CRPD 34/2015 sentence: the
       Constitution is named once and three later parentheticals inherit it.
       Before this rule they popped CRPD 49/23/10, which exist and mean
       "Accessible format" / "Respect for home and the family" / "Right to
       life" — confidently wrong article text. */
    { id: 'series', committee: 'CRPD',
      text: 'it violated the fundamental rights to work and to vocational rehabilitation (arts. 35 and 40 of the Constitution), the inclusion of persons with disabilities (art. 49), access to and retention of public employment (art. 23) and respect for human dignity (art. 10).',
      expect: [] },
    /* Three bounds that keep the anchor from over-reaching. */
    { id: 'series-break', committee: 'CCPR',
      text: 'the detention order (art. 12 of the Criminal Code) was upheld, and the Committee recalls that the Covenant guarantees fair trial (art. 14).',
      expect: [['14', 'ICCPR']] },
    { id: 'series-sent', committee: 'CCPR',
      text: 'The appeal cited the ordinance (art. 7 of the Decree). The author further invoked the right to liberty (art. 9).',
      expect: [['9', 'ICCPR']] },
    /* v19.70 — soft-law units. The negatives matter more than the positives:
       7,584 of the corpus's 8,562 "rule/principle N" occurrences are the
       Committee's own rules of procedure, and none may ever link. */
    { id: 'sl-rule', committee: 'CAT',
      text: 'The Committee recalls that, under rule 44 of the Nelson Mandela Rules, prolonged solitary confinement is prohibited.',
      expect: [['44', 'Mandela Rules']] },
    { id: 'sl-neg-rop', committee: 'CAT',
      text: 'The Committee, pursuant to rule 108, paragraph 1, of its rules of procedure, requested interim measures.',
      expect: [] },
    { id: 'sl-neg-unit', committee: 'CAT',
      text: 'principle 44 of the Nelson Mandela Rules was invoked by counsel.',
      expect: [] },
    { id: 'series-home', committee: 'CRC',
      text: 'the general measures of implementation (arts. 4 and 42 of the Convention) and the best interests principle (art. 3) apply.',
      expect: [['4', 'CRC'], ['42', 'CRC'], ['3', 'CRC']] },
    /* v19.71 — the Geneva family. Common articles 1-3 are IDENTICAL across
       GC I-IV, so the plural citation is NOT ambiguous for them and one
       canonical entry is correct. Before this, "common article 3 of the four
       Geneva Conventions" popped CAT article 3 — non-refoulement — for what
       the text says is humane treatment in non-international conflict. */
    { id: 'gc-common', committee: 'CAT',
      text: 'evidence of its violation of common article 3 of the four Geneva Conventions of 12 August 1949 was presented.',
      expect: [['3', 'Geneva Conventions']] },
    /* Past article 3 the four Conventions diverge, so the entry holds no
       such unit and the phantom guard must render plain text rather than a
       button whose popover never opens. */
    { id: 'gc-phantom', committee: 'CCPR',
      text: 'the deportation prohibition in article 47 of the Geneva Conventions is absolute.',
      expect: [] },
    /* v19.72 — a specific Convention now resolves too. This case expected
       plain text one commit ago, when only the common-articles entry
       existed; the change of expectation IS the feature. */
    /* v19.73 — REGRESSION GUARD. "…of the Covenant." at the end of a sentence:
       the tail matcher's character class keeps "." for abbreviations and so
       captured "Covenant.", which matched no home term and no treaty name, so
       the commonest citation form in the corpus rendered as plain text. Every
       earlier case here happened to put a word after "Covenant" and missed it;
       a blind random-sample audit found it. Keep BOTH forms. */
    { id: 'home-tail-eos', committee: 'CCPR',
      text: 'The seizure violated article 19 of the Covenant.',
      expect: [['19', 'ICCPR']] },
    { id: 'home-tail-bridge-eos', committee: 'CCPR',
      text: 'The author invokes article 19, paragraph 2, of the Covenant.',
      expect: [['19', 'ICCPR']] },
    /* v19.74 — Special Procedures own no treaty. That used to abort
       annotation for the whole paragraph: 11,310 SP paragraphs carry article
       references and none linked, not even when the instrument was spelled
       out. A missing home treaty must switch off only the FALLBACK. */
    { id: 'sp-named', committee: 'SR Torture',
      text: 'The Special Rapporteur recalls article 75 of Additional Protocol I in this context.',
      expect: [['75', 'AP I']] },
    /* …and an unnamed reference must stay plain: "the Covenant" in an SP
       report does not say which one, and a coin flip between ICCPR and
       ICESCR is worse than no link. */
    { id: 'sp-bare', committee: 'SR Freedom of Expression',
      text: 'The restriction must satisfy the three-part test in article 19, paragraph 3, of the Covenant.',
      expect: [] },
    /* v19.75 — the committee's OWN treaty named in full. tailTreatyAbbr is
       null (it equals home) and the external-instrument guard then read the
       first word, "International", as a foreign instrument. The most explicit
       home citation there is was the one shape that rendered plain. */
    { id: 'home-fullname', committee: 'CCPR',
      text: 'the facts disclose violations of articles 7 and 10, paragraph 1, of the International Covenant on Civil and Political Rights.',
      expect: [['7', 'ICCPR'], ['10', 'ICCPR']] },
    /* v19.75 — backward propagation: a list can put its numbers BEFORE the
       instrument governing them. Only list glue may sit in between, so the
       two negatives below must NOT propagate. */
    { id: 'backward', committee: 'CCPR',
      text: 'a violation of articles 6, 7 and 9, read together with article 2 of the Convention on the Rights of the Child.',
      expect: [['6', 'CRC'], ['7', 'CRC'], ['9', 'CRC'], ['2', 'CRC']] },
    { id: 'backward-neg-verb', committee: 'CCPR',
      text: 'The Committee examined articles 9 and 14 before turning to the obligations of the Convention on the Rights of the Child.',
      expect: [['9', 'ICCPR'], ['14', 'ICCPR']] },
    { id: 'gc-specific', committee: 'CAT',
      text: 'a violation of article 12 of the Third Geneva Convention was alleged.',
      expect: [['12', 'GC III']] },
    { id: 'ap-protocol', committee: 'CCPR',
      text: 'the fundamental guarantees in article 75 of Additional Protocol I bind all parties.',
      expect: [['75', 'AP I']] },
  ];
  /* Every article a case references must exist in the mock: since v19.71 the
     renderer refuses to button a unit the instrument does not hold (the
     phantom-article guard), so a thin mock silently disables half the suite. */
  const arts = (...nums) => nums.map((n) => ({
    number: String(n), paragraphs: [{ num: null, text: `Text of unit ${n}.` }],
  }));
  let CURRENT = CASES;
  const BUNDLE = {
    /* CAT must be present: annotateTreatyText resolves the committee's own
       treaty first and returns early when the bundle does not hold it, which
       would silently disable the soft-law pass too. */
    cat: { abbr: 'CAT', name_full: 'Convention against Torture and Other Cruel, Inhuman or Degrading Treatment or Punishment',
      term: 'Convention', committee_codes: ['CAT'], articles: arts(3) },
    iccpr: { abbr: 'ICCPR', name_full: 'International Covenant on Civil and Political Rights',
      term: 'Covenant', committee_codes: ['CCPR'], articles: arts(6, 7, 9, 10, 14, 19, 26) },
    'iccpr-op1': { abbr: 'ICCPR-OP1',
      name_full: 'Optional Protocol to the International Covenant on Civil and Political Rights',
      term: 'Optional Protocol', committee_codes: ['CCPR'], articles: arts(1, 2, 5) },
    'iccpr-op2': { abbr: 'ICCPR-OP2',
      name_full: 'Second Optional Protocol to the International Covenant on Civil and Political Rights, aiming at the abolition of the death penalty',
      term: 'Optional Protocol', committee_codes: ['CCPR'], articles: arts(1) },
    cedaw: { abbr: 'CEDAW', name_full: 'Convention on the Elimination of All Forms of Discrimination Against Women',
      term: 'Convention', committee_codes: ['CEDAW'], articles: arts(2, 3, 5, 15) },
    crpd: { abbr: 'CRPD', name_full: 'Convention on the Rights of Persons with Disabilities',
      term: 'Convention', committee_codes: ['CRPD'], articles: arts(13) },
    crc: { abbr: 'CRC', name_full: 'Convention on the Rights of the Child',
      term: 'Convention', committee_codes: ['CRC'], articles: arts(2, 3, 4, 6, 7, 9, 42) },
    icescr: { abbr: 'ICESCR', name_full: 'International Covenant on Economic, Social and Cultural Rights',
      term: 'Covenant', committee_codes: ['CESCR'], articles: arts(2, 3, 26) },
    'mandela rules': { abbr: 'Mandela Rules',
      name_full: 'United Nations Standard Minimum Rules for the Treatment of Prisoners',
      alt_names: ['Nelson Mandela Rules'], term: 'United', unit_term: 'rule',
      committee_codes: [], articles: arts(44) },
    /* Common articles 1-3 only — identical across GC I-IV. Article 47 is
       deliberately absent so the phantom guard has something to catch. */
    'gc iii': { abbr: 'GC III', name_full: 'Geneva Convention relative to the Treatment of Prisoners of War',
      alt_names: ['Third Geneva Convention', 'Geneva Convention III'],
      term: 'Geneva', committee_codes: [], articles: arts(12, 13) },
    'ap i': { abbr: 'AP I',
      name_full: 'Protocol Additional to the Geneva Conventions of 12 August 1949, and relating to the Protection of Victims of International Armed Conflicts (Protocol I)',
      alt_names: ['Additional Protocol I'], term: 'Protocol', committee_codes: [], articles: arts(75) },
    'geneva conventions': { abbr: 'Geneva Conventions',
      name_full: 'Geneva Conventions of 12 August 1949 (common articles)',
      alt_names: ['four Geneva Conventions', 'Geneva Conventions'],
      term: 'Geneva', committee_codes: [], articles: arts(1, 2, 3) },
  };
  await page.route('**/unhrdb-api/api/stats', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_STATS) })
  );
  await page.route('**/ask-api/api/treaties**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(BUNDLE) })
  );
  await page.route('**/unhrdb-api/api/search**', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({
        query: 'artref rules', scope: 'all', total: CURRENT.length,
        breakdown: { gc: CURRENT.length, jur: 0, sp: 0 }, page: 1, page_size: 50,
        hits: CURRENT.map((c, i) => ({
          rowid: i + 1, para_id: `a9-${c.id}`, doc_id: `a9-doc-${c.id}`, idx: i, n: String(i),
          section: null, text: c.text, type: 'gc', treaty: c.committee, committee: c.committee,
          mandate: null, country: null, year: 2020, adoption_date: '2020-01-01',
          signature: `A9/${c.id}`, outcome: null, name: `Case ${c.id}`, name_short: c.id,
          snippet: c.text.slice(0, 80), score: -10 - i,
        })),
      }),
    })
  );
  /* The result list appends 20 rows per page and the reader has no loader to
     call, so a suite larger than one page silently stops asserting on its
     tail — which is exactly how a stale expectation hid here once. Drive the
     cases in chunks that always fit. */
  for (let start = 0; start < CASES.length; start += 12) {
    const chunk = CASES.slice(start, start + 12);
    CURRENT = chunk;
    await page.goto(`/index.html?api=1&scope=all&q=artref%20rules&n=${start}`, { waitUntil: 'commit' });
    await expect
      .poll(async () => page.locator('#result-list li').count(), { timeout: 30000 })
      .toBeGreaterThanOrEqual(chunk.length);
    await expect
      .poll(async () => page.locator('#result-list .treaty-article-ref').count(), { timeout: 15000 })
      .toBeGreaterThan(0);
    for (const c of chunk) {
      const li = page.locator('#result-list li', { hasText: c.text.slice(0, 40) });
      const got = await li.locator('.treaty-article-ref').evaluateAll((els) =>
        els.map((b) => [b.getAttribute('data-article'), b.getAttribute('data-treaty')])
      );
      expect(got, `case ${c.id}`).toEqual(c.expect);
    }
  }
});
