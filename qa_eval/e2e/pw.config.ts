import { defineConfig, devices } from '@playwright/test'
import { resolve } from 'node:path'

const root = resolve(__dirname, '../..')

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['junit', { outputFile: `${root}/qa_eval/results/e2e-junit.xml` }]],
  outputDir: `${root}/qa_eval/results/e2e-artifacts`,
  use: {
    baseURL: process.env.QA_FRONTEND_URL || 'http://127.0.0.1:5173',
    timezoneId: 'Asia/Shanghai',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
})
