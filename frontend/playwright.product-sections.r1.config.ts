import { defineConfig } from '@playwright/test';

const configuredBaseURL = process.env.R1_PRODUCT_SECTIONS_FRONTEND_URL;
const baseURL = configuredBaseURL || 'http://127.0.0.1:43191';

export default defineConfig({
  testDir: './tests',
  testMatch: 'product-sections.r1.spec.ts',
  timeout: 45_000,
  webServer: configuredBaseURL ? undefined : {
    command: 'npm run dev -- --host 127.0.0.1 --port 43191',
    url: baseURL,
    reuseExistingServer: false,
    timeout: 30_000,
  },
  use: {
    baseURL,
    browserName: 'chromium',
    headless: true,
  },
  reporter: [['list']],
});
