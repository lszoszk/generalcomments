import { expect, test } from '@playwright/test';
import { bootApp, resetWorkspace, typeQuery } from './_helpers';

test.beforeEach(async ({ page }) => {
  await resetWorkspace(page);
});

test('UX1. gcBootDoesNotFetchHeavyJurCatalog · GC boot avoids jur/documents.json', async ({ page }) => {
  const seen: string[] = [];
  page.on('request', req => {
    const url = req.url();
    if (/\/jur\/documents(?:\.json|\?)/.test(url)) seen.push(url);
  });

  const t0 = Date.now();
  await bootApp(page, '/index.html?scope=gc&q=disability');
  const bootMs = Date.now() - t0;

  expect(bootMs).toBeLessThan(8_000);
  expect(seen, seen.join('\n')).toEqual([]);
  await expect(page.locator('.result').first()).toBeVisible();
});

test('UX2. jurApiSearchDoesNotFetchShards · API route stays server-backed', async ({ page }) => {
  const shardRequests: string[] = [];
  page.on('request', req => {
    const url = req.url();
    if (/\/jur\/shards\//.test(url)) shardRequests.push(url);
  });
  await page.route('**/unhrdb-api/api/stats', route =>
    route.fulfill({ status: 200, body: JSON.stringify({ version: 'mock', totalParagraphs: 132711, byType: {} }) })
  );
  await page.route('**/unhrdb-api/api/search**', route =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({
        query: 'non-refoulement',
        ftsExpr: '"non-refoulement"',
        scope: 'jur',
        total: 1,
        page: 1,
        pageSize: 200,
        tookMs: 42,
        breakdown: { jur: 1 },
        hits: [{
          rowid: 1,
          para_id: 'ccpr-c-142-d-2749-2016-0039',
          doc_id: 'ccpr-c-142-d-2749-2016',
          idx: 39,
          n: '8.4',
          section: 'Committee consideration',
          text: 'The Committee recalls the principle of non-refoulement.',
          type: 'jur',
          treaty: 'CCPR',
          committee: null,
          mandate: null,
          country: 'Australia',
          year: 2016,
          adoption_date: '2024',
          signature: 'CCPR/C/142/D/2749/2016',
          outcome: 'violation_found',
          name: 'English Title',
          name_short: 'English Title',
          snippet: 'The Committee recalls the principle of <mark>non-refoulement</mark>.',
          score: -1,
        }],
        alsoTry: [],
      }),
    })
  );

  await bootApp(page, '/index.html?api=1&scope=jur&q=non-refoulement');
  await expect(page.locator('.result').first()).toBeVisible();
  await expect(page.locator('.result-doc').first()).not.toContainText('English Title');
  expect(shardRequests, shardRequests.join('\n')).toEqual([]);
});

test('UX3. complexSearchFlows · GC SP and ALL searches stay useful', async ({ page }) => {
  await bootApp(page, '/index.html?scope=gc');

  for (const q of [
    'trafficking AND children NOT (sexual)',
    '"reasonable accommodation" NOT children',
    '(women OR girls) AND violence',
    'child* AND traffic*',
  ]) {
    await typeQuery(page, q);
    await expect(page.locator('.result').first(), q).toBeVisible();
    await expect(page.locator('#result-count'), q).toContainText(/¶/);
  }

  await page.locator('.scope-opt[data-scope="sp"]').click();
  await typeQuery(page, '"will and preferences"');
  await expect(page.locator('.result').first()).toBeVisible();
  await expect(page.locator('#result-count')).toContainText(/¶/);

  await typeQuery(page, 'will and preferences');
  await expect(page.locator('.result').first()).toBeVisible();

  await page.route('**/unhrdb-api/api/search**', route =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({
        query: 'trafficking AND children NOT (sexual)',
        ftsExpr: '"trafficking" AND "children" NOT ("sexual")',
        scope: 'all',
        total: 1,
        page: 1,
        pageSize: 200,
        tookMs: 25,
        breakdown: { gc: 1, jur: 0, sp: 0 },
        hits: [{
          rowid: 1,
          para_id: 'crc-gc-2003-6-0052',
          doc_id: 'crc-gc-2003-6',
          idx: 52,
          n: '52',
          section: null,
          text: 'Trafficking in children is a threat to the fulfilment of their rights.',
          type: 'gc',
          treaty: null,
          committee: 'CRC',
          mandate: null,
          country: null,
          year: 2003,
          adoption_date: '2003',
          signature: 'CRC/GC/2003/6',
          outcome: null,
          name: 'GC6: Treatment of unaccompanied and separated children outside their country of origin',
          name_short: 'GC6: Treatment of unaccompanied and separated children outside their country of origin',
          snippet: '<mark>Trafficking</mark> in <mark>children</mark> is a threat.',
          score: -1,
        }],
        alsoTry: [],
      }),
    })
  );
  await page.locator('.scope-opt[data-scope="all"]').click();
  await typeQuery(page, 'trafficking AND children NOT (sexual)');
  await expect(page.locator('.result').first()).toBeVisible();
});

test('UX4. localJurFallbackShowsProgress · api=0 remains explicit and bounded', async ({ page }) => {
  const shardRequests: string[] = [];
  page.on('request', req => {
    const url = req.url();
    if (/\/jur\/shards\//.test(url)) shardRequests.push(url);
  });
  const t0 = Date.now();
  await bootApp(page, '/index.html?api=0&scope=jur&q=non-refoulement');
  await expect(page.locator('.result').first()).toBeVisible({ timeout: 30_000 });
  const elapsed = Date.now() - t0;
  expect(elapsed).toBeLessThan(20_000);
  expect(shardRequests.length).toBeGreaterThan(0);
  await expect(page.locator('#api-badge')).toContainText(/offline/);
});

test('UX5. jurLiteCatalogInvariant · no public English Title placeholders', async ({ request }) => {
  const res = await request.get('/jur/documents-lite.json');
  expect(res.ok()).toBeTruthy();
  const docs = await res.json();
  const bad = docs.filter((d: any) =>
    ['name', 'nameShort', 'title', 'caseName'].some(k => String(d[k] || '').trim() === 'English Title')
  );
  expect(bad.map((d: any) => d.symbol || d.docId)).toEqual([]);
});

test('UX6. mobileSmoke · search scope result dossier flow fits narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await bootApp(page, '/index.html?scope=gc');
  await typeQuery(page, 'disability');
  const first = page.locator('.result').first();
  await expect(first).toBeVisible();
  await first.click();
  await expect(page.locator('.dossier-title')).toBeVisible();
  await page.locator('.scope-opt[data-scope="sp"]').click();
  await typeQuery(page, '"will and preferences"');
  await expect(page.locator('.result').first()).toBeVisible();
});
