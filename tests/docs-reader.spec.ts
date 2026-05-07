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

test.beforeEach(async ({ page }) => {
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

test('R7. railScopeTabs · clicking GC narrows rail to GC docs only', async ({ page }) => {
  await bootApp(page, '/index.html#documents');
  await page.waitForTimeout(600);
  await page.locator('.docs-scope-opt[data-docs-scope="gc"]').click();
  await page.waitForTimeout(300);
  // All visible rows must be GC type (CSS class .gc on row)
  const rows = page.locator('.docs-rail-row');
  const total = await rows.count();
  const gcRows = await page.locator('.docs-rail-row.gc').count();
  expect(gcRows).toBe(total);
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
