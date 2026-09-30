import { chromium, expect } from '@playwright/test'
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from 'node:fs'
import path from 'node:path'

const baseURL = process.env.PREVIEW_URL || 'http://127.0.0.1:18080'
const username = process.env.QA_STUDENT_USERNAME || 'e2e-multi-qa260928-user'
const password = process.env.QA_STUDENT_PASSWORD || 'E2e-123456'
const artifactDir = path.resolve(
  process.env.QA_ARTIFACT_DIR || '.artifacts/manual-multi-flow/e2e-multi-qa260928-run2',
)
const deviceA = { id: Number(process.env.QA_DEVICE_A_ID || 13), name: 'e2e-multi-qa260928-device' }
const deviceB = { id: Number(process.env.QA_DEVICE_B_ID || 14), name: 'e2e-multi-qa260928-device-2' }
const appointmentDate = '2026-09-28'
const purpose = 'Student A 手工全链路预约与归还验证 QA260928'

mkdirSync(artifactDir, { recursive: true })
const logPath = path.join(artifactDir, 'student-a.log')
const readyPath = path.join(artifactDir, 'student-a.ready.json')
const submitGoPath = path.join(artifactDir, 'submit.go')
const returnGoPath = path.join(artifactDir, 'return.go')
const acceptanceGoPath = path.join(artifactDir, 'acceptance.go')

function log(event, details = {}) {
  const record = { at: new Date().toISOString(), event, ...details }
  appendFileSync(logPath, `${JSON.stringify(record)}\n`, 'utf8')
  console.log(JSON.stringify(record))
}

async function waitForFile(filePath, label, timeoutMs = 10 * 60_000) {
  const started = Date.now()
  while (!existsSync(filePath)) {
    if (Date.now() - started > timeoutMs) throw new Error(`Timed out waiting for ${label}: ${filePath}`)
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  log('signal_received', { label, file: path.basename(filePath) })
}

async function gotoCreate(page, device) {
  await page.goto(
    `${baseURL}/reservations/create?deviceId=${device.id}&startDate=${appointmentDate}&endDate=${appointmentDate}`,
    { waitUntil: 'domcontentloaded' },
  )
  await expect(page.getByRole('heading', { name: device.name })).toBeVisible({ timeout: 20_000 })
  await page.locator('textarea').first().fill(purpose)
  await expect(page.locator('.preflight-card')).not.toHaveClass(/is-loading/, { timeout: 30_000 })

  const acknowledge = page.getByRole('button', { name: '我已阅读并确认' })
  if (await acknowledge.isVisible().catch(() => false)) {
    await acknowledge.click()
    log('safety_acknowledged', { deviceId: device.id })
  }

  const submit = page.getByRole('button', { name: '提交预约' })
  await expect(submit).toBeEnabled({ timeout: 30_000 })
  await expect(page.getByText(/1\s*天可用/)).toBeVisible({ timeout: 20_000 })
  return submit
}

function findReservationCard(page, deviceName) {
  return page.locator('.mine__card').filter({ hasText: deviceName }).filter({ hasText: purpose })
}

async function submitBooking(page, device) {
  const submit = await gotoCreate(page, device)
  const responsePromise = page.waitForResponse((response) => {
    const request = response.request()
    return response.url().includes('/api/v2/reservations')
      && request.method() === 'POST'
      && new URL(response.url()).pathname.endsWith('/reservations')
  }, { timeout: 30_000 })
  await submit.click()
  const response = await responsePromise
  log('booking_response', { deviceId: device.id, status: response.status() })
  return response
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
const page = await context.newPage()
const browserErrors = []
const websocketUrls = []
const websocketFrames = []
page.on('pageerror', (error) => browserErrors.push(error.message))
page.on('console', (message) => {
  if (message.type() === 'error') browserErrors.push(`${message.text()} @ ${message.location().url}`)
})
page.on('websocket', (socket) => {
  websocketUrls.push(socket.url())
  socket.on('framereceived', (frame) => websocketFrames.push(String(frame.payload)))
  log('websocket_connected', { url: socket.url() })
})
page.on('dialog', async (dialog) => {
  browserErrors.push(`Unexpected browser dialog: ${dialog.message()}`)
  await dialog.dismiss()
})

try {
  await page.goto(`${baseURL}/login`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await page.locator('input').nth(0).fill(username)
  await page.locator('input').nth(1).fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL('**/dashboard', { timeout: 20_000 })
  await expect(page.locator('main.layout__main')).toBeVisible()
  log('login_success', { username, url: page.url() })

  const firstSubmit = await gotoCreate(page, deviceA)
  writeFileSync(readyPath, `${JSON.stringify({ username, deviceId: deviceA.id, deviceName: deviceA.name, date: appointmentDate, readyToSubmit: true }, null, 2)}\n`, 'utf8')
  log('ready_to_race', { deviceId: deviceA.id, date: appointmentDate, file: path.basename(readyPath) })
  await waitForFile(submitGoPath, 'submit.go')
  const firstResponsePromise = page.waitForResponse((response) => {
    const request = response.request()
    return response.url().includes('/api/v2/reservations')
      && request.method() === 'POST'
      && new URL(response.url()).pathname.endsWith('/reservations')
  }, { timeout: 30_000 })
  await firstSubmit.click()
  const firstResponse = await firstResponsePromise
  log('booking_response', { deviceId: deviceA.id, status: firstResponse.status() })
  let bookedDevice = deviceA
  if (firstResponse.status() === 409) {
    const conflictText = await page.locator('body').innerText()
    await page.screenshot({ path: path.join(artifactDir, 'student-a-conflict-device-a.png'), fullPage: true })
    log('booking_conflict', { deviceId: deviceA.id, evidence: conflictText.slice(-700) })
    const fallbackResponse = await submitBooking(page, deviceB)
    expect(fallbackResponse.status()).toBe(201)
    bookedDevice = deviceB
  } else {
    expect(firstResponse.status()).toBe(201)
    await page.waitForURL(/\/reservations\/mine$/, { timeout: 20_000 })
  }

  await expect(page).toHaveURL(/\/reservations\/mine$/)
  const ownCard = findReservationCard(page, bookedDevice.name)
  await expect(ownCard).toHaveCount(1, { timeout: 20_000 })
  const cardId = await ownCard.locator('.mine__card-id').innerText()
  const reservationId = Number(cardId.replace(/[^0-9]/g, ''))
  expect(Number.isInteger(reservationId) && reservationId > 0).toBeTruthy()
  await page.screenshot({ path: path.join(artifactDir, 'student-a-booked.png'), fullPage: true })
  const booked = { username, reservationId, deviceId: bookedDevice.id, deviceName: bookedDevice.name, date: appointmentDate, purpose }
  writeFileSync(path.join(artifactDir, 'student-a.booked.json'), `${JSON.stringify(booked, null, 2)}\n`, 'utf8')
  log('booking_saved', booked)

  log('awaiting_admin_approval', { reservationId, websocketConnected: websocketUrls.length > 0 })

  // Keep the live browser connected while the administrator processes the request.
  await expect(page).toHaveURL(/\/reservations\/mine$/)
  const notificationToast = page.locator('.el-notification').filter({ hasText: '预约申请已通过' }).first()
  await expect(notificationToast).toBeVisible({ timeout: 180_000 })
  log('approval_realtime_toast_visible', { reservationId, websocketConnected: websocketUrls.length > 0, websocketFrames })
  await page.screenshot({ path: path.join(artifactDir, 'student-a-approval-toast.png'), fullPage: true })

  await page.goto(`${baseURL}/notifications`, { waitUntil: 'domcontentloaded' })
  const approvalHistoryRow = page.locator('.notif-row').filter({ hasText: '预约申请已通过' })
  await expect(approvalHistoryRow.first()).toBeVisible({ timeout: 30_000 })
  await expect(approvalHistoryRow.first()).toContainText(bookedDevice.name)
  await page.screenshot({ path: path.join(artifactDir, 'student-a-approval-history.png'), fullPage: true })
  log('approval_history_verified', { reservationId, title: '预约申请已通过', deviceName: bookedDevice.name })

  await waitForFile(returnGoPath, 'return.go')
  await page.goto(`${baseURL}/reservations/mine`, { waitUntil: 'domcontentloaded' })
  const activeCard = findReservationCard(page, bookedDevice.name)
  await expect(activeCard).toContainText('使用中', { timeout: 30_000 })
  const returnButton = activeCard.getByRole('button', { name: '归还' })
  await expect(returnButton).toBeVisible()
  await returnButton.click()
  const returnDialog = page.getByRole('dialog', { name: '提交归还' })
  await expect(returnDialog).toBeVisible()
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jvuoAAAAASUVORK5CYII=',
    'base64',
  )
  await returnDialog.locator('input[type="file"]').setInputFiles({
    name: 'student-a-return-1x1.png',
    mimeType: 'image/png',
    buffer: png,
  })
  await expect(returnDialog.getByText('1 张已选择')).toBeVisible()
  const returnResponsePromise = page.waitForResponse((response) =>
    response.url().includes(`/api/v2/reservations/${reservationId}/return`)
      && response.request().method() === 'POST', { timeout: 30_000 })
  await returnDialog.getByRole('button', { name: '确认归还' }).click()
  const returnResponse = await returnResponsePromise
  expect(returnResponse.status()).toBe(200)
  await expect(activeCard).toContainText('待负责人验收', { timeout: 30_000 })
  await page.screenshot({ path: path.join(artifactDir, 'student-a-return-pending.png'), fullPage: true })
  const returned = { ...booked, returnCondition: 'NORMAL', returnImage: 'student-a-return-1x1.png', status: 'RETURN_PENDING' }
  writeFileSync(path.join(artifactDir, 'student-a.returned.json'), `${JSON.stringify(returned, null, 2)}\n`, 'utf8')
  log('return_submitted', { ...returned, httpStatus: returnResponse.status() })

  await waitForFile(acceptanceGoPath, 'acceptance.go', 10 * 60_000)
  await page.goto(`${baseURL}/reservations/mine`, { waitUntil: 'domcontentloaded' })
  const completedCard = findReservationCard(page, bookedDevice.name)
  await expect(completedCard).toContainText('已完成', { timeout: 60_000 })
  await completedCard.getByRole('button', { name: '详情' }).click()
  await expect(page.locator('.rsv-detail')).toContainText('负责人已完成验收', { timeout: 30_000 })
  await page.screenshot({ path: path.join(artifactDir, 'student-a-completed-detail.png'), fullPage: true })
  const completed = { ...booked, status: 'COMPLETED', finalAcceptance: 'verified in reservation details' }
  writeFileSync(path.join(artifactDir, 'student-a.completed.json'), `${JSON.stringify(completed, null, 2)}\n`, 'utf8')
  log('complete_chain_verified', completed)

  if (browserErrors.length) throw new Error(`Browser errors: ${browserErrors.slice(0, 10).join(' | ')}`)
  log('student_a_passed', { reservationId, websocketConnected: websocketUrls.length > 0, browserErrors: 0 })
} catch (error) {
  const details = error instanceof Error ? { message: error.message, stack: error.stack } : { error: String(error) }
  try {
    await page.screenshot({ path: path.join(artifactDir, 'student-a-failure.png'), fullPage: true })
  } catch {
    // Keep the original failure if the browser is already unavailable.
  }
  log('student_a_failed', { ...details, url: page.url(), browserErrors, websocketUrls, websocketFrames })
  writeFileSync(path.join(artifactDir, 'student-a.failure.json'), `${JSON.stringify(details, null, 2)}\n`, 'utf8')
  throw error
} finally {
  await context.close()
  await browser.close()
}
