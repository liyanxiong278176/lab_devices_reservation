import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  // The notification operations suite needs two APIs and Prometheus/Grafana.
  testIgnore: [
    '**/reservation-special-cases.spec.ts',
    '**/reservation-joint-observe.spec.ts',
    '**/device-pool-capacity.spec.ts',
    ...(process.env.E2E_NOTIFICATION_LIVE === '1' ? [] : ['**/notification-stream-live.spec.ts']),
  ],
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never', outputFolder: '.artifacts/playwright-report' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: [
    {
      command: 'java -jar target/labflow-backend-1.0.0.jar',
      cwd: '../backend-java',
      url: process.env.E2E_API_URL || 'http://127.0.0.1:8000/api/v2/live',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: 'pnpm dev --host 127.0.0.1',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
})
