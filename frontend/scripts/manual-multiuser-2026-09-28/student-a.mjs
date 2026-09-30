import { chromium, expect } from '@playwright/test'
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const baseURL = process.env.PREVIEW_URL || 'http://127.0.0.1:5173'
const credentialsPath = 'C:/Users/A2781/AppData/Local/Temp/lab-reservation-manual-e2e-credentials-20260928.json'
const artifactDir = path.resolve('.artifacts/manual-multiuser-2026-09-28')
const date = '2026-09-28'
const deviceA = { id: 11628, name: 'e2e-qa260928-multi9x3-device' }
const deviceB = { id: 11629, name: 'e2e-qa260928-multi9x3-device-2' }
const initialDevice = process.env.QA_BOOK_DEVICE_B === '1' ? deviceB : deviceA
const purpose = 'Student A 多用户预约审批交接归还链路 e2e-qa260928-multi9x3'
const submitMarker = path.join(artifactDir, 'submit-go.json')
const handoverMarker = path.join(artifactDir, 'admin-handover-done.json')
const completionMarker = path.join(artifactDir, process.env.QA_ACCEPTANCE_MARKER || 'admin-completed.json')
const evidencePath = path.join(artifactDir, 'evidence.png')

if (!existsSync(credentialsPath)) throw new Error('Manual test credentials file is missing.')
const credentials = JSON.parse(readFileSync(credentialsPath, 'utf8'))
if (typeof credentials.username !== 'string' || typeof credentials.password !== 'string') {
  throw new Error('Manual test credentials file has an invalid shape.')
}

mkdirSync(artifactDir, { recursive: true })
const logPath = path.join(artifactDir, 'student-a.log.jsonl')
const readyPath = path.join(artifactDir, 'student-a-ready.json')
const bookingPath = path.join(artifactDir, 'student-a-booking.json')
const returnedPath = path.join(artifactDir, 'student-a-returned.json')
const unexpectedHTTP = []
const httpStatuses = []
const requestFailures = []
const browserErrors = []
const websocketEvents = []
const websocketFrames = []

function redact(value) {
  if (typeof value === 'string') {
    let text = value
    for (const secret of [credentials.password, credentials.username]) {
      if (secret) text = text.split(secret).join('[REDACTED]')
    }
    return text
  }
  if (Array.isArray(value)) return value.map(redact)
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, redact(item)]))
  }
  return value
}

function log(event, fields = {}) {
  const record = redact({ at: new Date().toISOString(), event, ...fields })
  appendFileSync(logPath, `${JSON.stringify(record)}\n`, 'utf8')
  console.log(JSON.stringify(record))
}

function writeJSON(file, data) {
  writeFileSync(file, `${JSON.stringify(redact(data), null, 2)}\n`, 'utf8')
}

async function waitForMarker(file, label, timeoutMs = 15 * 60_000) {
  const started = Date.now()
  while (!existsSync(file)) {
    if (Date.now() - started > timeoutMs) throw new Error(`Timed out waiting for ${label}.`)
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  log('marker_received', { marker: path.basename(file), label })
}

async function openReservationForm(page, device) {
  await page.goto(
    `${baseURL}/reservations/create?deviceId=${device.id}&startDate=${date}&endDate=${date}`,
    { waitUntil: 'domcontentloaded' },
  )
  await expect(page.getByRole('heading', { name: device.name })).toBeVisible({ timeout: 20_000 })
  await page.locator('textarea').first().fill(purpose)
  await expect(page.locator('.preflight-card')).not.toHaveClass(/is-loading/, { timeout: 30_000 })
  const safetyAcknowledgement = page.getByRole('button', { name: '我已阅读并确认' })
  if (await safetyAcknowledgement.isVisible().catch(() => false)) {
    await safetyAcknowledgement.click()
    log('safety_acknowledged', { deviceId: device.id })
  }
  await expect(page.getByText(/1\s*天可用/)).toBeVisible({ timeout: 20_000 })
  const submit = page.getByRole('button', { name: '提交预约' })
  await expect(submit).toBeEnabled({ timeout: 30_000 })
  return submit
}

function reservationCard(page, device) {
  return page.locator('.mine__card').filter({ hasText: device.name }).filter({ hasText: purpose })
}

async function createBooking(page, device) {
  const submit = await openReservationForm(page, device)
  return submitBooking(page, device, submit)
}

async function submitBooking(page, device, submit) {
  const responsePromise = page.waitForResponse((response) =>
    response.url().includes('/api/v2/reservations')
      && response.request().method() === 'POST'
      && new URL(response.url()).pathname.endsWith('/reservations'), { timeout: 30_000 })
  await submit.click()
  const response = await responsePromise
  let body = null
  try { body = await response.json() } catch { body = null }
  const created = body?.data?.created || []
  const reservationId = Number(created[0]?.id || 0)
  log('reservation_submission', {
    deviceId: device.id,
    responseStatus: response.status(),
    createdCount: created.length,
    reservationId: reservationId || null,
    expectedConflict: response.status() === 409,
  })
  return { response, reservationId }
}

function decodeNotificationFrame(frame) {
  try {
    const value = JSON.parse(String(frame.payload))
    return {
      id: value.id,
      type: value.type,
      title: value.title,
      relatedId: value.relatedId,
      relatedType: value.relatedType,
      receivedAt: new Date().toISOString(),
    }
  } catch {
    return { unparsedFrameLength: String(frame.payload).length, receivedAt: new Date().toISOString() }
  }
}

mkdirSync(path.dirname(evidencePath), { recursive: true })
if (!existsSync(evidencePath)) {
  writeFileSync(
    evidencePath,
    Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jvuoAAAAASUVORK5CYII=', 'base64'),
  )
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
const page = await context.newPage()
page.on('websocket', (socket) => {
  const safeSocketURL = (() => {
    try {
      const parsed = new URL(socket.url())
      parsed.search = ''
      parsed.hash = ''
      return parsed.toString()
    } catch {
      return '[unparseable websocket URL]'
    }
  })()
  const state = {
    url: safeSocketURL,
    openedAt: new Date().toISOString(),
    closeCount: 0,
    errors: [],
    receivedFrames: [],
    sentFrames: [],
  }
  websocketEvents.push(state)
  socket.on('framereceived', (frame) => {
    const parsed = decodeNotificationFrame(frame)
    state.receivedFrames.push(parsed)
    websocketFrames.push(parsed)
    log('websocket_frame_received', { socket: state.url, frame: parsed })
  })
  socket.on('framesent', (frame) => {
    let length = String(frame.payload).length
    state.sentFrames.push({ length, sentAt: new Date().toISOString() })
    log('websocket_frame_sent', { socket: state.url, length })
  })
  socket.on('close', () => {
    state.closeCount += 1
    state.closedAt = new Date().toISOString()
    log('websocket_closed', { socket: state.url, closeCount: state.closeCount })
  })
  socket.on('socketerror', (error) => {
    state.errors.push(redact(String(error)))
    log('websocket_error', { socket: state.url, error: String(error) })
  })
  log('websocket_opened', { socket: state.url, openedAt: state.openedAt })
})
page.on('response', (response) => {
  const url = new URL(response.url())
  const isExpectedAnonymousMe401 = response.status() === 401 && url.pathname.endsWith('/api/v2/auth/me')
  const isExpectedRaceConflict = response.status() === 409
    && response.request().method() === 'POST'
    && url.pathname.endsWith('/api/v2/reservations')
  const entry = {
    status: response.status(),
    method: response.request().method(),
    path: url.pathname,
    expected: isExpectedAnonymousMe401 || isExpectedRaceConflict,
  }
  httpStatuses.push(entry)
  if (response.status() >= 400 && !entry.expected) unexpectedHTTP.push(entry)
  if (response.status() >= 400) log('http_status', entry)
})
page.on('requestfailed', (request) => {
  const url = new URL(request.url())
  const entry = { method: request.method(), path: url.pathname, failure: request.failure()?.errorText }
  requestFailures.push(entry)
  log('request_failed', entry)
})
page.on('pageerror', (error) => {
  browserErrors.push(redact(error.message))
  log('page_error', { message: error.message })
})
page.on('console', (message) => {
  if (message.type() !== 'error') return
  const location = message.location().url || ''
  const expectedAnonymousMe401 = location.includes('/api/v2/auth/me') && message.text().includes('401')
  if (expectedAnonymousMe401) return
  const detail = `${message.text()} @ ${location}`
  browserErrors.push(redact(detail))
  log('console_error', { message: detail })
})

let booking = null
let selectedDevice = initialDevice
try {
  await page.goto(`${baseURL}/login`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible({ timeout: 20_000 })
  await page.locator('input').nth(0).fill(credentials.username)
  await page.locator('input').nth(1).fill(credentials.password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL('**/dashboard', { timeout: 20_000 })
  await expect(page.locator('main.layout__main')).toBeVisible()
  await expect.poll(() => websocketEvents.length, { timeout: 20_000 }).toBeGreaterThan(0)
  await log('login_complete', { url: page.url(), websocketCount: websocketEvents.length })

  const submitButton = await openReservationForm(page, initialDevice)
  await page.screenshot({ path: path.join(artifactDir, 'student-a-ready.png'), fullPage: true })
  writeJSON(readyPath, {
    role: 'student-a',
    deviceId: initialDevice.id,
    deviceName: initialDevice.name,
    date,
    readyToSubmit: true,
    screenshotPath: path.join(artifactDir, 'student-a-ready.png'),
  })
  log('ready_to_submit', { deviceId: initialDevice.id, date, readyFile: path.basename(readyPath) })
  if (process.env.QA_SKIP_SUBMIT_BARRIER !== '1') {
    await waitForMarker(submitMarker, 'parallel submit barrier')
  }

  // Submit from the exact preflight-ready page used to publish the barrier.
  // Reopening the form here would refresh availability and hide the intended race.
  const first = await submitBooking(page, initialDevice, submitButton)
  if (first.response.status() === 409) {
    await page.screenshot({ path: path.join(artifactDir, `student-a-device-${initialDevice.id}-conflict.png`), fullPage: true })
    if (initialDevice.id !== deviceA.id) {
      throw new Error(`Alternate device booking also returned HTTP 409; reservationId=${first.reservationId || 'none'}.`)
    }
    selectedDevice = deviceB
    const fallback = await createBooking(page, deviceB)
    if (fallback.response.status() !== 201 || fallback.reservationId <= 0) {
      throw new Error(`Fallback booking returned unexpected HTTP ${fallback.response.status()}.`)
    }
    booking = { device: deviceB, responseStatus: fallback.response.status(), reservationId: fallback.reservationId }
  } else {
    if (first.response.status() !== 201 || first.reservationId <= 0) {
      throw new Error(`Initial booking returned unexpected HTTP ${first.response.status()}.`)
    }
    booking = { device: initialDevice, responseStatus: first.response.status(), reservationId: first.reservationId }
    await page.waitForURL(/\/reservations\/mine$/, { timeout: 20_000 })
  }

  const ownCard = reservationCard(page, booking.device)
  await expect(ownCard).toHaveCount(1, { timeout: 30_000 })
  await expect(ownCard.locator('.mine__card-id')).toHaveText(`#${booking.reservationId}`)
  await page.screenshot({ path: path.join(artifactDir, 'student-a-booking.png'), fullPage: true })
  const bookingRecord = {
    role: 'student-a',
    deviceId: booking.device.id,
    deviceName: booking.device.name,
    date,
    responseStatus: booking.responseStatus,
    reservationId: booking.reservationId,
    screenshotPaths: [
      path.join(artifactDir, 'student-a-ready.png'),
      path.join(artifactDir, 'student-a-booking.png'),
      ...(selectedDevice.id !== initialDevice.id ? [path.join(artifactDir, `student-a-device-${initialDevice.id}-conflict.png`)] : []),
    ],
  }
  writeJSON(bookingPath, bookingRecord)
  log('booking_confirmed_in_ui', { ...bookingRecord, status: (await ownCard.innerText()).slice(0, 80) })

  const approvalToast = page.locator('.el-notification').filter({ hasText: '预约申请已通过' }).first()
  await expect(approvalToast).toBeVisible({ timeout: 180_000 })
  await page.screenshot({ path: path.join(artifactDir, 'student-a-approval-toast.png'), fullPage: true })
  log('approval_toast_received', { reservationId: booking.reservationId, websocketFrames })

  const approvalHistoryPromise = page.waitForResponse((response) =>
    response.url().includes('/api/v2/notifications/mine?page=1')
      && response.request().method() === 'GET', { timeout: 30_000 })
  await page.goto(`${baseURL}/notifications`, { waitUntil: 'domcontentloaded' })
  const historyResponse = await approvalHistoryPromise
  const historyBody = await historyResponse.json()
  const historyRecords = historyBody?.data?.records || []
  const approvalRecord = historyRecords.find((item) =>
    item.relatedId === booking.reservationId
      && item.title === '预约申请已通过'
      && String(item.content || '').includes(booking.device.name))
  const approvalRow = page.locator('.notif-row').filter({ hasText: '预约申请已通过' }).filter({ hasText: booking.device.name })
  await expect(approvalRow.first()).toBeVisible({ timeout: 30_000 })
  expect(approvalRecord).toBeTruthy()
  await page.screenshot({ path: path.join(artifactDir, 'student-a-approval-history.png'), fullPage: true })
  log('approval_history_verified', {
    reservationId: booking.reservationId,
    httpStatus: historyResponse.status(),
    notificationId: approvalRecord.id,
    title: approvalRecord.title,
  })

  await waitForMarker(handoverMarker, 'admin handover completion')
  await page.goto(`${baseURL}/reservations/mine`, { waitUntil: 'domcontentloaded' })
  const activeCard = reservationCard(page, booking.device)
  await expect(activeCard.locator('.mine__card-id')).toHaveText(`#${booking.reservationId}`, { timeout: 30_000 })
  await expect(activeCard).toContainText('使用中', { timeout: 30_000 })
  const returnButton = activeCard.getByRole('button', { name: '归还' })
  await expect(returnButton).toBeVisible()
  await returnButton.click()
  const returnDialog = page.getByRole('dialog', { name: '提交归还' })
  await expect(returnDialog).toBeVisible()
  await returnDialog.locator('input[type="file"]').setInputFiles(evidencePath)
  await expect(returnDialog.getByText('1 张已选择')).toBeVisible()
  const returnResponsePromise = page.waitForResponse((response) =>
    response.url().includes(`/api/v2/reservations/${booking.reservationId}/return`)
      && response.request().method() === 'POST', { timeout: 30_000 })
  await returnDialog.getByRole('button', { name: '确认归还' }).click()
  const returnResponse = await returnResponsePromise
  if (returnResponse.status() !== 200) throw new Error(`Return request returned HTTP ${returnResponse.status()}.`)
  await expect(activeCard).toContainText('待负责人验收', { timeout: 30_000 })
  await page.screenshot({ path: path.join(artifactDir, 'student-a-return-pending.png'), fullPage: true })
  const returnRecord = {
    role: 'student-a',
    deviceId: booking.device.id,
    deviceName: booking.device.name,
    date,
    reservationId: booking.reservationId,
    responseStatus: returnResponse.status(),
    condition: 'NORMAL',
    evidencePath,
    status: 'RETURN_PENDING',
    screenshotPath: path.join(artifactDir, 'student-a-return-pending.png'),
  }
  writeJSON(returnedPath, returnRecord)
  log('return_submitted', returnRecord)

  const acceptedToast = page.locator('.el-notification').filter({ hasText: '设备归还已验收' }).first()
  await expect(acceptedToast).toBeVisible({ timeout: 180_000 })
  await page.screenshot({ path: path.join(artifactDir, 'student-a-acceptance-toast.png'), fullPage: true })
  log('acceptance_toast_received', { reservationId: booking.reservationId, websocketFrames })

  const acceptanceHistoryPromise = page.waitForResponse((response) =>
    response.url().includes('/api/v2/notifications/mine?page=1')
      && response.request().method() === 'GET', { timeout: 30_000 })
  await page.goto(`${baseURL}/notifications`, { waitUntil: 'domcontentloaded' })
  const acceptanceHistoryResponse = await acceptanceHistoryPromise
  const acceptanceBody = await acceptanceHistoryResponse.json()
  const acceptanceRecords = acceptanceBody?.data?.records || []
  const acceptanceRecord = acceptanceRecords.find((item) =>
    item.relatedId === booking.reservationId
      && item.title === '设备归还已验收'
      && String(item.content || '').includes(booking.device.name))
  const acceptanceRow = page.locator('.notif-row').filter({ hasText: '设备归还已验收' }).filter({ hasText: booking.device.name })
  await expect(acceptanceRow.first()).toBeVisible({ timeout: 30_000 })
  expect(acceptanceRecord).toBeTruthy()
  await page.screenshot({ path: path.join(artifactDir, 'student-a-acceptance-history.png'), fullPage: true })
  log('acceptance_history_verified', {
    reservationId: booking.reservationId,
    httpStatus: acceptanceHistoryResponse.status(),
    notificationId: acceptanceRecord.id,
    title: acceptanceRecord.title,
  })

  await waitForMarker(completionMarker, 'admin return acceptance')
  await page.goto(`${baseURL}/reservations/mine`, { waitUntil: 'domcontentloaded' })
  const completedCard = reservationCard(page, booking.device)
  await expect(completedCard.locator('.mine__card-id')).toHaveText(`#${booking.reservationId}`, { timeout: 30_000 })
  await expect(completedCard).toContainText('已完成', { timeout: 30_000 })
  await completedCard.getByRole('button', { name: '详情' }).click()
  await expect(page.locator('.rsv-detail')).toContainText('负责人已完成验收', { timeout: 30_000 })
  await page.screenshot({ path: path.join(artifactDir, 'student-a-completed-detail.png'), fullPage: true })
  const finalRecord = {
    role: 'student-a',
    deviceId: booking.device.id,
    deviceName: booking.device.name,
    date,
    reservationId: booking.reservationId,
    status: 'COMPLETED',
    approvalToast: true,
    approvalHistoryHTTP: historyResponse.status(),
    acceptanceToast: true,
    acceptanceHistoryHTTP: acceptanceHistoryResponse.status(),
    websocketEvents,
    websocketFrames,
    browserErrors,
    unexpectedHTTP,
    requestFailures,
    screenshotPaths: [
      path.join(artifactDir, 'student-a-booking.png'),
      path.join(artifactDir, 'student-a-approval-toast.png'),
      path.join(artifactDir, 'student-a-approval-history.png'),
      path.join(artifactDir, 'student-a-return-pending.png'),
      path.join(artifactDir, 'student-a-acceptance-toast.png'),
      path.join(artifactDir, 'student-a-acceptance-history.png'),
      path.join(artifactDir, 'student-a-completed-detail.png'),
    ],
  }
  writeJSON(path.join(artifactDir, 'student-a-completed.json'), finalRecord)
  log('student_a_full_chain_passed', finalRecord)

  if (browserErrors.length || unexpectedHTTP.length || requestFailures.length) {
    throw new Error('Unexpected page, HTTP, or request failures were recorded.')
  }
} catch (error) {
  const message = redact(error instanceof Error ? error.message : String(error))
  const details = {
    message,
    currentPage: page.url(),
    reservationId: booking?.reservationId || null,
    websocketEvents,
    websocketFrames,
    httpStatuses,
    unexpectedHTTP,
    requestFailures,
    browserErrors,
  }
  if (!page.url().endsWith('/login')) {
    try { await page.screenshot({ path: path.join(artifactDir, 'student-a-failure.png'), fullPage: true }) } catch {}
  }
  writeJSON(path.join(artifactDir, 'student-a-failure.json'), details)
  log('student_a_chain_failed', details)
  throw error
} finally {
  await context.close()
  await browser.close()
}
