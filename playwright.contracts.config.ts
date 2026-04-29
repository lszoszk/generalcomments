import { defineConfig } from '@playwright/test';

/**
 * Contract tests against the LIVE unhrdb-api on the VM.
 *
 *   https://150.254.115.204/unhrdb-api
 *
 * No local web server. Tests fetch endpoints directly with the Node
 * Playwright APIRequestContext and assert response shape, status
 * codes, Cache-Control headers, CORS allow-origin, performance budgets.
 *
 * RUN:  npm run test:contracts
 */
export default defineConfig({
  testDir: './tests/contracts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 1,
  workers: 4,
  reporter: process.env.CI ? 'github' : 'list',

  use: {
    baseURL: 'https://150.254.115.204/unhrdb-api',
    extraHTTPHeaders: {
      // Mimic the GH-Pages origin so we exercise the CORS path.
      'origin': 'https://lszoszk.github.io',
    },
    ignoreHTTPSErrors: true,         // self-signed / IP-cert
  },

  projects: [{ name: 'contracts' }],
});
