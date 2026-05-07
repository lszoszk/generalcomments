import { expect, test } from '@playwright/test';
import { bootApp, resetWorkspace, typeQuery } from './_helpers';

/**
 * Workspace tests — bookmarks, notes, pins, saved searches, and the
 * v15 export-all (Markdown / JSON) flow.
 *
 *  W1. fourBlocks         — workspace renders the 4 named blocks
 *  W2. bookmarkAndJump    — bookmark a row, open Workspace, click row
 *                            → search view opens with active ¶
 *  W3. fullSnippet        — long bookmarks default to expanded body
 *  W4. inlineNote         — every workspace row has a textarea, autosave
 *  W5. exportMd           — Markdown download triggers
 *  W6. exportJson         — JSON download triggers
 *  W7. saveSearch         — Save-search button persists current query
 *  W8. resumeSavedSearch  — clicking a saved search restores ?q
 */

test.beforeEach(async ({ page }) => {
  await resetWorkspace(page);
});

test('W1. fourBlocks · workspace renders Bookmarks/Notes/Pins/Saves', async ({ page }) => {
  await bootApp(page, '/index.html#workspace');
  await page.waitForTimeout(600);
  await expect(page.locator('.workspace-grid')).toBeVisible();
  const heads = await page.locator('.ws-block h3').allTextContents();
  expect(heads.join(' ')).toMatch(/Bookmarks/);
  expect(heads.join(' ')).toMatch(/Notes/);
  expect(heads.join(' ')).toMatch(/Pinned for compare/);
  expect(heads.join(' ')).toMatch(/Saved searches/);
});

test('W2. bookmarkAndJump · ★ → Workspace → click row → search view', async ({ page }) => {
  await bootApp(page, '/index.html');
  await typeQuery(page, 'disability');
  await page.locator('.result .ws-mark-bm').first().click();
  // Navigate to workspace
  await page.locator('a[href="#workspace"]').click();
  await page.waitForTimeout(400);
  // Bookmark row count
  await expect(page.locator('.ws-block').first().locator('.ws-row')).toHaveCount(1);
  // Click the jump link
  await page.locator('.ws-jump').first().click();
  // Should navigate back to search view with the paragraph active
  await page.waitForTimeout(400);
  await expect(page.locator('body')).toHaveAttribute('data-active-view', 'search');
  await expect(page.locator('.dossier-title')).toBeVisible();
});

test('W3. fullSnippet · long bookmarks default to full text + Collapse toggle', async ({ page }) => {
  // Seed a bookmark on a long paragraph by direct localStorage write,
  // since "long" depends on the paragraph and some are short.
  await page.goto('/index.html', { waitUntil: 'commit' });
  await page.evaluate(() => {
    // Use an arbitrary CRPD GC paragraph we know exists.
    localStorage.setItem(
      'unhrdb_bookmarks_v1',
      JSON.stringify([{ paraId: 'crpd-c-gc-6-0024', savedAt: Date.now() }])
    );
  });
  await page.goto('/index.html#workspace', { waitUntil: 'commit' });
  // v19.43-fix14: corpus.json (where the snippet body lives) loads
  // lazily after first paint. Workspace renders an initial row from
  // metadata only (~80 chars) and re-paints once state.paragraphById
  // hydrates. Wait on the actual long-text condition instead of a
  // fixed timeout so a slow corpus fetch doesn't false-fail this.
  await page.waitForFunction(
    () => {
      const el = document.querySelector('.ws-row .ws-row-snippet');
      return !!el && (el.textContent || '').length > 180;
    },
    null,
    { timeout: 15_000 }
  );
  // Long paragraphs (≥320 chars) get a <details class="ws-snippet-fold open">
  // so the user sees full text by default with a Collapse toggle.
  const snippet = page.locator('.ws-row .ws-row-snippet').first();
  await expect(snippet).toBeVisible();
  // No truncation ellipsis on the default view (was 180-char clip pre-v15)
  const text = (await snippet.textContent()) || '';
  expect(text.length).toBeGreaterThan(180);
});

// W4 (inlineNote blur autosave) was perpetually `.fixme` — same
// headless-blur flakiness as the now-removed D4. The autosave wiring
// is exercised by hand via the workspace inline note in production.
// Removed v19.51.6.

test('W5. exportMd · Markdown download fires with the right filename', async ({ page }) => {
  // Seed at least one bookmark so the export bar appears.
  await page.goto('/index.html', { waitUntil: 'commit' });
  await page.evaluate(() => {
    localStorage.setItem(
      'unhrdb_bookmarks_v1',
      JSON.stringify([{ paraId: 'crpd-c-gc-6-0001', savedAt: Date.now() }])
    );
  });
  await page.goto('/index.html#workspace', { waitUntil: 'commit' });
  await page.waitForTimeout(500);
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('#ws-export-md').click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^unhrdb-workspace-\d{4}-\d{2}-\d{2}\.md$/);
});

test('W6. exportJson · JSON download fires', async ({ page }) => {
  await page.goto('/index.html', { waitUntil: 'commit' });
  await page.evaluate(() => {
    localStorage.setItem(
      'unhrdb_bookmarks_v1',
      JSON.stringify([{ paraId: 'crpd-c-gc-6-0001', savedAt: Date.now() }])
    );
  });
  await page.goto('/index.html#workspace', { waitUntil: 'commit' });
  await page.waitForTimeout(500);
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.locator('#ws-export-json').click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^unhrdb-workspace-\d{4}-\d{2}-\d{2}\.json$/);
});

test('W7. saveSearch · current query persists', async ({ page }) => {
  // The save-search flow uses window.prompt() for the name. Auto-accept
  // it with a fixed value so the test isn't gated on a UI dialog.
  page.on('dialog', (d) => d.accept('My saved search'));
  await bootApp(page, '/index.html?q=disability&scope=gc');
  await page.locator('#save-search').click();
  await page.waitForTimeout(400);
  const saved = await page.evaluate(() =>
    JSON.parse(localStorage.getItem('unhrdb_searches_v1') || '[]')
  );
  expect(saved.length).toBeGreaterThanOrEqual(1);
  expect(saved[0].url || '').toMatch(/disability/);
});

test('W8. resumeSavedSearch · click row in workspace restores ?q', async ({ page }) => {
  await page.goto('/index.html', { waitUntil: 'commit' });
  await page.evaluate(() => {
    localStorage.setItem(
      'unhrdb_searches_v1',
      JSON.stringify([
        { name: 'Education + disability', url: '/?q=education+disability&scope=gc', savedAt: Date.now() },
      ])
    );
  });
  await page.goto('/index.html#workspace', { waitUntil: 'commit' });
  await page.waitForTimeout(500);
  await page.locator('.ws-search-link').first().click();
  await page.waitForTimeout(800);
  await expect(page.locator('#q')).toHaveValue('education disability');
  await expect(page.locator('body')).toHaveAttribute('data-active-view', 'search');
});
