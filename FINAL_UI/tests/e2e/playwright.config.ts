import { defineConfig, devices } from '@playwright/test';

// Server: ./run.sh --repo <repo>  (PORT=8210 for tests). baseURL from BASE_URL, default http://127.0.0.1:8210
// The suite never starts a live pipeline run (ARCH 14.2, D28).
export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  globalSetup: './helpers/global-setup.ts',
  globalTeardown: './helpers/global-teardown.ts',
  use: {
    baseURL: process.env.BASE_URL || process.env.MCAGENT_URL || 'http://127.0.0.1:8210',
    viewport: { width: 1440, height: 900 },
    trace: 'off',
    screenshot: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
});
