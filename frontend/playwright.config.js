import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: 0,
  outputDir: 'test-results/playwright',
  use: {
    baseURL: 'http://127.0.0.1:4273',
    headless: true,
  },
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 4273',
    port: 4273,
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
});
