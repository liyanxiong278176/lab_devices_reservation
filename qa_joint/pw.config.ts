const path = require('node:path')
const { defineConfig } = require('../frontend/node_modules/@playwright/test')
const qaRoot = __dirname

module.exports = defineConfig({
  testDir: './steps',
  testMatch: '**/*.spec.cjs',
  fullyParallel: false,
  workers: 1,
  timeout: 15 * 60 * 1000,
  expect: { timeout: 15_000 },
  reporter: [
    ['list'],
    ['json', { outputFile: path.join(qaRoot, 'results', 'playwright.json') }],
  ],
  outputDir: path.join(qaRoot, 'results', 'test-results'),
  use: {
    baseURL: 'http://127.0.0.1:5173',
    browserName: 'chromium',
    viewport: { width: 1440, height: 1000 },
    actionTimeout: 30_000,
    trace: 'retain-on-failure',
    screenshot: 'off',
    video: 'off',
  },
})
