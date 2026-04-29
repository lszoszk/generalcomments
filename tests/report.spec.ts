import { expect, test } from '@playwright/test';
import { bootApp, resetWorkspace } from './_helpers';

/**
 * Report-a-problem flow (v19.3). Mocks the /api/feedback POST so we
 * don't pollute the production VM log on every test run.
 *
 *  F1. footerLinkVisible — the link is present in the footer
 *  F2. modalOpens         — clicking opens the modal with all 4 kinds
 *  F3. contextAutofill    — active paragraph fills CONTEXT line
 *  F4. validation         — < 4 char message blocks submit
 *  F5. submitOk           — happy path: status flips to is-ok, modal closes
 *  F6. submit429          — rate-limited gives a tailored "retry in an hour"
 *  F7. submit422          — server-side validation surfaces a tailored message
 *  F8. escClose           — Esc closes the modal
 */

test.beforeEach(async ({ page }) => {
  await resetWorkspace(page);
});

test('F1. footerLinkVisible · "Report a problem" rendered in footer', async ({ page }) => {
  await bootApp(page);
  await expect(page.locator('#foot-report')).toBeVisible();
});

test('F2. modalOpens · click button → 4 kinds + message + email + buttons', async ({ page }) => {
  await bootApp(page);
  await page.locator('#foot-report').click();
  await expect(page.locator('#report-modal')).toBeVisible();
  const kinds = await page.locator('.report-kind input[name="kind"]').evaluateAll((els) =>
    els.map((el) => (el as HTMLInputElement).value)
  );
  expect(kinds).toEqual(['bug', 'data', 'feature', 'other']);
  await expect(page.locator('#report-message')).toBeVisible();
  await expect(page.locator('#report-contact')).toBeVisible();
  await expect(page.locator('#report-submit')).toBeVisible();
});

test('F3. contextAutofill · active paragraph fills CONTEXT line', async ({ page }) => {
  await bootApp(page, '/index.html?q=disability&p=crpd-c-gc-6-0020');
  await page.waitForTimeout(800);
  await page.locator('#foot-report').click();
  await expect(page.locator('#report-context')).toBeVisible();
  await expect(page.locator('#report-context-detail')).toContainText(/crpd-c-gc-6-0020/);
});

test('F4. validation · message < 4 chars blocks submit', async ({ page }) => {
  await bootApp(page);
  // Mock the API so a real network call doesn't slip through.
  await page.route('**/unhrdb-api/api/feedback', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify({ ok: true, ts: 'mocked' }) })
  );
  await page.locator('#foot-report').click();
  await page.locator('#report-message').fill('no');
  await page.locator('#report-submit').click();
  // Frontend's own pre-flight stops the submit; modal stays open.
  await expect(page.locator('#report-modal')).toBeVisible();
  await expect(page.locator('#report-status')).toContainText(/too short/i);
});

test('F5. submitOk · 200 response → success copy + auto-close', async ({ page }) => {
  let captured: any = null;
  await page.route('**/unhrdb-api/api/feedback', async (route) => {
    captured = route.request().postDataJSON();
    await route.fulfill({ status: 200, body: JSON.stringify({ ok: true, ts: '2026-04-29' }) });
  });
  await bootApp(page);
  await page.locator('#foot-report').click();
  await page.locator('input[value="feature"]').click();
  await page.locator('#report-message').fill('Smoke test — feature request from playwright');
  await page.locator('#report-contact').fill('smoke@test.local');
  await page.locator('#report-submit').click();
  await expect(page.locator('#report-status')).toContainText(/Thanks/i);
  await expect(page.locator('#report-status')).toHaveClass(/is-ok/);
  // Auto-close ≈ 1.4 s
  await page.waitForTimeout(1700);
  await expect(page.locator('#report-modal')).toBeHidden();
  // Server payload assertions
  expect(captured.kind).toBe('feature');
  expect(captured.message).toContain('Smoke test');
  expect(captured.contact).toBe('smoke@test.local');
});

test('F6. submit429 · rate-limit shows tailored copy, modal stays open', async ({ page }) => {
  await page.route('**/unhrdb-api/api/feedback', (route) =>
    route.fulfill({ status: 429, body: JSON.stringify({ detail: 'Too many requests' }) })
  );
  await bootApp(page);
  await page.locator('#foot-report').click();
  await page.locator('#report-message').fill('A perfectly long enough message');
  await page.locator('#report-submit').click();
  await expect(page.locator('#report-status')).toContainText(/retry in an hour/i);
  await expect(page.locator('#report-status')).toHaveClass(/is-err/);
  await expect(page.locator('#report-modal')).toBeVisible();
});

test('F7. submit422 · validation error surfaces a tailored message', async ({ page }) => {
  await page.route('**/unhrdb-api/api/feedback', (route) =>
    route.fulfill({ status: 422, body: JSON.stringify({ detail: 'bad' }) })
  );
  await bootApp(page);
  await page.locator('#foot-report').click();
  await page.locator('#report-message').fill('A perfectly long enough message');
  await page.locator('#report-submit').click();
  await expect(page.locator('#report-status')).toContainText(/shortening/i);
  await expect(page.locator('#report-status')).toHaveClass(/is-err/);
});

test('F8. escClose · Escape key closes modal', async ({ page }) => {
  await bootApp(page);
  await page.locator('#foot-report').click();
  await expect(page.locator('#report-modal')).toBeVisible();
  await page.locator('body').press('Escape');
  await expect(page.locator('#report-modal')).toBeHidden();
});
