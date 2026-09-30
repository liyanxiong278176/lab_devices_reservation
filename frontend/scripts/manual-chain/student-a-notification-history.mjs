import { chromium, expect } from '@playwright/test'
import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const baseURL = process.env.PREVIEW_URL || 'http://127.0.0.1:18080'
const username = process.env.QA_STUDENT_USERNAME || 'e2e-multi-qa260928-user'
const password = process.env.QA_STUDENT_PASSWORD || 'E2e-123456'
const artifactDir = path.resolve(
  process.env.QA_ARTIFACT_DIR || '.artifacts/manual-multi-flow/e2e-multi-qa260928-run2',
)
const deviceName = 'e2e-multi-qa260928-device'
const reservationId = Number(process.env.QA_RESERVATION_ID || 5)
const title = '预约申请已通过'

mkdirSync(artifactDir, { recursive: true })
const logPath = path.join(artifactDir, 'student-a-notification-history.log')
function log(event, details = {}) {
  const entry = { at: new Date().toISOString(), event, ...details }
  appendFileSync(logPath, `${JSON.stringify(entry)}\n`, 'utf8')
  console.log(JSON.stringify(entry))
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
const page = await context.newPage()
const network = []
const errors = []
page.on('response', async (response) => {
  const request = response.request()
  if (!response.url().includes('/api/v2/notifications/mine')) return
  let body
  try { body = await response.json() } catch { body = null }
  network.push({ method: request.method(), status: response.status(), url: response.url(), body })
})
page.on('requestfailed', (request) => network.push({ method: request.method(), url: request.url(), failure: request.failure()?.errorText }))
page.on('pageerror', (error) => errors.push(error.message))
page.on('console', (message) => {
  if (message.type() !== 'error') return
  const location = message.location().url
  const expectedAnonymousMe401 = location.includes('/api/v2/auth/me') && message.text().includes('401')
  if (!expectedAnonymousMe401) errors.push(`${message.text()} @ ${location}`)
})

try {
  await page.goto(`${baseURL}/login`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await page.locator('input').nth(0).fill(username)
  await page.locator('input').nth(1).fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL('**/dashboard', { timeout: 20_000 })
  const historyResponse = page.waitForResponse((response) =>
    response.url().includes('/api/v2/notifications/mine')
      && response.request().method() === 'GET', { timeout: 20_000 })
  await page.goto(`${baseURL}/notifications`, { waitUntil: 'domcontentloaded' })
  await expect(page.locator('main.layout__main')).toBeVisible({ timeout: 20_000 })
  await page.locator('.notif-list').waitFor({ state: 'visible', timeout: 20_000 })
  await historyResponse
  await page.waitForTimeout(500)
  const rows = page.locator('.notif-row')
  const approval = rows.filter({ hasText: title }).filter({ hasText: deviceName })
  const found = await approval.count()
  const bodyText = await page.locator('main.layout__main').innerText()
  await page.screenshot({ path: path.join(artifactDir, 'student-a-notification-history-diagnostic.png'), fullPage: true })
  const historyRecords = network.flatMap((item) => item.body?.data?.records || [])
  const targetRecord = historyRecords.find((record) =>
    record.relatedId === reservationId && record.title === title && record.content?.includes(deviceName))
  const result = { reservationId, title, deviceName, found, targetRecord, bodyText: bodyText.slice(0, 3000), network, errors }
  writeFileSync(path.join(artifactDir, 'student-a-notification-history.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8')
  log('notification_history_diagnostic', result)
  expect(found).toBeGreaterThan(0)
  expect(targetRecord).toBeTruthy()
  expect(errors).toEqual([])
} catch (error) {
  const details = error instanceof Error ? { message: error.message, stack: error.stack } : { error: String(error) }
  try { await page.screenshot({ path: path.join(artifactDir, 'student-a-notification-history-failure.png'), fullPage: true }) } catch {}
  writeFileSync(path.join(artifactDir, 'student-a-notification-history.failure.json'), `${JSON.stringify({ ...details, network, errors }, null, 2)}\n`, 'utf8')
  log('notification_history_diagnostic_failed', { ...details, network, errors, url: page.url() })
  throw error
} finally {
  await context.close()
  await browser.close()
}
