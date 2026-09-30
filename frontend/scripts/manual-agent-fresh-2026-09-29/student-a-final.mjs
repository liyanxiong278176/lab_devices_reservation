import { chromium } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

const baseUrl = 'http://127.0.0.1:5173'
const username = 'e2e-manual-agent-qa260929a-user'
const password = 'E2e-123456'
const reservationId = 71538
const deviceName = 'e2e-manual-agent-qa260929a-device'
const artifactDir = path.resolve('.artifacts/manual-agent-fresh-2026-09-29/student-a')
const result = {
  task: 'student-a final real-page status and notification check',
  startedAt: new Date().toISOString(),
  reservationId,
  deviceName,
  responseSummary: [],
  httpErrors: [],
  pageErrors: [],
  requestFailures: [],
  checks: [],
}
await fs.mkdir(artifactDir, { recursive: true })
async function save() {
  result.updatedAt = new Date().toISOString()
  await fs.writeFile(path.join(artifactDir, 'final-page-check.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8')
}
async function waitForSettledPage(page, selector) {
  await page.locator(selector).waitFor({ state: 'visible', timeout: 20000 })
  await page.waitForFunction(() => [...document.querySelectorAll('.el-loading-mask')].every((element) => {
    const style = getComputedStyle(element)
    return style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0'
  }), { timeout: 20000 })
  await page.waitForTimeout(250)
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ locale: 'zh-CN', timezoneId: 'Asia/Shanghai', viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
page.on('console', (message) => {
  if (message.type() === 'error') result.consoleErrors ??= [], result.consoleErrors.push({ at: new Date().toISOString(), text: message.text() })
})
page.on('pageerror', (error) => result.pageErrors.push({ at: new Date().toISOString(), text: error.stack || error.message }))
page.on('requestfailed', (request) => result.requestFailures.push({ at: new Date().toISOString(), method: request.method(), url: request.url(), error: request.failure()?.errorText }))
page.on('response', async (response) => {
  if (!response.url().includes('/api/v2/')) return
  const request = response.request()
  const pathname = new URL(response.url()).pathname
  const item = { at: new Date().toISOString(), method: request.method(), path: pathname, status: response.status() }
  if (response.status() >= 400) {
    let body = ''
    try { body = (await response.text()).slice(0, 500) } catch { body = '' }
    const expected = response.status() === 401 && pathname.endsWith('/auth/me')
    result.httpErrors.push({ ...item, expected, body })
  } else {
    result.responseSummary.push(item)
  }
  await save()
})

try {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded' })
  const inputs = page.locator('.login-card .el-input__inner')
  await inputs.nth(0).fill(username)
  await inputs.nth(1).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL((current) => !['/login', '/register'].includes(current.pathname), { timeout: 20000 })

  await page.goto(`${baseUrl}/reservations/mine`, { waitUntil: 'domcontentloaded' })
  await waitForSettledPage(page, '.mine__grid .mine__cell')
  const card = page.locator('.mine__cell').filter({ hasText: deviceName }).first()
  const cardText = await card.innerText()
  const completed = /已完成/.test(cardText)
  const mineScreenshot = path.join(artifactDir, `final-my-reservation-${reservationId}.png`)
  await page.screenshot({ path: mineScreenshot, fullPage: true, animations: 'disabled' })
  result.checks.push({ name: 'my-reservation-final', at: new Date().toISOString(), url: page.url(), reservationId, completed, cardText, screenshot: mineScreenshot })
  await save()

  await page.goto(`${baseUrl}/reservations/${reservationId}`, { waitUntil: 'domcontentloaded' })
  await waitForSettledPage(page, 'body')
  const detailText = (await page.locator('body').innerText()).slice(0, 12000)
  const detailScreenshot = path.join(artifactDir, `reservation-detail-${reservationId}-final.png`)
  await page.screenshot({ path: detailScreenshot, fullPage: true, animations: 'disabled' })
  result.checks.push({ name: 'reservation-detail-final', at: new Date().toISOString(), url: page.url(), completed: /已完成/.test(detailText), pageText: detailText, screenshot: detailScreenshot })
  await save()

  await page.goto(`${baseUrl}/notifications`, { waitUntil: 'domcontentloaded' })
  await waitForSettledPage(page, '.notif-list')
  const notificationRows = await page.locator('.notif-row').evaluateAll((rows) => rows.map((row) => ({
    text: row.innerText, readState: row.getAttribute('data-read'), ariaLabel: row.getAttribute('aria-label'),
  })))
  const notificationsBody = await page.locator('body').innerText()
  const notificationsScreenshot = path.join(artifactDir, 'notifications-after-return-acceptance.png')
  await page.screenshot({ path: notificationsScreenshot, fullPage: true, animations: 'disabled' })
  result.checks.push({
    name: 'notifications-after-return-acceptance', at: new Date().toISOString(), url: page.url(),
    unreadCountText: notificationsBody.match(/\d+\s*未读提醒/)?.[0] || null,
    notificationRows, pageText: notificationsBody.slice(0, 12000), screenshot: notificationsScreenshot,
  })
  await save()
  process.stdout.write(`${JSON.stringify({
    reservation: result.checks[0],
    detail: { completed: result.checks[1].completed, tail: result.checks[1].pageText.slice(-900) },
    unreadCountText: result.checks[2].unreadCountText,
    notificationRows,
    responseSummary: result.responseSummary,
    httpErrors: result.httpErrors,
    pageErrors: result.pageErrors,
    requestFailures: result.requestFailures,
  }, null, 2)}\n`)
} catch (error) {
  result.fatalError = { at: new Date().toISOString(), text: error.stack || String(error) }
  await page.screenshot({ path: path.join(artifactDir, 'final-check-failure.png'), fullPage: true }).catch(() => {})
  await save()
  process.stderr.write(`${error.stack || error}\n`)
  process.exitCode = 1
} finally {
  await context.close().catch(() => {})
  await browser.close().catch(() => {})
}
