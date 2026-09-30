import { chromium } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

const baseUrl = 'http://127.0.0.1:5173'
const prefix = 'e2e-manual-agent-qa260929a'
const username = `${prefix}-user`
const password = 'E2e-123456'
const reservationId = 71538
const artifactDir = path.resolve('.artifacts/manual-agent-fresh-2026-09-29/student-a')
const result = {
  task: 'student-a page follow-up: notification history and reservation detail',
  startedAt: new Date().toISOString(),
  baseUrl,
  username,
  reservationId,
  consoleErrors: [],
  pageErrors: [],
  requestFailures: [],
  httpErrors: [],
  steps: [],
}

await fs.mkdir(artifactDir, { recursive: true })
async function save() {
  result.updatedAt = new Date().toISOString()
  await fs.writeFile(path.join(artifactDir, 'follow-up-page-check.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8')
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ locale: 'zh-CN', timezoneId: 'Asia/Shanghai', viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
page.on('console', (message) => {
  if (message.type() === 'error') result.consoleErrors.push({ at: new Date().toISOString(), text: message.text() })
})
page.on('pageerror', (error) => result.pageErrors.push({ at: new Date().toISOString(), text: error.stack || error.message }))
page.on('requestfailed', (request) => result.requestFailures.push({
  at: new Date().toISOString(), method: request.method(), url: request.url(), error: request.failure()?.errorText,
}))
page.on('response', async (response) => {
  if (response.status() < 400) return
  const request = response.request()
  const pathname = new URL(response.url()).pathname
  const anonymousProbe = response.status() === 401 && pathname.endsWith('/auth/me')
  let body = ''
  if (response.url().includes('/api/')) {
    try { body = (await response.text()).slice(0, 500) } catch { body = '' }
  }
  result.httpErrors.push({
    at: new Date().toISOString(), method: request.method(), url: response.url(), status: response.status(),
    expected: anonymousProbe, reason: anonymousProbe ? 'anonymous auth probe before login' : undefined, body,
  })
  await save()
})

try {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded' })
  const inputs = page.locator('.login-card .el-input__inner')
  await inputs.nth(0).fill(username)
  await inputs.nth(1).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL((current) => !['/login', '/register'].includes(current.pathname), { timeout: 20000 })

  await page.goto(`${baseUrl}/notifications`, { waitUntil: 'domcontentloaded' })
  await page.locator('.notif-list').waitFor({ state: 'visible', timeout: 20000 })
  await page.locator('.notif-row').first().waitFor({ state: 'visible', timeout: 10000 }).catch(() => {})
  await page.waitForTimeout(600)
  const notificationRows = await page.locator('.notif-row').evaluateAll((rows) => rows.map((row) => ({
    text: row.innerText,
    readState: row.getAttribute('data-read'),
    ariaLabel: row.getAttribute('aria-label'),
  })))
  const notificationsText = await page.locator('.notif-list').innerText()
  const notificationScreenshot = path.join(artifactDir, 'notifications-after-admin.png')
  await page.screenshot({ path: notificationScreenshot, fullPage: true, animations: 'disabled' })
  result.steps.push({
    name: 'notification-history-after-admin', at: new Date().toISOString(), url: page.url(),
    unreadCountText: (await page.locator('body').innerText()).match(/\d+\s*未读提醒/)?.[0] || null,
    notificationRows, notificationsText, screenshot: notificationScreenshot,
    pageText: (await page.locator('body').innerText()).slice(0, 12000),
  })
  await save()

  await page.goto(`${baseUrl}/reservations/${reservationId}`, { waitUntil: 'domcontentloaded' })
  await page.locator('main, .reservation-detail, .detail').first().waitFor({ state: 'visible', timeout: 20000 }).catch(() => {})
  await page.waitForTimeout(500)
  const detailScreenshot = path.join(artifactDir, `reservation-detail-${reservationId}-before-return.png`)
  await page.screenshot({ path: detailScreenshot, fullPage: true, animations: 'disabled' })
  result.steps.push({
    name: 'reservation-detail-before-return', at: new Date().toISOString(), url: page.url(),
    pageText: (await page.locator('body').innerText()).slice(0, 12000), screenshot: detailScreenshot,
  })
  await save()
  process.stdout.write(`[student-a-inspect] ${JSON.stringify({
    unreadCountText: result.steps[0].unreadCountText,
    notificationRows,
    detailUrl: result.steps[1].url,
    detailText: result.steps[1].pageText.slice(-1800),
    httpErrors: result.httpErrors,
    pageErrors: result.pageErrors,
  }, null, 2)}\n`)
} catch (error) {
  result.fatalError = { at: new Date().toISOString(), text: error.stack || String(error) }
  await page.screenshot({ path: path.join(artifactDir, 'follow-up-failure.png'), fullPage: true }).catch(() => {})
  await save()
  process.stderr.write(`[student-a-inspect] ${error.stack || error}\n`)
  process.exitCode = 1
} finally {
  await context.close().catch(() => {})
  await browser.close().catch(() => {})
}
