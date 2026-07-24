import { defineConfig } from '@playwright/test';


export default defineConfig({
  testDir: './tests',
  testMatch: 'workflow-actions.r1.spec.ts',
  fullyParallel: false,
  workers: 1,
  reporter: 'line',
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 43190',
    url: 'http://127.0.0.1:43190',
    reuseExistingServer: false,
    timeout: 30_000,
  },
  use: {
    baseURL: 'http://127.0.0.1:43190',
    browserName: 'chromium',
    headless: true,
  },
});
