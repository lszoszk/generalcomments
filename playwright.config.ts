import { defineConfig, devices } from '@playwright/test';

/**
 * UN Human Rights Database — Playwright smoke + integration tests.
 *
 * Adapted from the UHRI dashboard codex-pages rig (same author).
 * Production site is zero-build static; tests run against a local
 * `python3 -m http.server` over docs/.
 *
 * SCOPE we want to catch:
 *   - boot regressions (a JS error early in app.js stalls the whole
 *     site at "Loading corpus…")
 *   - search wiring (≥4-char gate, boolean parser, KWIC snippets)
 *   - dossier shape (toolbar buttons, cite menu, reading mode escape)
 *   - workspace persistence (localStorage round-trips)
 *   - 3-pane docs reader (rail + body + drawer)
 *   - report-a-problem flow (mocked POST so no real feedback rows)
 *   - API mode (?api=1) — the apiActive(scope) gate, the body= union,
 *     pagination across the 200-row API boundary
 *   - accessibility (axe-core, no critical/serious violations)
 *
 * The unhrdb-api itself is exercised by tests/contracts/api.spec.ts
 * via a separate config (playwright.contracts.config.ts) that hits
 * https://150.254.115.204/unhrdb-api/ directly.
 *
 * RUN:  npm test               (chromium, headless)
 *       npm run test:headed    (chromium, watch)
 *       npm run test:ui        (interactive Playwright UI)
 *       npm run test:contracts (live VM, separate config)
 */
export default defineConfig({
  testDir: './tests',
  testIgnore: ['**/contracts/**'],
  fullyParallel: false,        // one local server, tests share a port
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  // v19.19: raised from implicit 30 s to 60 s. The first test in each
  // browser project has to launch the browser cold; on this VM that
  // occasionally takes >30 s — the extra headroom prevents the P1
  // beforeEach timeout flake without masking real slow tests.
  timeout: 60_000,

  use: {
    baseURL: 'http://localhost:8765',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox',  use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit',   use: { ...devices['Desktop Safari']  } },
    {
      name: 'mobile',
      use: { ...devices['iPhone 13'] },
      // Mobile project skips desktop-only specs.
      testIgnore: [
        '**/contracts/**',
        '**/dossier-resize.spec.ts',
        '**/docs-reader.spec.ts',
      ],
    },
  ],

  webServer: {
    command: 'python3 -m http.server 8765 --directory docs',
    url: 'http://localhost:8765/index.html',
    reuseExistingServer: !process.env.CI,
    stdout: 'ignore',
    stderr: 'pipe',
    timeout: 10_000,
  },
});
