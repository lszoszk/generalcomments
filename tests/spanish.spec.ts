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
 *  ES4. scopeAware       — English-only banner + dimmed collections outside the GCs; the switch stays usable
 *  ES5. englishUntouched — default (no lang) reader and search stay English, no badge
 *  ES6. spanishInterface — ES translates the navigation and controls, never the document text; EN restores English
 *  ES7. askSpanish       — Ask (recorded response) shows the official Spanish text of the returned paragraphs
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

test('ES4. scopeAware · English-only collections are dimmed, the banner says so, the switch stays usable', async ({ page }) => {
  await bootApp(page, '/index.html?lang=es&scope=jur');
  await expect(page.locator('#lang-banner')).toContainText('solo está disponible en inglés', { timeout: 15_000 });
  await expect(page.locator('#lang-switch')).toHaveClass(/is-disabled/);
  await expect(page.locator('#lang-switch [data-lang="es"]')).toBeEnabled();
  await expect(page.locator('#lang-switch [data-lang="es"]')).toHaveAttribute('aria-pressed', 'true');
  const jurName = page.locator('.scope-opt[data-scope="jur"] .scope-opt-name');
  expect(Number(await jurName.evaluate((el) => getComputedStyle(el).opacity))).toBeLessThan(0.7);
  await page.locator('.scope-opt[data-scope="gc"]').click();
  await expect(page.locator('#lang-switch')).not.toHaveClass(/is-disabled/);
  await expect(page.locator('#lang-banner')).toContainText('solo las observaciones y recomendaciones generales');
  // CRC GC11 ¶19, a hand-aligned paragraph, reads in Spanish.
  await page.goto('/index.html?lang=es#documents/crc-c-gc-11');
  await expect(page.locator('.docs-reader-para').filter({ hasText: 'La presencia de pueblos indígenas' })).toHaveCount(1, { timeout: 15_000 });
});

test('ES5. englishUntouched · default stays English', async ({ page }) => {
  await bootApp(page, '/index.html#documents/crc-c-gc-11');
  await expect(readerText(page, 0)).toContainText('preamble', { timeout: 15_000 });
  await expect(page.locator('.docs-reader-para .lang-en-badge')).toHaveCount(0);   // About shows a sample badge
  await expect(page.locator('#lang-switch [data-lang="en"]')).toHaveAttribute('aria-pressed', 'true');
});

test('ES6. spanishInterface · navigation and controls in Spanish, document text untouched, EN restores', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await bootApp(page, '/index.html?lang=es&q=tortura');
  await expect(page.locator('html')).toHaveAttribute('lang', 'es', { timeout: 15_000 });
  await expect(page.locator('a[href="#documents"]').first()).toHaveText(/Documentos/);
  await expect(page.locator('.scope-opt[data-scope="gc"] .scope-opt-name')).toHaveText('Observaciones generales');
  await expect(page.getByText(/^[\d,]+ pasajes de [\d,]+ documentos$/).first()).toBeVisible({ timeout: 20_000 });
  // Rendered later (results) are translated too, the paragraph text is not touched by the dictionary.
  await expect(page.locator('li.result .result-body').first()).toContainText(/tortura/i);
  await page.locator('#lang-switch [data-lang="en"]').click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('a[href="#documents"]').first()).toHaveText(/Documents/);
  await expect(page.locator('.scope-opt[data-scope="gc"] .scope-opt-name')).toHaveText('General Comments');
  expect(errors).toEqual([]);
});

test('ES7. askSpanish · Ask shows the official Spanish text of the returned paragraphs', async ({ page }) => {
  const fixture = JSON.stringify(ASK_FIXTURE);
  const cors = { 'access-control-allow-origin': '*', 'content-type': 'application/json' };
  // Mock backend on the local-dev origin the CSP allows.
  await page.route('http://127.0.0.1:8767/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ status: 200, headers: cors, body: path.endsWith('/api/ask') ? fixture : '{"ok":true}' });
  });
  // ?ask= outranks the meta tag (the live backend, which refuses localhost).
  await bootApp(page, '/index.html?lang=es&ask=' + encodeURIComponent('http://127.0.0.1:8767') + '#ask');
  await page.locator('#ask-q').fill('¿Es absoluta la prohibición de la tortura?');
  await page.locator('#ask-go').click();
  await expect(page.locator('.ask-answer-body')).toContainText('El Comité recuerda', { timeout: 20_000 });
  await expect(page.locator('.ask-answer-title')).toHaveText('Mejor resultado · textual');
  await expect(page.locator('.ask-source-text').first()).toContainText('El Comité recuerda');
  await page.locator('#lang-switch [data-lang="en"]').click();
  await expect(page.locator('.ask-answer-body')).toContainText('The Committee recalls that the prohibition of torture');
});

// /api/ask response for '¿Es absoluta la prohibición de la tortura?' (recorded 2026-11-06, texts shortened).
const ASK_FIXTURE = {
  "query": "¿Es absoluta la prohibición de la tortura?",
  "answer": "8. The Committee recalls that the prohibition of torture, as defined in article 1 of the Convention, is absolute. Article 2 (2) of the Convention provides that “no exceptional circumstances whatsoever, whether a state of war or a threat of war, internal political instability or any other public emer",
  "retrieval": {},
  "sources": [
    {
      "paraId": "cat-c-gc-4-0008",
      "docId": "cat-c-gc-4",
      "signature": "CAT/C/GC/4",
      "committee": "CAT",
      "year": 2018,
      "title": "GC4: implementation of Art. 3 in the context of Art. 22 [REVISED]",
      "status": null,
      "text": "8. The Committee recalls that the prohibition of torture, as defined in article 1 of the Convention, is absolute. Article 2 (2) of the Convention provides that “no exceptional circumstances whatsoever, whether a state of war or a threat of war, internal political instability or any other public emer",
      "match": {
        "bandLabel": "excellent",
        "score100": 88
      }
    },
    {
      "paraId": "cat-c-gc-2-0005",
      "docId": "cat-c-gc-2",
      "signature": "CAT/C/GC/2",
      "committee": "CAT",
      "year": 2008,
      "title": "GC2: Implementation of Art. 2 by States parties",
      "status": null,
      "text": "5. Article 2, paragraph 2, provides that the prohibition against torture is absolute and non-derogable. It emphasizes that no exceptional circumstances whatsoever may be invoked by a State Party to justify acts of torture in any territory under its jurisdiction. The Convention identifies as among su",
      "match": {
        "bandLabel": "excellent",
        "score100": 87
      }
    }
  ]
};
