import { expect, test } from '@playwright/test';
import { bootApp, resetWorkspace, typeQuery } from './_helpers';

/**
 * Frontend query-parser regression suite.
 *
 * smoke.spec.ts test #4 (`trafficking AND children NOT (sexual)`) covers
 * the happy path for the AST evaluator in app.js (parseQuery →
 * evaluateAstToIds → paragraphMatchesAst). This file fills the gaps
 * before any work lands on top of the parser (regex dispatcher,
 * NEAR/N, etc.) — recommendation E in the v19.15 review.
 *
 * Specifically covered:
 *
 *   P1. nestedParens          — (A OR B) AND C  parses + runs
 *   P2. operatorPrecedence    — (A OR B) AND C  ≠  A OR B AND C
 *                                (verifies AND binds tighter than OR
 *                                 when parens are absent)
 *   P3. notOfPhrase           — "phrase" NOT word  shrinks the set
 *                                without losing the phrase property on
 *                                the surviving hits
 *   P4. prefixInsideBoolean   — child* AND traffic*  compiles + runs
 *                                (parser tokenisation handles the * as
 *                                a flag on the leaf, not as a literal)
 *   P5. lowercaseOperators    — `and` / `or` / `not` (lowercase) get
 *                                the same AST as their uppercase forms
 *
 * Each test runs against the live in-browser FlexSearch index — no
 * mocking — because the substring re-verification in
 * `paragraphMatchesAst` is what actually proves the AST is being
 * walked correctly. A unit test on the parser alone would silently
 * accept the v18.x bug where NOT subtrees were optimistically passed.
 *
 * Result-count thresholds are deliberately loose: the corpus grows
 * and exact equalities flake. Assertions use ratios + lower bounds,
 * matching the smoke.spec.ts convention.
 */

async function getResultCount(page: any): Promise<number> {
  const txt = (await page.locator('#result-count').textContent()) || '';
  return parseInt(txt.replace(/[^\d]/g, ''), 10) || 0;
}

test.beforeEach(async ({ page }) => {
  await resetWorkspace(page);
});

test('P1. nestedParens · (women OR girls) AND violence parses + runs', async ({ page }) => {
  await bootApp(page, '/index.html');
  await typeQuery(page, '(women OR girls) AND violence');
  const n = await getResultCount(page);
  // Loose lower bound — VAW is heavily covered across CEDAW + CRC GCs.
  expect(n).toBeGreaterThan(20);
  // Top hit must contain "violence" AND at least one of women/girls.
  // (substring re-check guarantees this — if the parser dropped the
  //  outer AND, we'd see snippets without "violence".)
  const firstSnippet = ((await page.locator('.result-text').first().textContent()) || '').toLowerCase();
  expect(firstSnippet).toContain('violence');
  expect(firstSnippet).toMatch(/wom[ae]n|girls?/);
});

test('P2. operatorPrecedence · parens override default AND-tighter', async ({ page }) => {
  // Without parens, `women OR girls AND violence` is parsed as
  //   women OR (girls AND violence)
  // which matches every "women" paragraph plus the small girls∩violence
  // intersection. With explicit parens, `(women OR girls) AND violence`
  // restricts to paragraphs that mention violence at all. The ratio
  // is the test: default-precedence query must return strictly more.
  await bootApp(page, '/index.html');
  await typeQuery(page, '(women OR girls) AND violence');
  const restricted = await getResultCount(page);
  await typeQuery(page, 'women OR girls AND violence');
  const defaulted = await getResultCount(page);
  expect(restricted).toBeGreaterThan(0);
  expect(defaulted).toBeGreaterThan(restricted);
});

test('P3. notOfPhrase · "reasonable accommodation" NOT children shrinks set', async ({ page }) => {
  // "reasonable accommodation" is everywhere in CRPD. NOT children
  // removes paragraphs that mention "children" — children appear in
  // CRPD GC6 ¶ on inclusive education etc., so the cut is non-zero.
  await bootApp(page, '/index.html');
  await typeQuery(page, '"reasonable accommodation"');
  const baseline = await getResultCount(page);
  expect(baseline).toBeGreaterThan(20);
  await typeQuery(page, '"reasonable accommodation" NOT children');
  const filtered = await getResultCount(page);
  expect(filtered).toBeGreaterThan(0);
  expect(filtered).toBeLessThan(baseline);
  // Surviving top hit still satisfies the phrase predicate.
  const firstSnippet = ((await page.locator('.result-text').first().textContent()) || '').toLowerCase();
  expect(firstSnippet).toContain('reasonable accommodation');
  // ...and the NOT predicate (substring re-check is paragraph-level,
  // so the snippet of the matching paragraph cannot contain the word).
  expect(firstSnippet).not.toMatch(/\bchildren?\b/);
});

test('P4. prefixInsideBoolean · child* AND traffic* compiles', async ({ page }) => {
  // Reproduces the prefix-wildcard tokenisation inside a boolean.
  // The trailing * is a flag on the leaf, not a literal — if the
  // tokeniser regressed, FlexSearch would receive "child*" as a
  // literal term and zero everything out.
  await bootApp(page, '/index.html');
  await typeQuery(page, 'child* AND traffic*');
  const n = await getResultCount(page);
  expect(n).toBeGreaterThan(5);                  // GR38, CRC GC13/14, etc.
  // Top hit must satisfy both stems (substring re-check on each leaf).
  const firstSnippet = ((await page.locator('.result-text').first().textContent()) || '').toLowerCase();
  expect(firstSnippet).toMatch(/child(ren|hood)?/);
  expect(firstSnippet).toMatch(/traffic(ked|king|ker)?/);
});

test('P5. lowercaseOperators · `and`/`or`/`not` parse the same as uppercase', async ({ page }) => {
  // The tokeniser lowercases each bare word and matches against
  // {'and','or','not','&','|'}. A casing regression here would silently
  // turn `women and violence` into a 3-token implicit-AND chain
  // including a literal token "and" that misses every paragraph.
  await bootApp(page, '/index.html');
  await typeQuery(page, 'women AND violence NOT discrimination');
  const upper = await getResultCount(page);
  await typeQuery(page, 'women and violence not discrimination');
  const lower = await getResultCount(page);
  expect(upper).toBeGreaterThan(0);
  // Same AST → identical candidate set → identical paginated count.
  expect(lower).toBe(upper);
});
