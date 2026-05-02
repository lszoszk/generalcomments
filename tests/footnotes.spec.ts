import { expect, test } from '@playwright/test';
import { bootApp, resetWorkspace, seedFootnotes, typeQuery } from './_helpers';

/**
 * v19.8 footnote infrastructure tests. Production corpus has no footnotes
 * yet (data migration pending), so we seed synthetic entries via the fetch
 * interceptor and verify the UX:
 *
 *   F1. markerRenders        — [[fn:N]] tokens become clickable buttons in reader
 *   F2. popoverOpens         — clicking a marker shows the footnote text
 *   F3. popoverEscapeCloses  — Escape dismisses + returns focus to trigger
 *   F4. snippetHidesMarkers  — search results never render [[fn:N]] tokens
 *   F5. citationMatchPill    — query that matches only in footnote shows pill
 *   F6. zeroRegressions      — paragraph without footnotes renders identical HTML
 */

// v19.13: footnote source data was reverted (PDF extractor bugs — see
// docs/_audit/FOOTNOTES_MIGRATION_PLAN.md "v19.13 reset"). CAT/OP/GC/1
// is the only doc with real footnotes for now; pick a quiet doc with
// no footnotes for synthetic seeding so assertions stay stable.
// CEDAW GR38 (122 ¶, no footnotes after revert) is a good target.
const SEED_DOC_ID = 'cedaw-c-gc-38';
const SEED_PARA_ID = 'cedaw-c-gc-38-0033';

test.beforeEach(async ({ page }) => {
  await resetWorkspace(page);
  await seedFootnotes(page, [
    {
      paraId: SEED_PARA_ID,
      footnotes: [
        {
          n: 1,
          text: 'Communication No. 1158/2003, Blanco Domínguez v. Spain, para. 9.3 — TEST FIXTURE for footnote popover behaviour.',
          anchor: '.', // anchor after the first period
        },
        {
          n: 2,
          text: 'See Cuscumigratoria v. Sample, fictional fixture used only by the v19.8 footnote test suite.',
        },
      ],
    },
  ]);
});

test('F1. markerRenders · [[fn:N]] tokens become buttons in reader', async ({ page }) => {
  await bootApp(page, `/index.html#documents/${SEED_DOC_ID}`);
  await page.waitForTimeout(800);
  const para = page.locator(`[data-para-id="${SEED_PARA_ID}"]`);
  await expect(para).toBeVisible();
  // Two markers seeded → two buttons rendered.
  const markers = para.locator('button.fn-marker');
  await expect(markers).toHaveCount(2);
  await expect(markers.first()).toHaveAttribute('data-fn-n', '1');
  await expect(markers.nth(1)).toHaveAttribute('data-fn-n', '2');
  // Marker text is the superscript number.
  await expect(markers.first().locator('sup')).toHaveText('1');
});

test('F2. popoverOpens · clicking a marker shows the footnote text', async ({ page }) => {
  await bootApp(page, `/index.html#documents/${SEED_DOC_ID}`);
  await page.waitForTimeout(800);
  const para = page.locator(`[data-para-id="${SEED_PARA_ID}"]`);
  const marker = para.locator('button.fn-marker').first();
  await marker.click();
  const pop = page.locator('.fn-popover');
  await expect(pop).toBeVisible();
  await expect(pop.locator('.fn-popover-body')).toContainText(/Blanco Domínguez/);
  await expect(marker).toHaveAttribute('aria-expanded', 'true');
});

test('F3. popoverEscapeCloses · Escape dismisses popover', async ({ page }) => {
  await bootApp(page, `/index.html#documents/${SEED_DOC_ID}`);
  await page.waitForTimeout(800);
  const para = page.locator(`[data-para-id="${SEED_PARA_ID}"]`);
  const marker = para.locator('button.fn-marker').first();
  await marker.click();
  await expect(page.locator('.fn-popover')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.fn-popover')).toBeHidden();
  await expect(marker).toHaveAttribute('aria-expanded', 'false');
});

test('F4. snippetHidesMarkers · search snippets never render [[fn:N]]', async ({ page }) => {
  // "desperation" hits 3 paragraphs including the seeded CEDAW GR38 ¶33,
  // so the seeded result row is guaranteed to show up. We assert NO snippet
  // across the result list contains a marker token — the row whose
  // underlying text DOES contain markers must have had them stripped by
  // stripFnMarkers before rendering.
  await bootApp(page, '/index.html');
  await page.waitForTimeout(800);
  await typeQuery(page, 'desperation');
  const seededResult = page.locator(`.result[data-para-id="${SEED_PARA_ID}"]`);
  await expect(seededResult).toHaveCount(1, { timeout: 6_000 });
  const allSnippets = await page.locator('.result-text').allInnerTexts();
  expect(allSnippets.length).toBeGreaterThan(0);
  for (const t of allSnippets) {
    expect(t).not.toContain('[[fn:');
  }
});

test('F5. citationMatchPill · query matching only a footnote shows the pill', async ({ page }) => {
  // The seeded footnote contains the unique token "Cuscumigratoria" — a
  // made-up word that cannot appear in real corpus prose. Searching for
  // it must produce at least one hit (the seeded paragraph) and that
  // result row must carry the .match-in-citation pill because the visible
  // snippet doesn't contain the token.
  await bootApp(page, '/index.html');
  await page.waitForTimeout(800);
  await typeQuery(page, 'Cuscumigratoria');
  // The result row for the seeded paragraph should be visible somewhere.
  const seededResult = page.locator(`.result[data-para-id="${SEED_PARA_ID}"]`);
  await expect(seededResult).toHaveCount(1, { timeout: 6_000 });
  await expect(seededResult.locator('.match-in-citation')).toBeVisible();
});

test('F6. zeroRegressions · paragraph without footnotes renders without buttons', async ({ page }) => {
  // ¶34 was NOT seeded — confirm it has no .fn-marker buttons.
  await bootApp(page, `/index.html#documents/${SEED_DOC_ID}`);
  await page.waitForTimeout(800);
  // Scope to reader pane (search list also carries data-para-id).
  const otherPara = page.locator(`.docs-reader-para[data-para-id="${SEED_DOC_ID}-0034"]`);
  await expect(otherPara).toBeVisible();
  await expect(otherPara.locator('button.fn-marker')).toHaveCount(0);
});

test('F7. dossierRendersMarkers · clicking a result paints buttons in the dossier', async ({ page }) => {
  // The dossier (right pane in search view) used to render `[[fn:N]]`
  // tokens as raw text. v19.12 wires renderParagraphHtml() into the
  // paintDossier path. Open the seeded paragraph via the dossier and
  // confirm the body paragraph carries a clickable marker.
  await bootApp(page, '/index.html');
  await page.waitForTimeout(800);
  await typeQuery(page, 'Cuscumigratoria');
  const result = page.locator(`.result[data-para-id="${SEED_PARA_ID}"]`);
  await expect(result).toHaveCount(1, { timeout: 6_000 });
  await result.click();
  // Dossier renders the same paragraph; markers appear as fn-marker buttons.
  const dossierMarkers = page.locator('#dossier button.fn-marker');
  await expect(dossierMarkers).toHaveCount(2);
  await expect(dossierMarkers.first()).toHaveAttribute('data-fn-n', '1');
});

test('F8. dossierPopover · marker click in dossier opens the popover', async ({ page }) => {
  await bootApp(page, '/index.html');
  await page.waitForTimeout(800);
  await typeQuery(page, 'Cuscumigratoria');
  const result = page.locator(`.result[data-para-id="${SEED_PARA_ID}"]`);
  await expect(result).toHaveCount(1, { timeout: 6_000 });
  await result.click();
  await page.locator('#dossier button.fn-marker').first().click();
  const pop = page.locator('.fn-popover');
  await expect(pop).toBeVisible();
  await expect(pop.locator('.fn-popover-body')).toContainText(/Blanco Domínguez/);
});

test('F9. fnToggle · default ON, click flips to OFF, persists across reload', async ({ page }) => {
  await bootApp(page, '/index.html');
  const toggle = page.locator('#fn-toggle');
  await expect(toggle).toBeVisible();
  await expect(toggle).toHaveClass(/is-on/);
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await toggle.click();
  await expect(toggle).not.toHaveClass(/is-on/);
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  // Wait for the 250 ms URL-debounce to fire so ?fn=0 is in the address
  // bar BEFORE we reload — the init script reads the URL param and skips
  // the localStorage wipe that would reset the toggle back to ON.
  await page.waitForURL(/fn=0/, { timeout: 3_000 });
  // Reload — preference persists via localStorage + URL param.
  await page.reload();
  await page.waitForFunction(() => {
    const folio = document.getElementById('mast-folio')?.textContent || '';
    return /\d+\s*¶/.test(folio);
  }, null, { timeout: 15_000 });
  await expect(page.locator('#fn-toggle')).not.toHaveClass(/is-on/);
});

test('F10. fnToggleHidesPill · OFF state suppresses match-in-citation hits', async ({ page }) => {
  // With the toggle ON, "Cuscumigratoria" finds the seeded paragraph
  // (footnote-only match) and the pill renders. Flip OFF and the same
  // search returns zero results — the index never queried fnText.
  await bootApp(page, '/index.html');
  await page.waitForTimeout(800);
  // Flip toggle OFF first
  await page.locator('#fn-toggle').click();
  await typeQuery(page, 'Cuscumigratoria');
  await page.waitForTimeout(400);
  // Should be no result for the seeded paragraph anymore.
  const seeded = page.locator(`.result[data-para-id="${SEED_PARA_ID}"]`);
  await expect(seeded).toHaveCount(0);
  // And no match-in-citation pill anywhere.
  await expect(page.locator('.match-in-citation')).toHaveCount(0);
});

test('F7. realDataCatOpGC1 · production footnotes render in the SPT general comment', async ({ page }) => {
  // CAT/OP/GC/1 was ingested in v19.8 with real footnotes from the OHCHR DOCX.
  // ¶1 carries [[fn:2]] [[fn:3]] [[fn:4]] markers anchored in the prose; this
  // test guards against an extraction regression that would silently drop them.
  await resetWorkspace(page);
  await bootApp(page, '/index.html#documents/cat-op-gc-1');
  await page.waitForTimeout(900);
  // Scope to the reader pane — search results list also carries data-para-id.
  const para = page.locator('.docs-reader-para[data-para-id="cat-op-gc-1-0001"]');
  await expect(para).toBeVisible();
  // ≥1 marker rendered
  await expect(para.locator('button.fn-marker').first()).toBeVisible();
  // Click first marker → popover with real footnote text
  await para.locator('button.fn-marker').first().click();
  const pop = page.locator('.fn-popover');
  await expect(pop).toBeVisible();
  // First footnote in the source DOCX is "Optional Protocol, preamble." — but
  // marker numbering may vary; we just assert non-empty text.
  await expect(pop.locator('.fn-popover-body')).not.toBeEmpty();
});
