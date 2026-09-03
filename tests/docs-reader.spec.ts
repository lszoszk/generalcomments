import { expect, test } from '@playwright/test';
import { bootApp, resetWorkspace } from './_helpers';

/**
 * 3-pane Documents reader (v17 + v17.1).
 *
 *  R1. railRenders         — left rail lists every doc, scope tabs work
 *  R2. clickRowOpensDoc    — click rail row → reader paints + URL hash
 *  R3. deepLink            — cold-load #documents/<docId> opens the doc
 *  R4. activeParaScroll    — ?p=<id>#documents/<id> scrolls to ¶
 *  R5. drawerOutline       — drawer shows outline + workspace tools
 *  R6. railFilterText      — typing in rail filter narrows to matches
 *  R7. railScopeTabs       — GC/JUR/SP tabs filter the rail
 *  R8. titleSyncReader     — browser tab title reflects open doc (v17.1 fix)
 */

test.beforeEach(async ({ page, context }) => {
  try {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  } catch { /* WebKit does not expose these permissions. */ }
  await resetWorkspace(page);
});

test('R1. railRenders · rail has 100+ rows, scope tabs visible', async ({ page }) => {
  await bootApp(page, '/index.html#documents');
  await page.waitForTimeout(800);
  await expect(page.locator('.docs-rail-list')).toBeVisible();
  expect(await page.locator('.docs-rail-row').count()).toBeGreaterThan(100);
  // v19.49: dropped the "All" tab; three corpus tabs GC / JUR / SP.
  // Each button now has TWO label spans (full + abbreviation) so we
  // assert on the data-docs-scope attribute instead of the text.
  const scopes = await page.locator('.docs-scope-opt').evaluateAll(
    (els) => els.map((el) => (el as HTMLElement).dataset.docsScope)
  );
  expect(scopes).toEqual(['gc', 'jur', 'sp']);
});

test('R2. clickRowOpensDoc · rail click → reader paints + hash', async ({ page }) => {
  await bootApp(page, '/index.html#documents');
  await page.waitForTimeout(800);
  // v19.56: rail bodies default to collapsed — expand CRPD before
  // clicking the GC6 row inside it.
  await page.locator('.docs-rail-committee[data-collapse-key="gc::CRPD"] summary').click();
  await page.waitForTimeout(200);
  // Click the CRPD GC6 row
  await page.locator('.docs-rail-row[data-doc-id="crpd-c-gc-6"]').click();
  await page.waitForTimeout(500);
  await expect(page.locator('.docs-reader-title')).toContainText(/equality and non-discrimination/i);
  // Hash routing
  expect(page.url()).toContain('#documents/crpd-c-gc-6');
  // ¶ count > 0
  expect(await page.locator('.docs-reader-para').count()).toBeGreaterThan(20);
  // Active rail row
  await expect(page.locator('.docs-rail-row.is-active')).toHaveAttribute('data-doc-id', 'crpd-c-gc-6');
});

test('R3. deepLink · cold load #documents/<docId> opens the doc', async ({ page }) => {
  await bootApp(page, '/index.html#documents/crpd-c-gc-6');
  await page.waitForTimeout(800);
  await expect(page.locator('.docs-reader-title')).toBeVisible();
  expect(await page.locator('.docs-reader-para').count()).toBeGreaterThan(20);
});

test('R4. activeParaScroll · ?p=<id> scrolls + highlights', async ({ page }) => {
  await bootApp(page, '/index.html?p=crpd-c-gc-6-0024#documents/crpd-c-gc-6');
  await page.waitForTimeout(1000);
  const active = page.locator('.docs-reader-para.is-active');
  await expect(active).toHaveCount(1);
  await expect(active).toHaveAttribute('data-para-id', 'crpd-c-gc-6-0024');
});

test('R4b. legacyBareParagraphLink · bare ?p= upgrades and opens the paragraph', async ({ page }) => {
  await bootApp(page, '/index.html?p=crpd-c-gc-6-0024');
  await expect(page).toHaveURL(/\?p=crpd-c-gc-6-0024#documents\/crpd-c-gc-6$/);
  await expect(page.locator('.docs-reader-para.is-active'))
    .toHaveAttribute('data-para-id', 'crpd-c-gc-6-0024', { timeout: 15_000 });
});

test('R5. drawerOutline · outline + workspace tools render', async ({ page, viewport }) => {
  // Drawer is hidden below the 1100 px breakpoint by design — make sure
  // the test runs against a viewport wide enough to render it.
  test.skip((viewport?.width || 0) < 1100, 'Drawer hidden below 1100 px viewport');
  await bootApp(page, '/index.html#documents/crpd-c-gc-6');
  await page.waitForTimeout(800);
  await expect(page.locator('#docs-drawer')).toBeVisible();
  await page.locator('.docs-reader-para').first().click();
  await page.waitForTimeout(300);
  // v19.49: "Open in search" drawer block was removed — Outline +
  // workspace tools remain. Use .first() because strict mode would
  // fail on multiple matches.
  await expect(page.locator('.docs-drawer-block').first()).toBeVisible();
  await expect(page.locator('#dw-bm')).toBeVisible();
  // v19.15: #dw-pin removed — pin lives only on the per-row 📌 affordance now.
  await expect(page.locator('#dw-note')).toBeVisible();
});

test('R6. railFilterText · typing narrows rail rows', async ({ page }) => {
  await bootApp(page, '/index.html#documents');
  // Wait on actual rows, not a fixed timeout — boot loads GC + JUR + SP
  // catalogs and builds the FlexSearch index before setView() paints the
  // docs view, and the JUR catalog is now ~7.8 MB.
  await page.waitForFunction(
    () => document.querySelectorAll('.docs-rail-row').length > 100,
    null,
    { timeout: 15_000 }
  );
  const before = await page.locator('.docs-rail-row').count();
  await page.locator('#docs-filter').fill('trafficking');
  await page.waitForTimeout(400);
  const after = await page.locator('.docs-rail-row').count();
  expect(after).toBeLessThan(before);
  expect(after).toBeGreaterThanOrEqual(1);          // CEDAW GR38 at least
});

test('R7. railScopeTabs · switching scope narrows the rail to that collection', async ({ page }) => {
  await bootApp(page, '/index.html#documents');
  // GC is the default scope, so start by measuring it once rows exist.
  await expect.poll(async () => page.locator('.docs-rail-row').count(), { timeout: 15_000 }).toBeGreaterThan(0);
  const gcTotal = await page.locator('.docs-rail-row').count();
  expect(await page.locator('.docs-rail-row.gc').count()).toBe(gcTotal);

  // Switching to jurisprudence must replace the rail with JUR rows only.
  await page.locator('.docs-scope-opt[data-docs-scope="jur"]').click();
  await expect.poll(async () => page.locator('.docs-rail-row.jur').count(), { timeout: 20_000 }).toBeGreaterThan(0);
  const jurTotal = await page.locator('.docs-rail-row').count();
  expect(await page.locator('.docs-rail-row.jur').count()).toBe(jurTotal);
  expect(await page.locator('.docs-rail-row.gc').count()).toBe(0);
  expect(jurTotal).not.toBe(gcTotal);
});

test('R9. spSectionHeadings · SP docs now render section rollups', async ({ page }) => {
  // v19.51.8: extracted section structure from OHCHR PDFs and stitched
  // it onto SP corpus paragraphs. The reader's section-rollup heading
  // code (which already worked for GCs) now fires for SPs too.
  // a-50-440 has a clean 6-section TOC: I. INTRODUCTION, II. …, etc.
  await bootApp(page, '/index.html#documents/a-50-440');
  await page.waitForTimeout(800);
  // The reader emits .docs-reader-section h3s for each section change.
  const headings = await page.locator('.docs-reader-section').allTextContents();
  expect(headings.length).toBeGreaterThan(2);
  expect(headings.join(' · ')).toMatch(/INTRODUCTION/i);
});

test('R10. spFootnoteMarkers · SP docs render inline footnote markers', async ({ page }) => {
  // v19.52: extracted footnotes from documents.un.org docx (with
  // libreoffice fallback for legacy .doc) and stitched them onto SP
  // corpus paragraphs. Reader's renderParagraphHtml already supported
  // [[fn:N]] markers (from GC pipeline); verifying it now fires on SP.
  // a-75-385 (Special Rapporteur on freedom of religion or belief, 2020)
  // has 179 footnotes across 83 numbered ¶s — first marker lives in ¶1.
  await bootApp(page, '/index.html#documents/a-75-385');
  await page.waitForTimeout(1200);
  // Inline marker buttons render as <button class="fn-marker">
  const markers = page.locator('.docs-reader-para button.fn-marker');
  expect(await markers.count()).toBeGreaterThan(20);
  // First marker should carry data-fn-text (extracted body) — non-empty.
  const firstFnText = await markers.first().getAttribute('data-fn-text');
  expect(firstFnText && firstFnText.length).toBeGreaterThan(5);
});

test('R11. cescrJurisprudence · CESCR cases load via the JUR shard', async ({ page }) => {
  // v19.53: added 247 CESCR Optional Protocol decisions as a new
  // jurisprudence shard (jur_CESCR.json). I.D.G. v. Spain
  // (E/C.12/55/D/2/2014) is the very first OP-ICESCR Views — short
  // case name, well-formed metadata, footnotes attached.
  await bootApp(page, '/index.html#documents/e-c-12-55-d-2-2014');
  await page.waitForTimeout(1500);
  await expect(page.locator('.docs-reader-title')).toBeVisible();
  // Should render >20 paragraphs (the substantive Views).
  expect(await page.locator('.docs-reader-para').count()).toBeGreaterThan(20);
  // Inline footnote markers should be present (extractor walks
  // <w:footnoteReference> directly).
  expect(await page.locator('.docs-reader-para button.fn-marker').count()).toBeGreaterThan(5);
});

test('R12. supersededWarning · obsolete GC identifies its replacement', async ({ page }) => {
  await bootApp(page, '/index.html#documents/crc-c-gc-10');

  const warning = page.locator('.docs-reader-status-warning');
  await expect(warning).toBeVisible({ timeout: 15_000 });
  await expect(warning).toContainText('Superseded');
  await expect(warning).toContainText('CRC/C/GC/24');
  await expect(warning).toContainText('Do not rely on it as the current interpretation');
  await expect(page.locator('.docs-reader-meta')).toContainText(/Adopted /);
});

test('R13. auditedHrcSupersession · old HRC guidance links its official replacement', async ({ page }) => {
  await bootApp(page, '/index.html#documents/hri-gen-1-rev-9-vol-i-p-181');

  const warning = page.locator('.docs-reader-status-warning');
  await expect(warning).toContainText('Superseded');
  await expect(warning).toContainText('CCPR/C/GC/34');
  await expect(warning.locator('a')).toHaveAttribute('href', /docs\.un\.org\/en\/CCPR\/C\/GC\/34/);
});

test('R14. updatedNotSuperseded · CEDAW GR19 remains relevant alongside GR35', async ({ page }) => {
  await bootApp(page, '/index.html#documents/annotated-cedaw-gr19-violence');

  const warning = page.locator('.docs-reader-status-warning');
  await expect(warning).toContainText('Updated guidance');
  await expect(warning).toContainText('remains relevant');
  await expect(warning).toContainText('CEDAW/C/GC/35');
  await expect(warning).not.toContainText('Superseded');
});

test('R15. correctedText · corrigendum is distinguished from a revision', async ({ page }) => {
  await bootApp(page, '/index.html#documents/crc-c-gc-9-corr-1');

  const warning = page.locator('.docs-reader-status-warning');
  await expect(warning).toContainText('Corrected text');
  await expect(warning).toContainText('official corrigendum');
  await expect(warning).not.toContainText('Revised');
});

test('R16. replacementRelationship · current HRC GC36 names both predecessors', async ({ page }) => {
  await bootApp(page, '/index.html#documents/ccpr-c-gc-36');

  const relationship = page.locator('.docs-reader-relationship');
  await expect(relationship).toContainText('Supersedes earlier guidance');
  await expect(relationship).toContainText('p.176');
  await expect(relationship).toContainText('p. 188');
});

test('R8. titleSyncReader · browser tab <title> follows the open doc', async ({ page }) => {
  // v19.6 (B1) fix: updateDocumentTitle now branches on state.view ===
  // 'documents' and reads state.docsActiveDocId. paintDocReaderBody
  // calls it whenever a new doc opens.
  await bootApp(page, '/index.html#documents/crpd-c-gc-6');
  // Wait for setView('documents') → openDocReader → updateDocumentTitle
  // chain to land. Headless chromium is slower than the manual probe;
  // poll on document.title rather than a fixed timeout.
  await page.waitForFunction(
    () => /equality|non-discrimination|GC6/i.test(document.title),
    null,
    { timeout: 8_000 }
  );
});

test('R17. documentCite · SP report cites the organ, not the mandate holder', async ({ page, browserName }) => {
  test.skip(browserName === 'webkit', 'WebKit headless blocks clipboard read');
  // OSCOLA §(f) cites a special-procedures report by the UN organ it was
  // submitted to ("UNHRC 'title' (date) UN Doc …"). Ana Brian Nougrères is
  // the mandate holder of A/HRC/58/58 and must NOT open the citation.
  await bootApp(page, '/index.html#documents/a-hrc-58-58');
  await page.waitForTimeout(900);

  const cite = page.locator('#docs-reader-cite');
  await expect(cite).toBeVisible();
  await cite.evaluate((el: Element) => (el as HTMLDetailsElement).open = true);

  // OSCOLA is the default, marked in the menu.
  await expect(page.locator('#docs-reader-cite .cite-opt.is-default'))
    .toHaveAttribute('data-cite-key', 'oscola');

  await page.locator('#docs-reader-cite .cite-opt[data-cite-key="oscola"]').click();
  const text = await page.evaluate(() => navigator.clipboard.readText());

  expect(text).toMatch(/^UNHRC ‘/);
  expect(text).toContain('Report of the Special Rapporteur on the right to privacy');
  expect(text).toContain('UN Doc A/HRC/58/58');
  expect(text).not.toContain('Nougrères');
  // Document-level citation carries no paragraph pinpoint.
  expect(text).not.toMatch(/para \d/);
});

test('R18. documentCite · organ follows the symbol (A/… → UNGA)', async ({ page, browserName }) => {
  test.skip(browserName === 'webkit', 'WebKit headless blocks clipboard read');
  await bootApp(page, '/index.html#documents/a-50-440');
  await page.waitForTimeout(900);
  const cite = page.locator('#docs-reader-cite');
  await cite.evaluate((el: Element) => (el as HTMLDetailsElement).open = true);
  await page.locator('#docs-reader-cite .cite-opt[data-cite-key="oscola"]').click();
  const text = await page.evaluate(() => navigator.clipboard.readText());
  expect(text).toMatch(/^UNGA ‘/);
  expect(text).toContain('UN Doc A/50/440');
});

test('R19. trailingSubhead · SP section headings break out of the paragraph', async ({ page }) => {
  // The SP PDF extraction glues a section heading onto the tail of the
  // paragraph before it, so A/80/283 ¶42 ends "…use of neurotechnologies
  // E. Precautionary principle in the use…". The reader promotes that tail
  // to its own line rather than running it into the prose.
  await bootApp(page, '/index.html#documents/a-80-283');
  await page.waitForTimeout(900);

  const heads = page.locator('.docs-reader-para .docs-reader-subhead');
  expect(await heads.count()).toBeGreaterThan(5);
  await expect(heads.filter({ hasText: 'Precautionary principle' })).toHaveCount(1);

  // The heading must not still sit inside the running text of ¶42.
  const para42 = page.locator('.docs-reader-para', { hasText: 'In that connection, from the time neurodata' }).first();
  const ownText = await para42.locator('.docs-reader-para-text').evaluate((el: Element) => {
    const clone = el.cloneNode(true) as HTMLElement;
    clone.querySelectorAll('.docs-reader-subhead').forEach((n) => n.remove());
    return clone.textContent || '';
  });
  expect(ownText).not.toContain('Precautionary principle');
  expect(ownText).toContain('improper use of neurotechnologies');
});

test('R20. trailingSubhead · the lettered rule stays off outside the SP corpus', async ({ page }) => {
  // In jurisprudence the same shape matches a signature block, so a treaty
  // body decision must not sprout headings.
  await bootApp(page, '/index.html#documents/ccpr-c-gc-37');
  await page.waitForTimeout(900);
  const text = await page.locator('.docs-reader-stream').innerText();
  expect(text.length).toBeGreaterThan(500);
  await expect(page.locator('.docs-reader-para .docs-reader-subhead')).toHaveCount(0);
});

test('R21. derivedOutline · a report with no extracted sections still gets a table of contents', async ({ page, viewport }) => {
  test.skip((viewport?.width || 0) < 1100, 'Drawer hidden below 1100 px viewport');
  // A/80/283's section structure was never extracted, so the drawer used to
  // say "No headings detected". The headings the prose announces now drive it.
  await bootApp(page, '/index.html#documents/a-80-283');
  await page.waitForTimeout(1000);

  await expect(page.locator('#docs-drawer')).not.toContainText('No headings detected');
  const rows = page.locator('.docs-outline-item');
  expect(await rows.count()).toBeGreaterThan(8);

  // Roman markers are sections, letters nest beneath them. "I." here is the
  // letter after "H.", not roman one — the depth proves the disambiguation.
  await expect(rows.filter({ hasText: 'IV. Advances in neurotechnologies' })).toHaveClass(/depth-0/);
  await expect(rows.filter({ hasText: 'I. Equality, non-discrimination' })).toHaveClass(/depth-1/);

  // The heading must not ALSO appear as a section rollup — it is already
  // rendered at the tail of the paragraph that carries it.
  await expect(page.locator('.docs-reader-section')).toHaveCount(0);
  expect(await page.locator('.docs-reader-subhead').count()).toBeGreaterThan(5);

  // Outline rows navigate.
  await page.locator('.docs-outline-link', { hasText: 'Precautionary principle' }).click();
  await page.waitForTimeout(600);
  await expect(page.locator('.docs-reader-para.is-active')).toHaveAttribute('data-para-id', 'a-80-283-0044');
});

test('R22. mergedDuplicate · the retired Narymbaev stub id still opens the case', async ({ page }) => {
  // ccpr-c-133-d-2904-2016-2907-2016 was a bare duplicate of the Narymbaev
  // record, merged away 2026-08-18. Its docId lives on via alternativeIds, and
  // a paragraph pinpoint carries over because the paragraphs are positional.
  await bootApp(page, '/index.html?p=ccpr-c-133-d-2904-2016-2907-2016-0005#documents/ccpr-c-133-d-2904-2016-2907-2016');
  await page.waitForTimeout(1200);
  await expect(page.locator('.docs-reader-title')).toContainText(/Narymbaev/i);
  await expect(page.locator('.docs-reader-para.is-active'))
    .toHaveAttribute('data-para-id', 'ccpr-c-133-d-2904-2907-2016-0005', { timeout: 10_000 });
});
