import { chromium, expect } from '@playwright/test'
import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const baseURL = process.env.PREVIEW_URL || 'http://127.0.0.1:18080'
const username = process.env.QA_STUDENT_USERNAME || 'e2e-multi-qa260928-user'
const password = process.env.QA_STUDENT_PASSWORD || 'E2e-123456'
const artifactDir = path.resolve(
  process.env.QA_ARTIFACT_DIR || '.artifacts/manual-multi-flow/e2e-multi-qa260928-run2',
)
const deviceId = Number(process.env.QA_DEVICE_A_ID || 13)
const deviceName = 'e2e-multi-qa260928-device'
const appointmentDate = process.env.QA_APPOINTMENT_DATE || '2026-09-29'
const purpose = process.env.QA_RESERVATION_PURPOSE || 'Student A 实时审批通知验证 QA260928 run2'

mkdirSync(artifactDir, { recursive: true })
const logPath = path.join(artifactDir, 'student-a-realtime.log')
const readyPath = path.join(artifactDir, 'student-a.realtime.ready.json')

function log(event, details = {}) {
  const entry = { at: new Date().toISOString(), event, ...details }
  appendFileSync(logPath, `${JSON.stringify(entry)}\n`, 'utf8')
  console.log(JSON.stringify(entry))
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
const page = await context.newPage()
const sockets = []
const frames = []
const browserErrors = []
const httpEvents = []
const failedRequests = []
page.on('websocket', (socket) => {
  const state = {
    url: socket.url(),
    openedAt: new Date().toISOString(),
    closeCount: 0,
    socketErrors: [],
    receivedFrames: [],
    sentFrames: [],
  }
  sockets.push(state)
  socket.on('framereceived', (frame) => {
    const payload = String(frame.payload)
    state.receivedFrames.push(payload)
    frames.push(payload)
    log('websocket_frame_received', { url: state.url, payload })
  })
  socket.on('framesent', (frame) => {
    const payload = String(frame.payload)
    state.sentFrames.push(payload)
    log('websocket_frame_sent', { url: state.url, payload })
  })
  socket.on('close', () => {
    state.closeCount += 1
    state.closedAt = new Date().toISOString()
    log('websocket_closed', { url: state.url, closeCount: state.closeCount })
  })
  socket.on('socketerror', (error) => {
    state.socketErrors.push(String(error))
    log('websocket_socket_error', { url: state.url, error: String(error) })
  })
  log('websocket_opened', { url: state.url, openedAt: state.openedAt })
})
page.on('response', (response) => {
  const url = response.url()
  if (!url.includes('/api/v2/auth/') && !url.includes('/api/v2/notifications/')) return
  const entry = { status: response.status(), method: response.request().method(), url }
  httpEvents.push(entry)
  log('http_response', entry)
})
page.on('requestfailed', (request) => {
  const entry = { method: request.method(), url: request.url(), failure: request.failure()?.errorText }
  failedRequests.push(entry)
  log('http_request_failed', entry)
})
page.on('pageerror', (error) => browserErrors.push(error.message))
page.on('console', (message) => {
  if (message.type() !== 'error') return
  const detail = `${message.text()} @ ${message.location().url}`
  if (detail.includes('/api/v2/auth/me') && detail.includes('401')) return
  browserErrors.push(detail)
})

try {
  await page.goto(`${baseURL}/login`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await page.locator('input').nth(0).fill(username)
  await page.locator('input').nth(1).fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL('**/dashboard', { timeout: 20_000 })
  await expect.poll(() => sockets.length, { timeout: 15_000 }).toBeGreaterThan(0)

  await page.goto(
    `${baseURL}/reservations/create?deviceId=${deviceId}&startDate=${appointmentDate}&endDate=${appointmentDate}`,
    { waitUntil: 'domcontentloaded' },
  )
  await expect(page.getByRole('heading', { name: deviceName })).toBeVisible({ timeout: 20_000 })
  await page.locator('textarea').first().fill(purpose)
  await expect(page.locator('.preflight-card')).not.toHaveClass(/is-loading/, { timeout: 30_000 })
  const safetyAck = page.getByRole('button', { name: '我已阅读并确认' })
  if (await safetyAck.isVisible().catch(() => false)) await safetyAck.click()
  await expect(page.getByRole('button', { name: '提交预约' })).toBeEnabled({ timeout: 30_000 })
  await expect(page.getByText(/1\s*天可用/)).toBeVisible({ timeout: 20_000 })

  const responsePromise = page.waitForResponse((response) =>
    response.url().includes('/api/v2/reservations')
      && response.request().method() === 'POST'
      && new URL(response.url()).pathname.endsWith('/reservations'), { timeout: 30_000 })
  await page.getByRole('button', { name: '提交预约' }).click()
  const response = await responsePromise
  expect(response.status()).toBe(201)
  await page.waitForURL(/\/reservations\/mine$/, { timeout: 20_000 })
  const card = page.locator('.mine__card').filter({ hasText: purpose }).filter({ hasText: deviceName })
  await expect(card).toHaveCount(1, { timeout: 30_000 })
  const reservationId = Number((await card.locator('.mine__card-id').innerText()).replace(/\D/g, ''))
  expect(reservationId).toBeGreaterThan(0)
  await expect(card).toContainText('待审批')
  await page.screenshot({ path: path.join(artifactDir, 'student-a-realtime-pending.png'), fullPage: true })
  const ready = { username, reservationId, deviceId, deviceName, date: appointmentDate, purpose, websocket: sockets }
  writeFileSync(readyPath, `${JSON.stringify(ready, null, 2)}\n`, 'utf8')
  log('realtime_ready', ready)

  const toast = page.locator('.el-notification').filter({ hasText: '预约申请已通过' }).first()
  await expect(toast).toBeVisible({ timeout: 180_000 })
  log('realtime_approval_toast_verified', { reservationId, websocket: sockets, websocketFrames: frames })
  await page.screenshot({ path: path.join(artifactDir, 'student-a-realtime-toast.png'), fullPage: true })

  const historyResponsePromise = page.waitForResponse((historyResponse) =>
    historyResponse.url().includes('/api/v2/notifications/mine?page=1')
      && historyResponse.request().method() === 'GET', { timeout: 30_000 })
  await page.goto(`${baseURL}/notifications`, { waitUntil: 'domcontentloaded' })
  const historyResponse = await historyResponsePromise
  expect(historyResponse.status()).toBe(200)
  const historyBody = await historyResponse.json()
  const historyRecords = historyBody?.data?.records || []
  const targetNotification = historyRecords.find((record) =>
    record.relatedId === reservationId
      && record.title === '预约申请已通过'
      && String(record.content || '').includes(deviceName))
  const historyRow = page.locator('.notif-row').filter({ hasText: '预约申请已通过' })
  await expect(historyRow.first()).toBeVisible({ timeout: 30_000 })
  await expect(historyRow.first()).toContainText(deviceName)
  expect(targetNotification).toBeTruthy()
  await page.screenshot({ path: path.join(artifactDir, 'student-a-realtime-history.png'), fullPage: true })
  if (browserErrors.length) throw new Error(`Unexpected browser errors: ${browserErrors.join(' | ')}`)
  const complete = {
    ...ready,
    realtimeToast: true,
    notificationHistory: true,
    targetNotification,
    websocketFrames: frames,
    sockets,
    httpEvents,
    failedRequests,
    browserErrors,
  }
  writeFileSync(path.join(artifactDir, 'student-a.realtime.passed.json'), `${JSON.stringify(complete, null, 2)}\n`, 'utf8')
  log('realtime_flow_passed', complete)
} catch (error) {
  const details = error instanceof Error ? { message: error.message, stack: error.stack } : { error: String(error) }
  try {
    await page.screenshot({ path: path.join(artifactDir, 'student-a-realtime-failure.png'), fullPage: true })
  } catch {
    // Preserve the first error if the browser has already closed.
  }
  writeFileSync(path.join(artifactDir, 'student-a.realtime.failure.json'), `${JSON.stringify({ ...details, browserErrors, sockets, frames, httpEvents, failedRequests }, null, 2)}\n`, 'utf8')
  log('realtime_flow_failed', { ...details, browserErrors, sockets, frames, httpEvents, failedRequests, url: page.url() })
  throw error
} finally {
  await context.close()
  await browser.close()
}
