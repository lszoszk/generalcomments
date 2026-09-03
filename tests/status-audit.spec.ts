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
