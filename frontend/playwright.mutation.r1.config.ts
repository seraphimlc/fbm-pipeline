import { readFileSync } from 'node:fs';
import { defineConfig } from '@playwright/test';


const statePath = process.env.R1_MUTATION_FRONTEND_STATE;
if (!statePath) {
  throw new Error('R1_MUTATION_FRONTEND_STATE is required');
}

const state = JSON.parse(readFileSync(statePath, 'utf-8')) as {
  frontend_base_url: string;
  output_dir: string;
};

export default defineConfig({
  testDir: './tests',
  testMatch: 'mutation-ux.r1.spec.ts',
  fullyParallel: false,
  workers: 1,
  reporter: 'line',
  outputDir: state.output_dir,
  use: {
    baseURL: state.frontend_base_url,
    browserName: 'chromium',
    headless: true,
  },
});
