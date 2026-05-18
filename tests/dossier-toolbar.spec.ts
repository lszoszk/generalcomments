import { expect, test } from '@playwright/test';
import { bootApp, resetWorkspace, typeQuery } from './_helpers';

/**
 * Dossier action toolbar tests — covers the v18 / v18.2 / v19.5 churn
 * around the 6-button cluster (Save / Pin / Copy / Note / Cite / Read).
 *
 *  D1. saveToggles       — bookmark on/off survives page navigation
 *  D2. pinTwoForCompare  — 2 pins → diff tray appears
 *  D3. copyParagraph     — Copy button writes para text to clipboard
 *  D4. noteEditor        — Note opens textarea below toolbar, autosaves
 *  D5. citeMenu          — Cite popover shows 5 formats; click APA copies
 *  D6. citeOpenStyle     — open-state inverts ink/paper (no garnet bold)
 *  D7. readingModeFromBtn — clicking 📖 read button toggles reading mode
 */

test.beforeEach(async ({ page, context }) => {
  // `clipboard-read` / `clipboard-write` are not valid permission names
  // on WebKit — the `mobile` project runs WebKit, where grantPermissions
  // throws "Unknown permission" and kills every test in this file before
  // its body runs. Guard it: the clipboard-dependent tests (D3/D5/D8)
  // test.skip on webkit anyway, and the rest don't touch the clipboard.
  try {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  } catch { /* WebKit: unsupported permission names — ignore */ }
  await resetWorkspace(page);
});

async function openDossier(page: any) {
  await bootApp(page, '/index.html');
  await typeQuery(page, 'disability');
  await page.locator('.result').first().click();
  await page.locator('.dossier-footer').waitFor();
}

test('D1. saveToggles · bookmark on/off survives reload', async ({ page }) => {
  // v19.43-fix3: the search-view URL no longer carries `?p=<paraId>`,
  // so the dossier is NOT auto-restored after reload — opening it
  // requires re-clicking the row. The bookmark itself lives in
  // localStorage and IS persistent; we re-open the dossier on the same
  // paragraph after reload to verify the persisted ★ state.
  await openDossier(page);
  const paraId = await page.locator('.result.is-active').first().getAttribute('data-para-id');
  await page.locator('#ws-bookmark').click();
  await expect(page.locator('#ws-bookmark')).toHaveClass(/on/);
  await page.reload({ waitUntil: 'commit' });
  await page.waitForFunction(() => /\d+\s*¶/.test(document.getElementById('mast-folio')?.textContent || ''));
  // Same paragraph by data-para-id, not just .result first-child (sort
  // order may differ run-to-run on the search corpus).
  await page.locator(`.result[data-para-id="${paraId}"]`).first().click();
  await page.locator('.dossier-footer').waitFor();
  await expect(page.locator('#ws-bookmark')).toHaveClass(/on/);
});

test('D2. pinTwoForCompare · 2 pins surface the diff tray', async ({ page }) => {
  // v19.15 removed the dossier-toolbar #ws-pin; pinning lives only on
  // the per-result-row 📌 affordance in the mid-panel now. No dossier
  // is opened — on the mobile viewport an open dossier covers the
  // result column, hiding the very pins this test clicks.
  await bootApp(page, '/index.html');
  await typeQuery(page, 'disability');
  await page.locator('.result .ws-mark-pin').nth(0).click();
  await page.locator('.result .ws-mark-pin').nth(1).click();
  await expect(page.locator('.diff-tray')).toBeVisible();
  await expect(page.locator('.diff-tray')).toContainText(/2\/2|PINNED/);
});

test('D3. copyParagraph · Copy button puts para text on clipboard', async ({ page, browserName }) => {
  test.skip(browserName === 'webkit', 'WebKit headless blocks clipboard read API');
  await openDossier(page);
  await page.locator('#ws-copy').click();
  // Read clipboard back via the granted permission
  const text = await page.evaluate(() => navigator.clipboard.readText());
  expect(text.length).toBeGreaterThan(20);     // a real paragraph
  // Flash class fired
  await expect(page.locator('#ws-copy')).toHaveClass(/is-flash/);
});

// D4 (noteEditor blur autosave) was perpetually `.fixme` because
// headless Playwright doesn't reliably fire `blur` from a synthetic
// click on a sibling element. The underlying noteSet() autosave is
// exercised by hand and via the dossier note-toggle round-trip in
// production. Removed v19.51.6 to clean up the suite's skipped count.

test('D5. citeMenu · 9 formats incl. legal-IL ones → UN footnote copies', async ({ page, browserName }) => {
  test.skip(browserName === 'webkit', 'WebKit headless blocks clipboard read');
  await openDossier(page);
  // v19.43-fix8: the cite popover is opened from the "Cite in another
  // format" entry inside the More overflow, not a top-level button.
  // Open the <details> directly (synthetic clicks on <summary> can be
  // flaky during dossier mount animation — see smoke 8).
  await page.locator('#dossier-more').evaluate((el: Element) =>
    (el as HTMLDetailsElement).open = true
  );
  await page.locator('#cite-other-trigger').click();
  await expect(page.locator('#cite-pop')).toBeVisible();
  // v19.15: legal formats first, academic/tooling formats after.
  const formats = await page.locator('#cite-pop .cite-opt').evaluateAll((els) =>
    els.map((e) => (e as HTMLElement).dataset.citeKey)
  );
  expect(formats).toEqual(['unfn', 'oscola', 'bluebook', 'mcgill', 'apa', 'chicago', 'bibtex', 'ris', 'url']);
  // Click UN treaty-body footnote → copy + flash
  await page.locator('#cite-pop .cite-opt[data-cite-key="unfn"]').click();
  await expect(page.locator('#cite-pop .cite-opt[data-cite-key="unfn"] .cite-fmt')).toContainText(/COPIED/);
  const text = await page.evaluate(() => navigator.clipboard.readText());
  // Shape: "<Long committee>, General Comment No. N, ¶ M, U.N. Doc. <symbol> (YYYY)."
  expect(text).toMatch(/U\.N\. Doc\. /);
  expect(text).toMatch(/Committee/);
});

// D6 (citeOpenStyle) was retired with the v19.43-fix8 layout change
// (the "7 equal-width buttons in a grid" toolbar that gave the cite
// cell its "open-state inverts colour" styling no longer exists).
// Removed v19.51.6 — the new footer-CTA + overflow-menu pattern is
// covered by smoke 8 (dossierFooter) and D5 (citeMenu).

test('D7. readNavigatesToFullDoc · Read jumps to #documents/<docId>?p=…', async ({ page }) => {
  // v19.15: Read no longer toggles a styling overlay. It navigates to
  // the documents view with the active paragraph centered + highlighted
  // (the existing R4 deep-link path).
  //
  // v19.43-fix3: the search-view URL no longer carries `?p=<paraId>`
  // — read it from the active result row's data-para-id instead.
  // v19.43-fix8: the Read action lives in the More overflow now.
  await openDossier(page);
  const paraId = await page.locator('.result.is-active').first().getAttribute('data-para-id');
  expect(paraId).toBeTruthy();
  await page.locator('#dossier-more').evaluate((el: Element) =>
    (el as HTMLDetailsElement).open = true
  );
  await page.locator('#ws-read').click();
  // After click: hash starts with #documents/<docId>, ?p= preserved.
  await page.waitForFunction(() => window.location.hash.startsWith('#documents/'));
  expect(page.url()).toContain(`#documents/${paraId!.replace(/-\d{4}$/, '')}`);
  expect(page.url()).toContain(`p=${paraId}`);
  // Full document reader is now visible with the matching ¶ active.
  // openInDocReader is a hard navigation, so the reader re-boots
  // before paintDocReaderBody marks the paragraph — bump the wall.
  await expect(page.locator('.docs-reader-para.is-active'))
    .toHaveAttribute('data-para-id', paraId!, { timeout: 15_000 });
});

test('D8. permalink · Link button copies a deep URL containing ?p=…', async ({ page, browserName }) => {
  test.skip(browserName === 'webkit', 'WebKit headless blocks clipboard read');
  await openDossier(page);
  // v19.43-fix3: read paraId from active row, not URL.
  // v19.43-fix8: permalink lives in the More overflow.
  const paraId = await page.locator('.result.is-active').first().getAttribute('data-para-id');
  expect(paraId).toBeTruthy();
  await page.locator('#dossier-more').evaluate((el: Element) =>
    (el as HTMLDetailsElement).open = true
  );
  await page.locator('#ws-permalink').click();
  // Toast confirmation
  await expect(page.locator('#feedback-toast.is-shown')).toBeVisible({ timeout: 3_000 });
  await expect(page.locator('#feedback-toast')).toContainText(/Permalink copied/);
  // Clipboard carries the URL with ?p=
  const text = await page.evaluate(() => navigator.clipboard.readText());
  expect(text).toContain(`p=${paraId}`);
});
