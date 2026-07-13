import { expect, test } from '@playwright/test';

/**
 * Contract tests against the LIVE unhrdb-api on the VM.
 * These do hit the production-equivalent endpoint at
 *   https://150.254.115.204/unhrdb-api
 *
 * Run with:  npm run test:contracts
 */

test('C1. /health returns ok', async ({ request }) => {
  const r = await request.get('health');
  expect(r.ok()).toBe(true);
  const body = await r.json();
  expect(body.status).toBe('ok');
  expect(body.paragraphs).toBeGreaterThan(100_000);
  expect(r.headers()['cache-control']).toMatch(/no-cache/);
});

test('C2. /api/stats has gc/jur/sp counts', async ({ request }) => {
  const r = await request.get('api/stats');
  expect(r.ok()).toBe(true);
  const body = await r.json();
  expect(body.byType.gc.documents).toBeGreaterThan(150);
  expect(body.byType.jur.documents).toBeGreaterThan(2000);
  expect(body.byType.sp.documents).toBeGreaterThan(50);
  expect(r.headers()['cache-control']).toMatch(/max-age=300/);
});

test('C3. /api/facets?scope=jur returns treaties + countries', async ({ request }) => {
  const r = await request.get('api/facets?scope=jur');
  expect(r.ok()).toBe(true);
  const body = await r.json();
  expect(body.treaties.length).toBeGreaterThanOrEqual(1);
  expect(body.countries.length).toBeGreaterThan(50);
});

test('C4. /api/search keyword + snippet + bm25 score', async ({ request }) => {
  const r = await request.get('api/search?q=reasonable+accommodation&page_size=3');
  expect(r.ok()).toBe(true);
  const body = await r.json();
  expect(body.total).toBeGreaterThan(100);
  expect(body.tookMs).toBeGreaterThan(0);
  expect(body.hits[0].snippet).toContain('<mark>');
  expect(body.hits[0].score).toBeLessThan(0);    // bm25 is negative-valued
});

test('C5. /api/search boolean grouping', async ({ request }) => {
  const r = await request.get(
    'api/search?q=' + encodeURIComponent('trafficking AND children NOT (sexual)') + '&page_size=2'
  );
  const body = await r.json();
  expect(body.ftsExpr).toContain('AND');
  expect(body.ftsExpr).toContain('NOT (');           // paren grouping preserved
  expect(body.total).toBeGreaterThan(0);
});

test('C5b. /api/search minus alias is equivalent to NOT', async ({ request }) => {
  const positive = 'trafficking AND children';
  const [notResponse, minusResponse] = await Promise.all([
    request.get('api/search?q=' + encodeURIComponent(`${positive} NOT sexual`) + '&page_size=1'),
    request.get('api/search?q=' + encodeURIComponent(`${positive} -sexual`) + '&page_size=1'),
  ]);
  expect(notResponse.ok()).toBeTruthy();
  expect(minusResponse.ok()).toBeTruthy();
  const notBody = await notResponse.json();
  const minusBody = await minusResponse.json();
  expect(minusBody.ftsExpr).toBe(notBody.ftsExpr);
  expect(minusBody.total).toBe(notBody.total);
});

test('C5c. /api/search rejects negative-only queries without a server error', async ({ request }) => {
  const response = await request.get('api/search?q=' + encodeURIComponent('NOT surveillance'));
  expect(response.status()).toBe(422);
  const body = await response.json();
  expect(body.detail.code).toBe('invalid_query_syntax');
  expect(body.detail.message).toContain('positive term');
});

test('C6. /api/search body= union (v19.4)', async ({ request }) => {
  // body=CRPD must hit BOTH the GC committee column AND the JUR treaty
  // column. Lumping into committees+treaties+mandates would zero out.
  const r = await request.get('api/search?q=disability&body=CRPD&page_size=2');
  const body = await r.json();
  expect(body.breakdown.gc).toBeGreaterThan(0);
  expect(body.breakdown.jur).toBeGreaterThan(0);
});

test('C7. /api/search alsoTry on 0-result phrase', async ({ request }) => {
  const r = await request.get('api/search?q=' + encodeURIComponent('"gig worker"'));
  const body = await r.json();
  expect(body.total).toBe(0);
  expect(body.alsoTry).toContain('informal economy');
});

test('C8. /api/document/<id> returns full body', async ({ request }) => {
  const r = await request.get('api/document/crpd-c-gc-6');
  expect(r.ok()).toBe(true);
  const body = await r.json();
  expect(body.document.doc_id).toBe('crpd-c-gc-6');
  expect(body.paragraphs.length).toBeGreaterThan(60);
});

test('C9. /api/document/unknown returns 404', async ({ request }) => {
  const r = await request.get('api/document/foo-bar-baz');
  expect(r.status()).toBe(404);
});

test('C10. CORS allow-origin honours GH-Pages', async ({ request }) => {
  const r = await request.get('api/stats');
  expect(r.headers()['access-control-allow-origin']).toBe('https://lszoszk.github.io');
});

test('C11. /api/feedback validates (≥4 chars)', async ({ request }) => {
  const r = await request.post('api/feedback', {
    data: { kind: 'bug', message: 'no' },         // too short
  });
  expect(r.status()).toBe(422);
});

test('C12. perf · keyword search responds < 1500 ms cold', async ({ request }) => {
  const t0 = Date.now();
  const r = await request.get('api/search?q=violation&page_size=5');
  const wall = Date.now() - t0;
  expect(r.ok()).toBe(true);
  expect(wall).toBeLessThan(1500);
});

test('C13. perf · every advertised operator stays within the indexed-search budget', async ({ request }) => {
  const queries = [
    '"hold opinions"',
    'opinion hold',
    'opinion AND hold',
    'surveillance OR interception',
    'trafficking AND children NOT sexual',
    '(women OR girls) AND violence',
    'discriminat*',
  ];
  for (const query of queries) {
    const response = await request.get(
      'api/search?q=' + encodeURIComponent(query) + '&page_size=1'
    );
    expect(response.ok(), query).toBeTruthy();
    const body = await response.json();
    expect(body.total, query).toBeGreaterThan(0);
    expect(body.tookMs, query).toBeLessThan(1200);
  }
});

test('C14. bare words are exact; variants require an explicit wildcard', async ({ request }) => {
  const [rootResponse, exactResponse, pluralResponse, prefixResponse] = await Promise.all([
    request.get('api/search?q=reason&scope=sp&page_size=20'),
    request.get('api/search?q=reasoning&scope=sp&page_size=20'),
    request.get('api/search?q=reasons&scope=sp&page_size=20'),
    request.get('api/search?q=reason*&scope=sp&page_size=1'),
  ]);
  expect(rootResponse.ok()).toBeTruthy();
  expect(exactResponse.ok()).toBeTruthy();
  expect(pluralResponse.ok()).toBeTruthy();
  expect(prefixResponse.ok()).toBeTruthy();

  const root = await rootResponse.json();
  const exact = await exactResponse.json();
  const plural = await pluralResponse.json();
  const prefix = await prefixResponse.json();
  expect(root.ftsExpr).toBe('"reason"');
  expect(exact.ftsExpr).toBe('"reasoning"');
  expect(plural.ftsExpr).toBe('"reasons"');
  expect(root.total).not.toBe(exact.total);
  expect(root.total).not.toBe(plural.total);
  expect(exact.total).not.toBe(plural.total);
  expect(prefix.total).toBeGreaterThan(root.total);
  expect(prefix.total).toBeGreaterThan(exact.total);
  expect(prefix.total).toBeGreaterThan(plural.total);
  for (const hit of root.hits) {
    expect(hit.text).toMatch(/\breason\b/i);
  }
  for (const hit of exact.hits) {
    expect(hit.text).toMatch(/\breasoning\b/i);
  }
});
