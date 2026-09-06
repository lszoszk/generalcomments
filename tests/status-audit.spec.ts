import { expect, test } from '@playwright/test';

test('S1. statusGraph · audited supersessions are complete and reciprocal', async ({ request }) => {
  const response = await request.get('/documents.json');
  expect(response.ok()).toBeTruthy();
  const documents = await response.json();
  const byId = new Map(documents.map((doc: any) => [doc.docId, doc]));

  const facetsResponse = await request.get('/facets.json');
  expect(facetsResponse.ok()).toBeTruthy();
  const facets = await facetsResponse.json();
  // `final` grows with every ingestion (status-less SP reports count as
  // final), so derive it from the catalogue instead of pinning a number
  // that has to be bumped in every corpus commit.
  const expectedFinal = documents.filter((doc: any) => (doc.status ?? 'final') === 'final').length;
  expect(facets.statuses).toEqual([
    { value: 'final', count: expectedFinal },
    { value: 'superseded', count: 13 },
    { value: 'revised', count: 2 },
    { value: 'corrected', count: 1 },
  ]);

  const superseded = documents.filter((doc: any) => doc.type === 'gc' && doc.status === 'superseded');
  expect(superseded).toHaveLength(13);
  for (const doc of superseded) {
    expect(doc.supersededBy, `${doc.docId} needs a replacement`).toBeTruthy();
    expect(doc.statusSource, `${doc.docId} needs official evidence`).toMatch(/^https:\/\/(?:[^/]+\.)?(?:ohchr|un)\.org\//);
    expect(doc.statusVerifiedAt).toBe('2026-07-13');
  }

  // GC1 and GC2 share a report/page signature; only GC2 is superseded.
  expect(byId.get('annotated-ccpr-gc1-reporting-obligation')).toMatchObject({ status: 'final' });
  expect(byId.get('annotated-ccpr-gc2-reporting-guidelines')).toMatchObject({
    status: 'superseded',
    supersededBy: 'CCPR/C/66/GUI/Rev.2',
  });

  expect(byId.get('ccpr-c-gc-36')).toMatchObject({
    status: 'final',
    supersedes: [
      'HRI/GEN/1/Rev.9 (Vol. I) p.176',
      'HRI/GEN/1/Rev.9 (Vol. I) p. 188',
    ],
  });
});

test('S2. nuancedRelationships · updates, addenda, revisions, and corrections stay distinct', async ({ request }) => {
  const response = await request.get('/documents.json');
  const documents = await response.json();
  const byId = new Map(documents.map((doc: any) => [doc.docId, doc]));

  expect(byId.get('annotated-cedaw-gr19-violence')).toMatchObject({
    status: 'final',
    updatedBy: 'CEDAW/C/GC/35',
  });
  expect(byId.get('cedaw-c-gc-30')).toMatchObject({
    status: 'final',
    supplementedBy: 'CEDAW/C/GC/30/Add.1',
  });
  expect(byId.get('crc-c-gc-7-rev-1')).toMatchObject({ status: 'revised' });
  expect(byId.get('crc-c-gc-9-corr-1')).toMatchObject({ status: 'corrected' });
});

test('S3. citationGraph · the built graph is consistent with the catalogue', async ({ request }) => {
  const index = await (await request.get('/citations/index.json')).json();
  const graph = await (await request.get('/citations/graph.json')).json();
  const documents = await (await request.get('/documents.json')).json();
  const jur = await (await request.get('/jur/documents-lite.json')).json();
  const ids = new Set([...documents, ...jur].map((d: any) => d.docId));
  expect(graph.counts.edges).toBe(graph.edges.length);
  expect(graph.counts.edges).toBeGreaterThan(20_000);
  for (const e of graph.edges.slice(0, 500)) {
    expect(ids.has(e.from), e.from).toBeTruthy();
    expect(ids.has(e.to), e.to).toBeTruthy();
    expect(e.from).not.toBe(e.to);
  }
  // The most-cited general comment of the Human Rights Committee.
  const gc31 = index.docs['ccpr-c-21-rev-1-add-13'];
  expect(gc31.citedBy.length).toBeGreaterThan(300);
  expect(gc31.citedBy[0][1]).toBeGreaterThanOrEqual(gc31.citedBy[1][1]);
});

test('S4. feedsChangelogRelated · the current-awareness and related-paragraph artefacts are built', async ({ request }) => {
  const all = await request.get('/feeds/all.xml');
  expect(all.ok()).toBeTruthy();
  const xml = await all.text();
  expect(xml).toContain('<feed xmlns="http://www.w3.org/2005/Atom">');
  expect((xml.match(/<entry>/g) || []).length).toBeGreaterThan(50);
  const index = await (await request.get('/feeds/index.json')).json();
  expect(index.feeds.length).toBeGreaterThan(40);
  expect(index.feeds.map((f: any) => f.id)).toEqual(expect.arrayContaining(['all', 'gc', 'jur', 'sp', 'body-ccpr']));
  const changelog = await request.get('/changelog.html');
  expect(changelog.ok()).toBeTruthy();
  expect(await changelog.text()).toContain('What is new');
  const related = await (await request.get('/related/gc.json')).json();
  expect(related.scope).toBe('gc');
  expect(Object.keys(related.related).length).toBeGreaterThan(7000);
  for (const [id, rows] of Object.entries(related.related).slice(0, 200)) {
    const doc = id.replace(/-\d{4}$/, '');
    for (const [other, score] of rows as any[]) {
      expect(other.replace(/-\d{4}$/, '')).not.toBe(doc);
      expect(score).toBeGreaterThanOrEqual(0.55);
    }
  }
});
