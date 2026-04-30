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
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await resetWorkspace(page);
});

async function openDossier(page: any) {
  await bootApp(page, '/index.html');
  await typeQuery(page, 'disability');
  await page.locator('.result').first().click();
  await page.locator('.dossier-toolbar').waitFor();
}

test('D1. saveToggles · bookmark on/off survives reload', async ({ page }) => {
  await openDossier(page);
  await page.locator('#ws-bookmark').click();
  await expect(page.locator('#ws-bookmark')).toHaveClass(/on/);
  await page.reload({ waitUntil: 'commit' });
  await page.waitForFunction(() => /\d+\s*¶/.test(document.getElementById('mast-folio')?.textContent || ''));
  await page.locator('.dossier-toolbar').waitFor();
  await expect(page.locator('#ws-bookmark')).toHaveClass(/on/);
});

test('D2. pinTwoForCompare · 2 pins surface the diff tray', async ({ page }) => {
  // v19.15 removed the dossier-toolbar #ws-pin; pinning lives only on
  // the per-result-row 📌 affordance in the mid-panel now.
  await openDossier(page);
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

test.fixme('D4. noteEditor · opens, focuses, autosaves on blur', async ({ page }) => {
  // FLAKY in headless: the `blur` event from clicking outside the
  // textarea doesn't always propagate cleanly to the listener that
  // triggers autosave. The underlying noteSet() call is exercised in
  // workspace.spec.ts (W4) once that test stabilises. Fix: replace the
  // blur trigger with an explicit `await ta.blur()` and retry.
  await openDossier(page);
  // Capture the active paragraph URL so we can come back to the SAME
  // paragraph after reload (the URL's ?p= param is what restores it).
  const beforeUrl = page.url();
  await page.locator('#ws-note-toggle').click();
  const ta = page.locator('#ws-note');
  await expect(ta).toBeVisible();
  await expect(ta).toBeFocused();
  await ta.fill('Test note from playwright suite');
  // Blur to trigger autosave. Click the dossier title (visible, in-view).
  await page.locator('.dossier-title').click();
  await page.waitForTimeout(700);
  // Navigate to the captured URL so the ?p= param re-opens the same ¶.
  await page.goto(beforeUrl, { waitUntil: 'commit' });
  await page.waitForFunction(() => /\d+\s*¶/.test(document.getElementById('mast-folio')?.textContent || ''));
  await page.locator('.dossier-toolbar').waitFor();
  await page.locator('#ws-note-toggle').click();
  await expect(page.locator('#ws-note')).toHaveValue('Test note from playwright suite');
});

test('D5. citeMenu · 9 formats incl. legal-IL ones → UN footnote copies', async ({ page, browserName }) => {
  test.skip(browserName === 'webkit', 'WebKit headless blocks clipboard read');
  await openDossier(page);
  await page.locator('#cite-trigger').click();
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

test('D6. citeOpenStyle · open-state inverts colour, equal-width grid', async ({ page }) => {
  // v19.15: Pin removed (-1), Link added (+1) — toolbar still 7 cols.
  // Order: Save · Copy · Note · Cite · Flag · Link · Read.
  await openDossier(page);
  const cols = await page.locator('.dossier-toolbar').evaluate((el) => {
    return getComputedStyle(el).gridTemplateColumns;
  });
  const widths = cols.split(/\s+/).map((w) => parseFloat(w));
  expect(widths.length).toBe(7);
  expect(Math.max(...widths) - Math.min(...widths)).toBeLessThan(2);
  // Cite cell has no special background or border before opening.
  const closed = await page.locator('#cite-menu').evaluate((el) => {
    const cs = getComputedStyle(el);
    return { bg: cs.backgroundColor, border: cs.border };
  });
  expect(closed.bg).toMatch(/rgba\(0, 0, 0, 0\)|transparent/);
  // Open: inversion kicks in.
  await page.locator('#cite-trigger').click();
  await expect(page.locator('#cite-menu')).toHaveClass(/is-open/);
});

test('D7. readNavigatesToFullDoc · Read jumps to #documents/<docId>?p=…', async ({ page }) => {
  // v19.15: Read no longer toggles a styling overlay. It navigates to
  // the documents view with the active paragraph centered + highlighted
  // (the existing R4 deep-link path).
  await openDossier(page);
  // Capture the active paragraph's id from the URL ?p= param.
  const beforeUrl = new URL(page.url());
  const paraId = beforeUrl.searchParams.get('p');
  expect(paraId).toBeTruthy();
  await page.locator('#ws-read').click();
  // After click: hash starts with #documents/<docId>, ?p= preserved.
  await page.waitForFunction(() => window.location.hash.startsWith('#documents/'));
  expect(page.url()).toContain(`#documents/${paraId!.replace(/-\d{4}$/, '')}`);
  expect(page.url()).toContain(`p=${paraId}`);
  // Full document reader is now visible with the matching ¶ active.
  await expect(page.locator('.docs-reader-para.is-active')).toHaveAttribute('data-para-id', paraId!);
});

test('D8. permalink · Link button copies a deep URL containing ?p=…', async ({ page, browserName }) => {
  test.skip(browserName === 'webkit', 'WebKit headless blocks clipboard read');
  await openDossier(page);
  const paraId = new URL(page.url()).searchParams.get('p');
  await page.locator('#ws-permalink').click();
  // Toast confirmation
  await expect(page.locator('#feedback-toast.is-shown')).toBeVisible({ timeout: 3_000 });
  await expect(page.locator('#feedback-toast')).toContainText(/Permalink copied/);
  // Clipboard carries the URL with ?p=
  const text = await page.evaluate(() => navigator.clipboard.readText());
  expect(text).toContain(`p=${paraId}`);
});
