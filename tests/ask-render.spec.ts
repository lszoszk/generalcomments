import { expect, test } from '@playwright/test';
import { bootApp, resetWorkspace } from './_helpers';

/**
 * Ask result rendering (mocked backend on the CSP-allowed local-dev origin).
 *
 *  AR1. footnoteMarkers — the backend sends paragraph text with [[fn:N]] markers: the top
 *       match and the source cards show footnote buttons (paragraph in the local corpus) or
 *       nothing (paragraph not loaded), never the raw markers; Copy writes clean text.
 */

test.beforeEach(async ({ page }) => {
  await resetWorkspace(page);
});

test('AR1. footnoteMarkers · no raw [[fn:N]] in the answer or the sources', async ({ page, context }) => {
  try { await context.grantPermissions(['clipboard-read', 'clipboard-write']); } catch { /* WebKit */ }
  const cors = { 'access-control-allow-origin': '*', 'content-type': 'application/json' };
  await page.route('http://127.0.0.1:8767/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ status: 200, headers: cors, body: path.endsWith('/api/ask') ? JSON.stringify(ASK_FIXTURE) : '{"ok":true}' });
  });
  await bootApp(page, '/index.html?ask=' + encodeURIComponent('http://127.0.0.1:8767') + '#ask');
  await page.locator('#ask-q').fill('notification requirements for peaceful assembly');
  await page.locator('#ask-go').click();
  const answer = page.locator('.ask-answer-body');
  await expect(answer).toContainText('Having to apply for permission', { timeout: 20_000 });
  await expect(answer).not.toContainText('[[fn:');
  await expect(page.locator('.ask-source-text').first()).not.toContainText('[[fn:');
  await expect(page.locator('.ask-source-text').nth(1)).toContainText('with a marker. And more text');
  await expect(page.locator('.ask-source-text').nth(1)).not.toContainText('[[fn:');
  // ¶70 is in the local corpus: its markers are footnote buttons, as in the reader.
  expect(await answer.locator('[data-fn], .fn-mark, button').count()).toBeGreaterThan(0);
  await page.locator('.ask-source').first().locator('[data-act="copy"]').click();
  const copied = await page.evaluate(() => navigator.clipboard.readText()).catch(() => null);
  if (copied !== null) expect(copied).not.toContain('[[fn:');
});

// /api/ask response (recorded 2026-11-08); the second source is synthetic: a paragraph the
// local corpus does not hold.
const ASK_FIXTURE = {
  "query": "notification requirements for peaceful assembly",
  "answer": "70. Having to apply for permission from the authorities undercuts the idea that peaceful assembly is a basic right.[[fn:92]] Notification systems requiring that those who intend to organize a peaceful assembly must inform the authorities in advance and provide certain salient details are permissible to the extent necessary to assist the authorities in facilitating the smooth conduct of peaceful assemblies and protecting the rights of others.[[fn:93]] At the same time, this requirement must not be misused to stifle peaceful assemblies and, as in the case of other interferences with the right, must be justifiable on the grounds listed in article 21.[[fn:94]] The enforcement of notification requirements must not become an end in itself.[[fn:95]] Notification procedures should be transparent, not unduly bureaucratic,[[fn:96]] their demands on organizers must be proportionate to the potential public impact of the assembly concerned, and they should be free of charge.",
  "retrieval": {},
  "sources": [
    {
      "paraId": "ccpr-c-gc-37-0070",
      "docId": "ccpr-c-gc-37",
      "signature": "CCPR/C/GC/37",
      "committee": "CCPR",
      "year": 2020,
      "title": "GC37: the right of peaceful assembly (article 21)",
      "status": null,
      "text": "70. Having to apply for permission from the authorities undercuts the idea that peaceful assembly is a basic right.[[fn:92]] Notification systems requiring that those who intend to organize a peaceful assembly must inform the authorities in advance and provide certain salient details are permissible to the extent necessary to assist the authorities in facilitating the smooth conduct of peaceful assemblies and protecting the rights of others.[[fn:93]] At the same time, this requirement must not be misused to stifle peaceful assemblies and, as in the case of other interferences with the right, must be justifiable on the grounds listed in article 21.[[fn:94]] The enforcement of notification requirements must not become an end in itself.[[fn:95]] Notification procedures should be transparent, not unduly bureaucratic,[[fn:96]] their demands on organizers must be proportionate to the potential public impact of the assembly concerned, and they should be free of charge.",
      "match": {
        "bandLabel": "excellent",
        "score100": 91
      }
    },
    {
      "paraId": "ccpr-c-gc-37-9999",
      "docId": "ccpr-c-gc-37",
      "signature": "CCPR/C/GC/37",
      "committee": "CCPR",
      "year": 2020,
      "title": "GC37: the right of peaceful assembly (article 21)",
      "status": null,
      "text": "999. A paragraph the local corpus does not hold, with a marker.[[fn:7]] And more text.",
      "match": {
        "bandLabel": "excellent",
        "score100": 91
      }
    }
  ]
};
