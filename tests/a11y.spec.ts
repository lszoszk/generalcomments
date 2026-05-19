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
    // Each a11y test wipes IndexedDB (resetWorkspace) → cold boot:
    // the full ~48 MB corpus.json + FlexSearch index build, ~13 s on
    // an idle machine and more under parallel-suite load. Triple the
    // default 60 s budget so a slow CI run can't time the test out
    // before axe even runs.
    test.slow();
    await resetWorkspace(page);
    await bootApp(page, '/index.html' + view.hash);
    // bootApp already blocks until the corpus + index are ready (it
    // waits for body[data-active-view]). We do NOT use
    // waitForLoadState('networkidle') here — the app lazy-loads JUR
    // shards continuously, so the network never idles for 500 ms and
    // the wait burns the whole test budget. A short settle for late
    // paints is enough.
    await page.waitForTimeout(1500);
    // Freeze CSS animations/transitions before the scan. Result rows
    // fade in via a `fade-up` entrance animation; axe-core's
    // color-contrast check, if it samples a row mid-fade, reads the
    // transient sub-1.0 opacity as a contrast failure — a false
    // positive (WCAG contrast applies to the settled state, and
    // prefers-reduced-motion users never see the animation). Snapping
    // animations to their end state audits what the user actually
    // reads.
    await page.addStyleTag({
      content: `*, *::before, *::after {
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        transition-duration: 0s !important;
        transition-delay: 0s !important;
      }`,
    });
    await page.waitForTimeout(200);
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa', 'best-practice'])
      .analyze();
    const critical = results.violations.filter((v) => ['serious', 'critical'].includes(v.impact || ''));
    if (critical.length) {
      // Human-readable summary for CI logs — include each failing
      // node's selector + a snippet so a violation is actionable
      // without re-running axe locally.
      for (const v of critical) {
        console.log(`  ${v.impact?.toUpperCase()}  ${v.id}  ${v.help}  (${v.nodes.length} nodes)`);
        for (const n of v.nodes) {
          console.log(`    @ ${JSON.stringify(n.target)}  ${n.html.slice(0, 100)}`);
        }
      }
    }
    const minor = results.violations.filter((v) => !['serious', 'critical'].includes(v.impact || ''));
    if (minor.length) {
      console.log(`  [info] ${minor.length} moderate/minor violations on ${view.label}`);
    }
    expect(critical, critical.map((v) => v.id).join(', ')).toEqual([]);
  });
}
