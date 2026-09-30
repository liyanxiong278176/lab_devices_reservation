import { chromium, expect } from '@playwright/test'
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const baseURL = process.env.PREVIEW_URL || 'http://127.0.0.1:18080'
const username = process.env.QA_ADMIN_USERNAME || 'e2e-multi-qa260928-admin'
const password = process.env.QA_ADMIN_PASSWORD || 'E2e-123456'
const artifactDir = process.env.QA_ARTIFACT_DIR
if (!artifactDir) throw new Error('请将 QA_ARTIFACT_DIR 设置为 run3 隔离证据目录。')
const readyPath = path.resolve(artifactDir, 'student-a.realtime.ready.json')
const logPath = path.resolve(artifactDir, 'admin-realtime-run3.jsonl')
const markerPath = path.resolve(artifactDir, 'admin.realtime-approval-complete')

mkdirSync(path.resolve(artifactDir), { recursive: true })

function log(event, data = {}) {
  const entry = { at: new Date().toISOString(), role: 'SYS_ADMIN', event, ...data }
  appendFileSync(logPath, `${JSON.stringify(entry)}\n`, 'utf8')
  console.log(JSON.stringify(entry))
}

async function capture(page, filename) {
  await page.screenshot({ path: path.resolve(artifactDir, filename), fullPage: true })
}

function reservationCard(page, reservationId) {
  const idMarker = page.locator('.approval__card-id').getByText(`#${reservationId}`, { exact: true })
  return idMarker.locator('xpath=ancestor::article[1]')
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const browserErrors = []
const serverErrors = []
page.on('pageerror', (error) => browserErrors.push(error.message))
page.on('response', (response) => {
  if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`)
})

try {
  await page.goto(`${baseURL}/login`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await page.locator('input').nth(0).fill(username)
  await page.locator('input').nth(1).fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL('**/dashboard', { timeout: 20_000 })
  await expect(page.locator('main.layout__main')).toBeVisible()
  log('admin-login-complete', { username })

  const markerDeadline = Date.now() + 10 * 60_000
  while (!existsSync(readyPath) && Date.now() < markerDeadline) {
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  if (!existsSync(readyPath)) throw new Error(`等待 A 的预约 marker 超时：${readyPath}`)
  const target = JSON.parse(readFileSync(readyPath, 'utf8'))
  const reservationId = Number(target.reservationId)
  if (!Number.isInteger(reservationId) || reservationId < 1) throw new Error('预约 marker 中 reservationId 无效。')
  if (!target.deviceName?.trim() || !target.purpose?.trim()) throw new Error('预约 marker 缺少设备名或用途，拒绝模糊定位。')
  log('target-loaded', {
    reservationId,
    deviceId: Number(target.deviceId),
    deviceName: target.deviceName,
    date: target.date,
    purpose: target.purpose,
  })

  await page.goto(`${baseURL}/approvals/pending`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { name: '待审批', exact: true })).toBeVisible()
  const selector = 'article.approval__card'
  const card = reservationCard(page, reservationId)
  const queueDeadline = Date.now() + 90_000
  let attempt = 0
  while (Date.now() < queueDeadline && (await card.count()) !== 1) {
    attempt += 1
    if (attempt === 1 || attempt % 10 === 0) {
      log('waiting-for-exact-approval-card', {
        reservationId,
        attempt,
        visibleCards: await page.locator(selector).allTextContents(),
      })
    }
    await page.waitForTimeout(1000)
    await page.reload({ waitUntil: 'networkidle' })
  }
  await expect(card).toHaveCount(1)
  await expect(card.locator('.approval__device')).toHaveText(target.deviceName)
  await expect(card).toContainText(target.purpose)
  const exactCardText = (await card.innerText()).replace(/\s+/g, ' ').trim()
  await capture(page, 'admin-realtime-run3-before.png')
  log('exact-card-confirmed', { reservationId, deviceName: target.deviceName, purpose: target.purpose, exactCardText })

  const approveResponsePromise = page.waitForResponse((response) =>
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === `/api/v2/approvals/${reservationId}/approve`,
  { timeout: 30_000 })
  await card.getByRole('button', { name: '通过', exact: true }).click()
  const approveResponse = await approveResponsePromise
  const responseBody = await approveResponse.json().catch(() => null)
  const approvedRecord = responseBody?.data ?? null
  expect(approveResponse.status()).toBe(200)
  expect(Number(approvedRecord?.id)).toBe(reservationId)
  expect(approvedRecord?.status).toBe('APPROVED')
  await expect(card).toHaveCount(0, { timeout: 20_000 })
  await capture(page, 'admin-realtime-run3-after.png')

  const result = {
    reservationId,
    deviceId: Number(target.deviceId),
    deviceName: target.deviceName,
    date: target.date,
    purpose: target.purpose,
    httpStatus: approveResponse.status(),
    reservationStatus: approvedRecord.status,
    approvedThroughUi: true,
    browserErrors,
    serverErrors,
  }
  if (browserErrors.length || serverErrors.length) {
    throw new Error(`审批成功但页面存在浏览器/服务端错误：${JSON.stringify({ browserErrors, serverErrors })}`)
  }
  writeFileSync(markerPath, `${JSON.stringify({ at: new Date().toISOString(), ...result }, null, 2)}\n`, 'utf8')
  log('realtime-approval-complete', result)
} catch (error) {
  await capture(page, 'admin-realtime-run3-failure.png').catch(() => {})
  log('failed', {
    message: error instanceof Error ? error.message : String(error),
    browserErrors,
    serverErrors,
  })
  throw error
} finally {
  await context.close()
  await browser.close()
}
