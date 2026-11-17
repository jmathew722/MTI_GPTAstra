import { defineConfig, devices } from '@playwright/test';

// Server: cd pipeline_app/webapp && PORT=8200 ./run.sh
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
    baseURL: process.env.BASE_URL || 'http://127.0.0.1:8200',
    viewport: { width: 1440, height: 900 },
    trace: 'off',
    screenshot: 'off',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
});
