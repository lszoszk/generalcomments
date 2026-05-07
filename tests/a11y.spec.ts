import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { bootApp, resetWorkspace } from './_helpers';

/**
 * Accessibility audit. Runs axe-core (WCAG 2.0 + 2.1 + 2.2 AA + best-
 * practice) against the four top-level views.  Fails on any
 * `serious` or `critical` violation.  `moderate` and `minor`
 * violations are surfaced to stdout but don't fail the build.
 */

const VIEWS = [
  { hash: '',           label: 'search'    },
  { hash: '#documents', label: 'documents' },
  { hash: '#workspace', label: 'workspace' },
  { hash: '#about',     label: 'about'     },
];

for (const view of VIEWS) {
  // v19.51.2 (audit Tier 1 H6 + C2) brought serious + critical
  // violations to ZERO across all four views, so the test is now
  // wired live (was `.fixme` since the v19.6 era). The assertion
  // below is the regression guard: a future change that introduces
  // a serious/critical violation will fail this test.
  // Moderate/minor violations are surfaced to stdout but don't fail
  // the build (region landmarks etc. — semantic improvements, not
  // WCAG-AA blockers).
  test(`a11y · ${view.label}`, async ({ page }) => {
    await resetWorkspace(page);
    await bootApp(page, '/index.html' + view.hash);
    // Wait for layout + lazy paints (corpus, JUR catalog) to settle.
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.waitForTimeout(1500);
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa', 'best-practice'])
      .analyze();
    const critical = results.violations.filter((v) => ['serious', 'critical'].includes(v.impact || ''));
    if (critical.length) {
      // Human-readable summary for CI logs.
      for (const v of critical) {
        console.log(`  ${v.impact?.toUpperCase()}  ${v.id}  ${v.help}  (${v.nodes.length} nodes)`);
      }
    }
    const minor = results.violations.filter((v) => !['serious', 'critical'].includes(v.impact || ''));
    if (minor.length) {
      console.log(`  [info] ${minor.length} moderate/minor violations on ${view.label}`);
    }
    expect(critical, critical.map((v) => v.id).join(', ')).toEqual([]);
  });
}
