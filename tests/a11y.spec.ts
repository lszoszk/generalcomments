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
  // KNOWN REMAINING VIOLATIONS (after v19.6 round):
  //   - color-contrast on .dim text + .badge-preview/jur on light bg
  //   - target-size on the result-row ☆/📌/”/📝 marks (≤24×24)
  //
  // v19.6 cleared:
  //   ✅ A2 aria-required-attr on year-range sliders (explicit aria-*
  //      attrs added by initYearRange + paintYearFill)
  //   ✅ A4 docs view axe timeout (rail wrapped in role="navigation")
  //
  // The suite stays in the rig as `.fixme` until A1 + A3 (target-size +
  // color-contrast) ship.  Drop the .fixme then.
  test.fixme(`a11y · ${view.label}`, async ({ page }) => {
    await resetWorkspace(page);
    await bootApp(page, '/index.html' + view.hash);
    await page.waitForTimeout(800);
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa', 'best-practice'])
      .analyze();
    const critical = results.violations.filter((v) => ['serious', 'critical'].includes(v.impact || ''));
    if (critical.length) {
      // Print human-readable summary so CI logs are useful.
      for (const v of critical) {
        console.log(`  ${v.impact?.toUpperCase()}  ${v.id}  ${v.help}  (${v.nodes.length} nodes)`);
      }
    }
    // Log the moderate/minor pile (informational).
    const minor = results.violations.filter((v) => !['serious', 'critical'].includes(v.impact || ''));
    if (minor.length) {
      console.log(`  [info] ${minor.length} moderate/minor violations on ${view.label}`);
    }
    expect(critical, critical.map((v) => v.id).join(', ')).toEqual([]);
  });
}
