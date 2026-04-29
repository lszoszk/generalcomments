import { expect, test } from '@playwright/test';

/**
 * Contract tests against the LIVE unhrdb-api on the VM.
 * These do hit the production-equivalent endpoint at
 *   https://150.254.115.204/unhrdb-api
 *
 * Run with:  npm run test:contracts
 */

test('C1. /health returns ok', async ({ request }) => {
  const r = await request.get('/health');
  expect(r.ok()).toBe(true);
  const body = await r.json();
  expect(body.status).toBe('ok');
  expect(body.paragraphs).toBeGreaterThan(100_000);
  expect(r.headers()['cache-control']).toMatch(/no-cache/);
});

test('C2. /api/stats has gc/jur/sp counts', async ({ request }) => {
  const r = await request.get('/api/stats');
  expect(r.ok()).toBe(true);
  const body = await r.json();
  expect(body.byType.gc.documents).toBeGreaterThan(150);
  expect(body.byType.jur.documents).toBeGreaterThan(2000);
  expect(body.byType.sp.documents).toBeGreaterThan(50);
  expect(r.headers()['cache-control']).toMatch(/max-age=300/);
});

test('C3. /api/facets?scope=jur returns treaties + countries', async ({ request }) => {
  const r = await request.get('/api/facets?scope=jur');
  expect(r.ok()).toBe(true);
  const body = await r.json();
  expect(body.treaties.length).toBeGreaterThanOrEqual(1);
  expect(body.countries.length).toBeGreaterThan(50);
});

test('C4. /api/search keyword + snippet + bm25 score', async ({ request }) => {
  const r = await request.get('/api/search?q=reasonable+accommodation&page_size=3');
  expect(r.ok()).toBe(true);
  const body = await r.json();
  expect(body.total).toBeGreaterThan(100);
  expect(body.tookMs).toBeGreaterThan(0);
  expect(body.hits[0].snippet).toContain('<mark>');
  expect(body.hits[0].score).toBeLessThan(0);    // bm25 is negative-valued
});

test('C5. /api/search boolean grouping', async ({ request }) => {
  const r = await request.get(
    '/api/search?q=' + encodeURIComponent('trafficking AND children NOT (sexual)') + '&page_size=2'
  );
  const body = await r.json();
  expect(body.ftsExpr).toContain('AND');
  expect(body.ftsExpr).toContain('NOT (');           // paren grouping preserved
  expect(body.total).toBeGreaterThan(0);
});

test('C6. /api/search body= union (v19.4)', async ({ request }) => {
  // body=CRPD must hit BOTH the GC committee column AND the JUR treaty
  // column. Lumping into committees+treaties+mandates would zero out.
  const r = await request.get('/api/search?q=disability&body=CRPD&page_size=2');
  const body = await r.json();
  expect(body.breakdown.gc).toBeGreaterThan(0);
  expect(body.breakdown.jur).toBeGreaterThan(0);
});

test('C7. /api/search alsoTry on 0-result phrase', async ({ request }) => {
  const r = await request.get('/api/search?q=' + encodeURIComponent('"AI bias"'));
  const body = await r.json();
  expect(body.total).toBe(0);
  expect(body.alsoTry).toContain('algorithmic discrimination');
});

test('C8. /api/document/<id> returns full body', async ({ request }) => {
  const r = await request.get('/api/document/crpd-c-gc-6');
  expect(r.ok()).toBe(true);
  const body = await r.json();
  expect(body.document.doc_id).toBe('crpd-c-gc-6');
  expect(body.paragraphs.length).toBeGreaterThan(60);
});

test('C9. /api/document/unknown returns 404', async ({ request }) => {
  const r = await request.get('/api/document/foo-bar-baz');
  expect(r.status()).toBe(404);
});

test('C10. CORS allow-origin honours GH-Pages', async ({ request }) => {
  const r = await request.get('/api/stats');
  expect(r.headers()['access-control-allow-origin']).toBe('https://lszoszk.github.io');
});

test('C11. /api/feedback validates (≥4 chars)', async ({ request }) => {
  const r = await request.post('/api/feedback', {
    data: { kind: 'bug', message: 'no' },         // too short
  });
  expect(r.status()).toBe(422);
});

test('C12. perf · keyword search responds < 1500 ms cold', async ({ request }) => {
  const t0 = Date.now();
  const r = await request.get('/api/search?q=violation&page_size=5');
  const wall = Date.now() - t0;
  expect(r.ok()).toBe(true);
  expect(wall).toBeLessThan(1500);
});
