import { expect, test } from '@playwright/test';
import { bootApp, collectConsoleErrors, resetWorkspace, typeQuery } from './_helpers';

/**
 * Recommendations (UHRI) scope. The records are never shipped statically —
 * every search asks the uhri-dataset-api — so these tests mock that service
 * and check the frontend wiring: the scope paints UHRI records, the filters
 * travel as the right query parameters, the dossier shows the annotations and
 * cites the record as a paragraph of its document, an outage is not a zero
 * result, and a record deep link round-trips.
 *
 *  U1. scopePaintsRecords     — REC rows with type pill, theme chips, ¶ number
 *  U2. filtersTravel          — mechanism chip + "Recommendations only" → bodies= / annotation_type=
 *  U3. dossierAndCitation     — metadata grid, OSCOLA cite with UN Doc + para
 *  U4. outageIsNotZero        — 500 → "not a zero-result search" + retry
 *  U5. deepLinkRoundTrip      — ?scope=rec&p=rec-<uuid> opens the record
 */

const RECORDS = [
  {
    AnnotationId: '1fcdefc5-714d-4346-b027-f4957a03abe7',
    Symbol: 'CCPR/C/POL/CO/7',
    Text: '<p>45. The Committee requests the State party to submit its next periodic report by 4 November 2021.</p>',
    TextPlainRaw: '45. The Committee requests the State party to submit its next periodic report by 4 November 2021.',
    TextPlainCleaned: '45. The Committee requests the State party to submit its next periodic report by 4 November 2021.',
    SectionHeadings: ['Dissemination and follow-up'],
    DocumentId: '1ad6c727-52cd-4686-9e7f-f94c38a667fc',
    PublicationDate: '2016-11-23T00:00:00',
    AnnotationType: '- Recommendations',
    Countries: ['Poland'],
    AffectedPersons: [],
    Themes: ['Cooperation & Follow up with Treaty Bodies'],
    Sdgs: ['16 - PEACE, JUSTICE AND STRONG INSTITUTIONS'],
    Regions: ['Eastern Europe'],
    Body: '- CCPR',
  },
  {
    AnnotationId: 'c111ba17-447c-48ea-8f79-2f8a21292a89',
    Symbol: 'CCPR/C/POL/CO/7',
    Text: '<p>23. The Committee is concerned about reports of solitary confinement of detainees.</p>',
    TextPlainRaw: '23. The Committee is concerned about reports of solitary confinement of detainees.',
    TextPlainCleaned: '23. The Committee is concerned about reports of solitary confinement of detainees.',
    SectionHeadings: ['Conditions of detention'],
    DocumentId: '1ad6c727-52cd-4686-9e7f-f94c38a667fc',
    PublicationDate: '2016-11-23T00:00:00',
    AnnotationType: '- Concerns/Observations',
    Countries: ['Poland'],
    AffectedPersons: ['Persons deprived of their liberty & detainees'],
    Themes: ['Conditions of detention', 'Prohibition of torture & ill-treatment (including cruel, inhuman or degrading treatment)'],
    Sdgs: ['16 - PEACE, JUSTICE AND STRONG INSTITUTIONS', '16.3 - Promote the rule of law and access to justice for all'],
    Regions: ['Eastern Europe'],
    Body: '- CCPR',
  },
];

function recordsBody(records = RECORDS) {
  return JSON.stringify({ ok: true, page: 1, page_size: 200, total_pages: 1, total_records: records.length, records });
}

const ANALYTICS = {
  ok: true, requested_sections: ['trends', 'themes', 'text'],
  trends: {
    yearly_counts: [{ year: 2016, count: 2 }],
    yearly_body_counts: [{ year: 2016, body: '- CCPR', count: 2 }],
    yearly_region_counts: [],
    yearly_type_counts: [{ year: 2016, annotation_type: '- Recommendations', count: 1 }, { year: 2016, annotation_type: '- Concerns/Observations', count: 1 }],
    dataset_first_publication_date: '2006-06-02T00:00:00', dataset_last_publication_date: '2026-05-20T00:00:00',
  },
  themes: { theme_counts: [{ theme: 'Conditions of detention', count: 1 }, { theme: 'Cooperation & Follow up with Treaty Bodies', count: 1 }], yearly_theme_counts: [] },
  text: {
    affected_person_counts: [], sdg_counts: [], bigram_counts: [], body_avg_text_length: [],
    yearly_affected_person_counts: [{ year: 2016, affected_person: 'Persons deprived of their liberty & detainees', count: 1 }],
    yearly_sdg_counts: [{ year: 2016, sdg: '16 - PEACE, JUSTICE AND STRONG INSTITUTIONS', count: 2 }],
    sampled: false, sample_size: 2, total_records: 2,
  },
};

async function mockUhri(page: any, opts: { records?: () => string; fail?: boolean } = {}) {
  const requests: string[] = [];
  await page.route('**/uhri-api/api/data/records**', (route: any) => {
    requests.push(route.request().url());
    if (opts.fail) return route.fulfill({ status: 500, body: 'offline' });
    return route.fulfill({ status: 200, contentType: 'application/json', body: (opts.records || recordsBody)() });
  });
  await page.route('**/uhri-api/api/data/analytics**', (route: any) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ANALYTICS) }));
  await page.route('**/uhri-api/api/data/map**', (route: any) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, total_records: 2, country_counts: [{ country: 'Poland', count: 2 }] }) }));
  await page.route('**/uhri-api/api/data/record/**', (route: any) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, record: RECORDS[1] }) }));
  // The unhrdb API must not be reached for real either.
  await page.route('**/unhrdb-api/api/stats', (route: any) =>
    route.fulfill({ status: 200, body: JSON.stringify({ version: 'mock', manifest: {}, totalParagraphs: 1, byType: {} }) }));
  await page.route('**/unhrdb-api/api/search**', (route: any) =>
    route.fulfill({ status: 200, body: JSON.stringify({ query: '', scope: 'gc', total: 0, page: 1, pageSize: 200, hits: [], alsoTry: [], breakdown: { gc: 0, jur: 0, sp: 0 } }) }));
  return requests;
}

test.beforeEach(async ({ page }) => {
  await resetWorkspace(page);
});

test('U1. scopePaintsRecords · the Recommendations scope lists UHRI records', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await mockUhri(page);
  await bootApp(page, '/index.html?api=1&scope=rec');
  const rows = page.locator('.result.rec');
  await expect(rows).toHaveCount(2, { timeout: 15_000 });
  await expect(rows.first().locator('.badge-rec')).toHaveText('REC');
  await expect(rows.first().locator('.rec-type-pill')).toHaveText('Recommendation');
  await expect(rows.first().locator('.result-pn')).toHaveText('¶45');
  await expect(rows.nth(1).locator('.result-meta .rec-theme-chip').first()).toContainText('Conditions of detention');
  // The scope count comes from the static vocabulary; the rail shows the mechanisms.
  await expect(page.locator('#count-rec')).toContainText(/UHRI/);
  await expect(page.locator('#bodies-label')).toHaveText('Mechanism');
  await expect(page.locator('#filter-committees .chip[data-committee="UPR"]')).toBeVisible();
  await expect(page.locator('#filter-block-rec-theme')).toBeVisible();
  await expect(page.locator('#filter-block-textscope')).toBeHidden();
  await expect(page.locator('#results-sub')).toContainText('Universal Human Rights Index');
  expect(errors, errors.join('\n')).toEqual([]);
});

test('U2. filtersTravel · mechanism chip and "Recommendations only" reach the service', async ({ page }) => {
  const requests = await mockUhri(page);
  await bootApp(page, '/index.html?api=1&scope=rec');
  await expect(page.locator('.result.rec')).toHaveCount(2, { timeout: 15_000 });
  await typeQuery(page, 'solitary confinement');
  await page.locator('#filter-committees .chip[data-committee="CCPR"]').click();
  await page.locator('#filter-rec-only').check();
  await expect.poll(() => requests.length, { timeout: 10_000 }).toBeGreaterThanOrEqual(4);
  const last = new URL(requests[requests.length - 1]);
  expect(last.searchParams.get('text_query')).toBe('solitary confinement');
  expect(last.searchParams.get('bodies')).toBe('CCPR');
  expect(last.searchParams.get('annotation_type')).toBe('Recommendations');
  expect(last.searchParams.get('sort_by')).toBe('publication_date');
  // Relevance sorting is not offered for this scope.
  await expect(page.locator('#result-sort .result-opt[data-sort="relevance"]')).toBeDisabled();
  // The URL carries the scope and the toggle.
  await expect.poll(() => page.url()).toContain('scope=rec');
  await expect.poll(() => page.url()).toContain('ro=1');
});

test('U3. dossierAndCitation · record metadata and an OSCOLA cite with UN Doc and paragraph', async ({ page, context }) => {
  try { await context.grantPermissions(['clipboard-read', 'clipboard-write']); } catch { /* WebKit */ }
  await mockUhri(page);
  await bootApp(page, '/index.html?api=1&scope=rec');
  const row = page.locator('.result[data-para-id="rec-c111ba17-447c-48ea-8f79-2f8a21292a89"]');
  await expect(row).toBeVisible({ timeout: 15_000 });
  await row.click();
  const dossier = page.locator('#dossier');
  await expect(dossier.locator('.dossier-kind')).toContainText('OBSERVATION · CCPR');
  await expect(dossier.locator('.dossier-sig-link')).toHaveText(/CCPR\/C\/POL\/CO\/7/);
  await expect(dossier.locator('.rec-facet-chip[data-rec-facet="theme"]').first()).toContainText('Conditions of detention');
  await expect(dossier.locator('.rec-facet-chip[data-rec-facet="group"]')).toHaveCount(1);
  await expect(dossier.locator('.rec-facet-chip[data-rec-facet="sdg"]')).toHaveCount(2);
  await expect(dossier.locator('a[href*="uhri.ohchr.org/en/document/1ad6c727"]')).toBeVisible();
  await expect(dossier.locator('blockquote .pn')).toHaveText('¶ 23');
  await expect(dossier.locator('.dossier-authority-note.rec')).toBeVisible();
  // Cite in OSCOLA via the "other formats" popover.
  await page.locator('#dossier-more').evaluate((el: Element) => (el as HTMLDetailsElement).open = true);
  await page.locator('#cite-other-trigger').click();
  await page.locator('#cite-pop .cite-opt[data-cite-key="oscola"]').click();
  const cite = await page.evaluate(() => navigator.clipboard.readText());
  expect(cite).toBe('Human Rights Committee ‘Concluding observations: Poland’ (23 November 2016) UN Doc CCPR/C/POL/CO/7, para 23.');
  // "All records from this document" fetches by mechanism + State + year and keeps the symbol only.
  await page.locator('#rec-doc-details summary').click();
  await expect(page.locator('#rec-doc-list .dossier-context-para')).toHaveCount(2, { timeout: 10_000 });
});

test('U4. outageIsNotZero · a failing service shows the offline state with retry', async ({ page }) => {
  await mockUhri(page, { fail: true });
  await bootApp(page, '/index.html?api=1&scope=rec&q=solitary');
  await expect(page.locator('.empty-title')).toContainText('not a zero-result search', { timeout: 15_000 });
  await expect(page.locator('#results-title')).toContainText('did not answer');
  await expect(page.locator('#rec-api-retry')).toBeVisible();
  await expect(page.locator('#result-count')).toContainText('offline');
});

test('U5. deepLinkRoundTrip · ?scope=rec&p=rec-<uuid> opens that record', async ({ page }) => {
  await mockUhri(page, { records: () => recordsBody([RECORDS[0]]) });
  await bootApp(page, '/index.html?api=1&scope=rec&p=rec-c111ba17-447c-48ea-8f79-2f8a21292a89');
  // The record was not on the page, so it is fetched by id and pinned on top.
  await expect(page.locator('.result[data-para-id="rec-c111ba17-447c-48ea-8f79-2f8a21292a89"]')).toBeVisible({ timeout: 15_000 });
  await expect(page.locator('#dossier .dossier-kind')).toContainText('OBSERVATION', { timeout: 10_000 });
  await expect.poll(() => page.url()).toContain('p=rec-c111ba17');
});
