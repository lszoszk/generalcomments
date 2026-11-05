import { expect, test } from '@playwright/test';
import { bootApp, collectConsoleErrors, resetWorkspace } from './_helpers';

/**
 * Spanish texts of the General Comments (EN | ES switch, docs/corpus.es.json).
 * Local search path: the API is off on localhost, so these exercise the
 * corpus.es.json overlay, the Spanish FlexSearch index and the renderers.
 *
 *  ES1. readerDeepLink   — ?lang=es#documents/<GC> renders the Spanish text + title
 *  ES2. switchRoundTrip  — the switch sets ?lang=es and survives a reload; EN restores English
 *  ES3. spanishSearch    — a Spanish query finds Spanish paragraphs; the dossier shows them
 *  ES4. enBadge          — a paragraph without Spanish text shows English with the EN badge
 *  ES5. englishUntouched — default (no lang) reader and search stay English, no badge
 */

test.beforeEach(async ({ page }) => {
  await resetWorkspace(page);
});

const readerText = (page, n: number) =>
  page.locator('.docs-reader-para').nth(n).locator('.docs-reader-para-text');

test('ES1. readerDeepLink · Spanish text and title in the reader', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await bootApp(page, '/index.html?lang=es#documents/ccpr-c-gc-36');
  await expect(readerText(page, 0)).toContainText('Esta observación general sustituye', { timeout: 15_000 });
  await expect(page.locator('.docs-reader-title')).toContainText('OG36');
  await expect(page.locator('#lang-switch [data-lang="es"]')).toHaveAttribute('aria-pressed', 'true');
  expect(errors).toEqual([]);
});

test('ES2. switchRoundTrip · ?lang=es, reload, back to English', async ({ page }) => {
  await bootApp(page, '/index.html#documents/ccpr-c-gc-36');
  await expect(readerText(page, 0)).toContainText('This general comment replaces', { timeout: 15_000 });
  await page.locator('#lang-switch [data-lang="es"]').click();
  await expect(readerText(page, 0)).toContainText('Esta observación general sustituye');
  await expect(page).toHaveURL(/[?&]lang=es/);
  await page.reload();
  await expect(readerText(page, 0)).toContainText('Esta observación general sustituye', { timeout: 15_000 });
  await page.locator('#lang-switch [data-lang="en"]').click();
  await expect(readerText(page, 0)).toContainText('This general comment replaces');
  await expect(page).not.toHaveURL(/[?&]lang=es/);
});

test('ES3. spanishSearch · Spanish query, Spanish results and dossier', async ({ page }) => {
  await bootApp(page, '/index.html?lang=es&q=' + encodeURIComponent('desaparición forzada'));
  const first = page.locator('li.result').first();
  await expect(first).toBeVisible({ timeout: 20_000 });
  expect(await page.locator('li.result').count()).toBeGreaterThan(5);
  await expect(first.locator('.result-doc')).toContainText('OG');
  await first.locator('.result-body').click();
  await expect(page.locator('.dossier-title')).toContainText('OG');
  await expect(page.locator('#dossier-active-anchor blockquote p')).toContainText(/desaparici/i);
});

test('ES4. enBadge · a paragraph without Spanish shows English, badged', async ({ page }) => {
  // CRC GC11 is "partial": ¶19 and ¶20 did not pair cleanly and stay English.
  await bootApp(page, '/index.html?lang=es#documents/crc-c-gc-11');
  await expect(readerText(page, 0)).toContainText('En el preámbulo', { timeout: 15_000 });
  const p19 = page.locator('.docs-reader-para').filter({ hasText: 'The presence of indigenous peoples' });
  await expect(p19.locator('.lang-en-badge')).toHaveCount(1);
  await expect(page.locator('.docs-reader-para').first().locator('.lang-en-badge')).toHaveCount(0);
});

test('ES5. englishUntouched · default stays English', async ({ page }) => {
  await bootApp(page, '/index.html#documents/crc-c-gc-11');
  await expect(readerText(page, 0)).toContainText('preamble', { timeout: 15_000 });
  await expect(page.locator('.docs-reader-para .lang-en-badge')).toHaveCount(0);   // About shows a sample badge
  await expect(page.locator('#lang-switch [data-lang="en"]')).toHaveAttribute('aria-pressed', 'true');
});
