import { expect, test } from '@playwright/test';
import { bootApp, resetWorkspace, typeQuery } from './_helpers';

/**
 * Report-a-problem flow.
 *
 * v19.14 reshaped this from a global "describe a bug" affordance into a
 * per-paragraph curator workflow. The modal now offers six categories,
 * comment is optional (≤280 chars), and a successful submit shows a
 * toast (with the GitHub issue number when the backend has the token).
 *
 *  F1. footerLinkVisible    — global "Report a problem" still in footer
 *  F2. modalOpens           — six new categories rendered
 *  F3. contextAutofill      — active paragraph fills CONTEXT line
 *  F5. submitOk             — happy path: toast appears, modal closes,
 *                             payload includes auto-context (paraId,
 *                             signature, view, url, query, scope, excerpt)
 *  F6. submit429            — rate-limit tailored copy, draft preserved
 *  F8. escClose             — Esc closes modal
 *  F9. dossierFlag          — ⚐ button on dossier opens with paragraph context
 *  F10. readerFlag          — ⚐ button in documents reader opens with context
 *  F11. issueLinkInToast    — issueUrl from server renders a link in toast
 *  F12. draftSurvivesFail   — failed submit keeps text in localStorage
 */

test.beforeEach(async ({ page }) => {
  await resetWorkspace(page);
});

test('F1. footerLinkVisible · "Report a problem" rendered in footer', async ({ page }) => {
  await bootApp(page);
  await expect(page.locator('#foot-report')).toBeVisible();
});

test('F2. modalOpens · click button → 6 categories', async ({ page }) => {
  await bootApp(page);
  await page.locator('#foot-report').click();
  await expect(page.locator('#report-modal')).toBeVisible();
  const kinds = await page.locator('.report-kind input[name="kind"]').evaluateAll((els) =>
    els.map((el) => (el as HTMLInputElement).value)
  );
  expect(kinds).toEqual([
    'wrong-text', 'wrong-fn', 'wrong-label', 'wrong-meta', 'wrong-link', 'other',
  ]);
  await expect(page.locator('#report-message')).toBeVisible();
  await expect(page.locator('#report-charcount')).toContainText('0 / 280');
  await expect(page.locator('#report-submit')).toBeVisible();
});

test('F3. contextAutofill · active paragraph fills CONTEXT line', async ({ page }) => {
  await bootApp(page, '/index.html?q=disability&p=crpd-c-gc-6-0020');
  await page.waitForTimeout(800);
  await page.locator('#foot-report').click();
  await expect(page.locator('#report-context')).toBeVisible();
  await expect(page.locator('#report-context-detail')).toContainText(/crpd-c-gc-6-0020/);
});

test('F5. submitOk · 200 → toast + auto-close + auto-context payload', async ({ page }) => {
  let captured: any = null;
  await page.route('**/unhrdb-api/api/feedback', async (route) => {
    captured = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      body: JSON.stringify({ ok: true, ts: '2026-04-30', issueNumber: null, issueUrl: null }),
    });
  });
  await bootApp(page, '/index.html?q=disability&p=crpd-c-gc-6-0020');
  await page.waitForTimeout(800);
  await page.locator('#foot-report').click();
  await page.locator('input[value="wrong-fn"]').click();
  await page.locator('#report-message').fill('Footnote 3 should anchor after the second comma');
  await page.locator('#report-submit').click();
  // Toast appears, modal closes.
  await expect(page.locator('#feedback-toast.is-shown')).toBeVisible({ timeout: 4_000 });
  await expect(page.locator('#report-modal')).toBeHidden();
  // Server payload — auto-captured context fields are populated.
  expect(captured.kind).toBe('wrong-fn');
  expect(captured.paraId).toBe('crpd-c-gc-6-0020');
  expect(captured.docId).toBe('crpd-c-gc-6');
  expect(captured.view).toBe('search');
  expect(captured.scope).toBe('gc');
  expect(captured.url).toContain('p=crpd-c-gc-6-0020');
  expect(captured.query).toBe('disability');
  expect(typeof captured.excerpt).toBe('string');
  expect(captured.message).toContain('anchor after the second comma');
});

test('F6. submit429 · rate-limit copy + modal stays open', async ({ page }) => {
  await page.route('**/unhrdb-api/api/feedback', (route) =>
    route.fulfill({ status: 429, body: JSON.stringify({ detail: 'Too many requests' }) })
  );
  await bootApp(page);
  await page.locator('#foot-report').click();
  await page.locator('#report-message').fill('A test message');
  await page.locator('#report-submit').click();
  await expect(page.locator('#report-status')).toContainText(/try again in an hour/i);
  await expect(page.locator('#report-status')).toHaveClass(/is-err/);
  await expect(page.locator('#report-modal')).toBeVisible();
});

test('F8. escClose · Escape key closes modal', async ({ page }) => {
  await bootApp(page);
  await page.locator('#foot-report').click();
  await expect(page.locator('#report-modal')).toBeVisible();
  await page.locator('body').press('Escape');
  await expect(page.locator('#report-modal')).toBeHidden();
});

test('F9. dossierFlag · ⚐ button on dossier opens modal with context', async ({ page }) => {
  // Open a paragraph in the search dossier, click the new flag button.
  await bootApp(page, '/index.html');
  await typeQuery(page, 'disability');
  await page.locator('.result').first().click();
  await page.locator('#ws-flag').click();
  await expect(page.locator('#report-modal')).toBeVisible();
  await expect(page.locator('#report-context')).toBeVisible();
  // Detail should include the active paragraph id.
  const txt = await page.locator('#report-context-detail').textContent();
  expect(txt).toMatch(/-\d{4}/);
});

test('F10. readerFlag · ⚐ in documents reader opens modal', async ({ page }) => {
  await bootApp(page, '/index.html#documents/crpd-c-gc-6');
  await page.waitForTimeout(800);
  // Click the flag in the first paragraph row.
  await page.locator('.docs-reader-para .docs-para-flag').first().click();
  await expect(page.locator('#report-modal')).toBeVisible();
  await expect(page.locator('#report-context-detail')).toContainText(/crpd-c-gc-6/);
});

test('F11. issueLinkInToast · server returns issueUrl → toast renders link', async ({ page }) => {
  await page.route('**/unhrdb-api/api/feedback', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({
        ok: true, ts: '2026-04-30',
        issueNumber: 42,
        issueUrl: 'https://github.com/lszoszk/generalcomments-feedback/issues/42',
      }),
    })
  );
  await bootApp(page);
  await page.locator('#foot-report').click();
  await page.locator('#report-message').fill('Test issue with link');
  await page.locator('#report-submit').click();
  const toast = page.locator('#feedback-toast.is-shown');
  await expect(toast).toBeVisible();
  await expect(toast).toContainText('issue #42');
  await expect(toast.locator('a')).toHaveAttribute(
    'href',
    'https://github.com/lszoszk/generalcomments-feedback/issues/42'
  );
});

test('F12. draftSurvivesFail · network failure → text persists locally', async ({ page }) => {
  await page.route('**/unhrdb-api/api/feedback', (route) => route.abort('failed'));
  await bootApp(page);
  await page.locator('#foot-report').click();
  await page.locator('input[value="wrong-meta"]').click();
  await page.locator('#report-message').fill('Year on this doc looks wrong');
  await page.locator('#report-submit').click();
  await expect(page.locator('#report-status')).toBeVisible();
  // The draft is in localStorage even after the request bombed.
  const draft = await page.evaluate(() =>
    JSON.parse(localStorage.getItem('unhrdb_feedback_draft_v1') || 'null')
  );
  expect(draft).not.toBeNull();
  expect(draft.kind).toBe('wrong-meta');
  expect(draft.message).toContain('Year on this doc');
});
