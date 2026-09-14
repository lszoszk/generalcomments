import { expect, test } from '@playwright/test';
import { bootApp, collectConsoleErrors, resetWorkspace } from './_helpers';

/**
 * Citation check ("check my text"). Everything runs in the browser against
 * the catalogue and the local corpus, so no API mocks are needed.
 *
 *  C1. viewOpens         — #check paints the form, nav link is active
 *  C2. sampleStatuses    — the built-in sample yields every status: a found GC
 *                          with a verbatim quotation, a superseded GC, an
 *                          invented GC number and symbol, an ambiguous GC, a
 *                          wrong pinpoint, a case resolved by name
 *  C3. misquoteRedline   — a changed word in a quotation is struck through
 *  C4. reportCopies      — the Markdown report lands on the clipboard
 */

test.beforeEach(async ({ page }) => {
  await resetWorkspace(page);
});

async function openCheck(page: any) {
  await bootApp(page, '/index.html#check');
  await expect(page.locator('section[data-view="check"]')).toBeVisible();
  await expect(page.locator('#check-text')).toBeVisible();
}

test('C1. viewOpens · #check shows the form and highlights the nav link', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await openCheck(page);
  await expect(page.locator('#check-nav-link')).toHaveClass(/active/);
  await expect(page.locator('#check-run')).toBeVisible();
  await expect(page.locator('#check-output')).toBeHidden();
  expect(errors, errors.join('\n')).toEqual([]);
});

test('C2. sampleStatuses · the sample text exercises every verdict', async ({ page }) => {
  await openCheck(page);
  await page.locator('#check-sample').click();
  const rows = page.locator('.ck-row');
  await expect(rows.first()).toBeVisible({ timeout: 15_000 });
  // Paragraph checks need the local corpus; wait for the status line to settle.
  await expect(page.locator('#check-status')).toContainText(/Checked \d+ citations and \d+ quotations/, { timeout: 45_000 });

  const rowFor = (text: string) => page.locator('.ck-row', { has: page.locator('.ck-raw', { hasText: text }) }).first();
  // Ambiguous: GC 14 without a committee (CCPR, CESCR and CRC each have one).
  await expect(rowFor('General Comment No. 14')).toHaveClass(/ck-ambiguous/);
  // Found, pinpoint exists, quotation verbatim.
  const gc36 = rowFor('General Comment No. 36');
  await expect(gc36).toHaveClass(/ck-ok/);
  await expect(gc36.locator('.ck-note-ok').first()).toContainText('Paragraph 3 exists');
  await expect(gc36.locator('.ck-note-ok').nth(1)).toContainText('verbatim');
  await expect(gc36.locator('.ck-resolved')).toContainText('CCPR/C/GC/36');
  // The cited paragraph is one click away: collapsed by default, its text and a reader link inside.
  const para36 = gc36.locator('details.ck-para');
  await expect(para36).toHaveCount(1);
  await expect(para36.locator('.ck-para-summary')).toContainText('Show paragraph 3');
  await expect(para36.locator('.ck-para-body')).toBeHidden();
  await para36.locator('.ck-para-summary').click();
  await expect(para36.locator('.ck-para-body')).toBeVisible();
  await expect(para36.locator('.ck-para-p').first()).toContainText('interpreted narrowly');
  await expect(para36.locator('.ck-para-open a')).toHaveAttribute('href', /p=ccpr-c-gc-36-\d+/);
  // Superseded.
  const gc6 = rowFor('General Comment No. 6');
  await expect(gc6).toHaveClass(/ck-warn/);
  await expect(gc6.locator('.ck-note', { hasText: 'Superseded by CCPR/C/GC/36' })).toBeVisible();
  // Wrong pinpoint: GC 32 has 65 paragraphs.
  const gc32 = rowFor('General Comment No. 32');
  await expect(gc32).toHaveClass(/ck-bad/);
  await expect(gc32.locator('.ck-note-bad').first()).toContainText('Paragraph 99 does not exist');
  await expect(gc32.locator('details.ck-para')).toHaveCount(0);
  // Case name and communication number both resolve to Toussaint v. Canada.
  await expect(rowFor('Toussaint v. Canada')).toHaveClass(/ck-ok/);
  await expect(rowFor('Toussaint v. Canada').locator('.ck-resolved')).toContainText('CCPR/C/123/D/2348/2014');
  await expect(rowFor('Communication No. 2348/2014')).toHaveClass(/ck-ok/);
  // Invented GC number and symbol.
  await expect(rowFor('General Comment No. 45')).toHaveClass(/ck-bad/);
  await expect(rowFor('General Comment No. 45').locator('.ck-note')).toContainText('run up to No. 37');
  await expect(rowFor('CRC/C/GC/99')).toHaveClass(/ck-bad/);
  // CRC GC 25 ¶1 quotation is verbatim.
  const crc25 = rowFor('General Comment No. 25');
  await expect(crc25).toHaveClass(/ck-ok/);
  await expect(crc25.locator('.ck-note-ok').nth(1)).toContainText('verbatim');
  // The annotated text carries a red mark for the invented symbol and a green one for GC 36.
  await expect(page.locator('#check-annotated mark.ck-bad', { hasText: 'CRC/C/GC/99' })).toBeVisible();
  await expect(page.locator('#check-annotated mark.ck-cite.ck-ok', { hasText: 'CCPR/C/GC/36' })).toBeVisible();
  await expect(page.locator('#check-summary')).toContainText('not found');
});

test('C3. misquoteRedline · a changed word is struck through and the source word shown', async ({ page }) => {
  await openCheck(page);
  await page.locator('#check-text').fill(
    'The Human Rights Committee held that the right to life “is a right that must not be interpreted narrowly” (General Comment No. 36, para. 3).'
  );
  await page.locator('#check-run').click();
  await expect(page.locator('#check-status')).toContainText(/Checked 1 citation and 1 quotation/, { timeout: 45_000 });
  const row = page.locator('.ck-row').first();
  await expect(row).toHaveClass(/ck-ok|ck-warn/);
  const diff = row.locator('.ck-diff');
  await expect(diff.locator('del')).toContainText('must');
  await expect(diff.locator('ins')).toContainText('should');
  await expect(row.locator('.ck-notes')).toContainText(/small difference|of the words match/);
});

test('C4. reportCopies · the Markdown report is written to the clipboard', async ({ page, context }) => {
  try { await context.grantPermissions(['clipboard-read', 'clipboard-write']); } catch { /* WebKit */ }
  await openCheck(page);
  await page.locator('#check-text').fill('See CCPR/C/GC/36 and the invented CRC/C/GC/99.');
  await page.locator('#check-run').click();
  await expect(page.locator('.ck-row')).toHaveCount(2, { timeout: 15_000 });
  await expect(page.locator('#check-status')).toContainText(/Checked 2 citations/, { timeout: 15_000 });
  await page.locator('#check-copy-report').click();
  const md = await page.evaluate(() => navigator.clipboard.readText());
  expect(md).toContain('| # | As written | Status |');
  expect(md).toContain('CCPR/C/GC/36');
  expect(md).toContain('✖ not found');
});
