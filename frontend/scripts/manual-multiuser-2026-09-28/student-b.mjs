import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

const BASE_URL = 'http://127.0.0.1:5173'
const PRIMARY_DEVICE_ID = 11628
const FALLBACK_DEVICE_ID = 11629
const PRIMARY_DEVICE_NAME = 'e2e-qa260928-multi9x3-device'
const DATE = '2026-09-28'
const CREDENTIALS_PATH = 'C:\\Users\\A2781\\AppData\\Local\\Temp\\lab-reservation-manual-e2e-credentials-20260928.json'
const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..', '..', '..')
const OUT = path.join(ROOT, '.artifacts', 'manual-multiuser-2026-09-28')
const EVIDENCE_PATH = path.join(OUT, 'evidence.png')
const LOG_PATH = path.join(OUT, 'student-b-events.ndjson')

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const safePath = (value) => {
  try { return new URL(value).pathname } catch { return String(value).split('?')[0] }
}
const writeJson = async (name, value) => {
  const target = path.join(OUT, name)
  const temp = `${target}.tmp`
  await fs.writeFile(temp, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
  await fs.rename(temp, target)
}
const readJson = async (name) => JSON.parse(await fs.readFile(path.join(OUT, name), 'utf8'))
const record = async (event) => {
  const value = { at: new Date().toISOString(), ...event }
  await fs.appendFile(LOG_PATH, `${JSON.stringify(value)}\n`, 'utf8')
  console.log(JSON.stringify(value))
}

async function waitForFile(name, timeoutMs = 20 * 60 * 1000) {
  const deadline = Date.now() + timeoutMs
  let lastNotice = 0
  while (Date.now() < deadline) {
    try { return await readJson(name) } catch (error) {
      if (error?.code !== 'ENOENT') throw error
    }
    if (Date.now() - lastNotice > 20_000) {
      await record({ event: 'waiting_for_parent_marker', marker: name })
      lastNotice = Date.now()
    }
    await sleep(1000)
  }
  throw new Error(`Timed out waiting for ${name}`)
}

async function waitUntil(check, timeoutMs, label, intervalMs = 250) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await check()) return
    await sleep(intervalMs)
  }
  throw new Error(`Timed out waiting for ${label}`)
}

const pageErrors = []
const httpErrors = []
const failedRequests = []
const websocketEvents = []
let offlineMode = false
let loggedIn = false

async function verifyHistoryOnly() {
  await fs.mkdir(OUT, { recursive: true })
  const reservationId = Number(process.argv[process.argv.indexOf('--history-only') + 1])
  if (!Number.isInteger(reservationId) || reservationId < 1) throw new Error('--history-only requires a reservation id')
  const credentials = JSON.parse(await fs.readFile(CREDENTIALS_PATH, 'utf8'))
  const username = String(credentials.alternate_username ?? '')
  const password = String(credentials.password ?? '')
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const page = await context.newPage()
  let loggedIn = false
  page.on('response', async (response) => {
    const route = safePath(response.url())
    const status = response.status()
    if (status >= 400) {
      const expectedAuthProbe = status === 401 && !loggedIn && route.endsWith('/auth/me')
      await record({ event: expectedAuthProbe ? 'expected_http_status' : 'history_check_http_error', status, method: response.request().method(), route })
    }
  })
  try {
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' })
    await page.getByPlaceholder('请输入用户名').fill(username)
    await page.getByPlaceholder('请输入密码').fill(password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await page.waitForURL((url) => !url.pathname.endsWith('/login'), { timeout: 20_000 })
    loggedIn = true
    const historyPromise = page.waitForResponse((response) => {
      if (response.status() !== 200 || !safePath(response.url()).endsWith('/api/v2/notifications/mine')) return false
      return !new URL(response.url()).searchParams.has('onlyUnread')
    }, { timeout: 30_000 })
    await page.goto(`${BASE_URL}/notifications`, { waitUntil: 'domcontentloaded' })
    const historyResponse = await historyPromise
    const responseBody = await historyResponse.json()
    const historyPayload = responseBody?.data ?? responseBody
    const rows = historyPayload?.records ?? historyPayload?.items ?? []
    const linked = Array.isArray(rows) ? rows.filter((row) => Number(row.related_id ?? row.relatedId) === reservationId) : []
    const approval = linked.find((row) => row.title === '预约申请已通过')
    const handover = linked.find((row) => row.title === '设备已完成交接')
    await page.locator('.notif-row').filter({ hasText: '预约申请已通过' }).first().waitFor({ timeout: 15_000 })
    await page.locator('.notif-row').filter({ hasText: '设备已完成交接' }).first().waitFor({ timeout: 15_000 })
    await page.screenshot({ path: path.join(OUT, 'student-b-notification-followup.png'), fullPage: true })
    const result = {
      role: 'student-b', reservationId, historyHttpStatus: historyResponse.status(),
      linkedNotificationCount: linked.length,
      notifications: linked.map((row) => ({
        id: Number(row.id) || null,
        relatedId: Number(row.related_id ?? row.relatedId) || null,
        title: String(row.title || ''),
        type: String(row.type || ''),
      })),
      approvalCompensated: Boolean(approval),
      handoverNotificationPresent: Boolean(handover),
      screenshot: path.join(OUT, 'student-b-notification-followup.png'),
    }
    await writeJson('student-b-notification-followup.json', result)
    await record({ event: 'history_only_verification', reservationId, historyHttpStatus: result.historyHttpStatus, approvalCompensated: result.approvalCompensated, handoverNotificationPresent: result.handoverNotificationPresent, linkedNotificationCount: linked.length })
    if (!approval || !handover) throw new Error(`History missing linked approval or handover notification for reservation ${reservationId}`)
  } catch (error) {
    const message = String(error?.stack || error?.message || error).replaceAll(username, '[redacted]').replaceAll(password, '[redacted]').slice(0, 3000)
    await record({ event: 'history_only_error', message })
    try { await page.screenshot({ path: path.join(OUT, 'student-b-notification-followup-error.png'), fullPage: true }) } catch { /* ignore */ }
    await writeJson('student-b-notification-followup-error.json', { role: 'student-b', reservationId, message })
    process.exitCode = 1
  } finally {
    await context.close().catch(() => {})
    await browser.close().catch(() => {})
  }
}

async function main() {
  await fs.mkdir(OUT, { recursive: true })
  // A valid tiny PNG is uploaded through the return form as the required evidence image.
  await fs.writeFile(EVIDENCE_PATH, Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/pV8AAAAASUVORK5CYII=',
    'base64',
  ))
  const credentials = JSON.parse(await fs.readFile(CREDENTIALS_PATH, 'utf8'))
  const username = String(credentials.alternate_username ?? '')
  const password = String(credentials.password ?? '')
  if (!username || !password) throw new Error('Credential file is missing required fields')

  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const page = await context.newPage()

  page.on('pageerror', async (error) => {
    const message = String(error?.message || 'page error').replaceAll(username, '[redacted]').replaceAll(password, '[redacted]').slice(0, 500)
    pageErrors.push(message)
    await record({ event: 'page_error', message })
  })
  page.on('response', async (response) => {
    const status = response.status()
    const request = response.request()
    const route = safePath(response.url())
    if (route.endsWith('/api/v2/ws') && status === 101) {
      websocketEvents.push({ event: 'handshake_101', at: Date.now(), route })
      await record({ event: 'websocket_handshake', status, route })
    }
    if (status >= 400) {
      const expectedAuthProbe = status === 401 && !loggedIn && route.endsWith('/auth/me')
      const expectedRaceConflict = status === 409 && request.method() === 'POST' && route.endsWith('/api/v2/reservations')
      if (expectedAuthProbe || expectedRaceConflict) {
        await record({ event: 'expected_http_status', status, method: request.method(), route })
      } else {
        const item = { status, method: request.method(), route }
        httpErrors.push(item)
        await record({ event: 'http_error', ...item })
      }
    }
  })
  page.on('requestfailed', async (request) => {
    const failure = request.failure()?.errorText || 'request failed'
    const route = safePath(request.url())
    const expectedDisconnect = offlineMode && /ERR_INTERNET_DISCONNECTED|ERR_NETWORK_CHANGED|ERR_CONNECTION_CLOSED/i.test(failure)
    if (expectedDisconnect || /ERR_ABORTED/i.test(failure)) {
      await record({ event: 'expected_request_failure', route, reason: failure })
    } else {
      const item = { route, reason: failure.slice(0, 240) }
      failedRequests.push(item)
      await record({ event: 'request_failure', ...item })
    }
  })
  page.on('websocket', (socket) => {
    const item = { route: safePath(socket.url()), createdAt: Date.now(), closedAt: null, framesReceived: 0, framesSent: 0 }
    websocketEvents.push(item)
    void record({ event: 'websocket_created', route: item.route })
    socket.on('framesent', () => { item.framesSent += 1 })
    socket.on('framereceived', () => { item.framesReceived += 1 })
    socket.on('close', () => {
      item.closedAt = Date.now()
      void record({ event: 'websocket_closed', route: item.route })
    })
  })

  try {
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' })
    await page.getByPlaceholder('请输入用户名').fill(username)
    await page.getByPlaceholder('请输入密码').fill(password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await page.waitForURL((url) => !url.pathname.endsWith('/login'), { timeout: 20_000 })
    loggedIn = true
    await record({ event: 'login_succeeded' })

    async function prepareDevice(deviceId, deviceName) {
      await page.goto(`${BASE_URL}/reservations/create?deviceId=${deviceId}&startDate=${DATE}&endDate=${DATE}`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: deviceName, exact: true }).waitFor({ timeout: 20_000 })
      const purpose = page.locator('textarea').first()
      await purpose.fill('用于本轮多用户预约审批、断线通知补偿与归还验收链路验证')
      await page.locator('.preflight-card .summary-good').waitFor({ timeout: 20_000 })

      const safetyButton = page.getByRole('button', { name: '我已阅读并确认', exact: true })
      if (await safetyButton.count()) {
        await safetyButton.click()
        await page.getByText('已确认', { exact: true }).waitFor({ timeout: 15_000 })
        await page.locator('.preflight-card .summary-good').waitFor({ timeout: 15_000 })
      }
      const qualificationRequired = await page.locator('.access-card').getByText('该设备需要先提交培训或操作资质').count().catch(() => 0)
      if (qualificationRequired) throw new Error(`Device ${deviceId} requires qualification not covered by this flow`)
      const submit = page.locator('.submit-button')
      await waitUntil(() => submit.isEnabled(), 20_000, 'reservation submit enabled')
      return submit
    }

    let deviceId = PRIMARY_DEVICE_ID
    let deviceName = PRIMARY_DEVICE_NAME
    let submit = await prepareDevice(deviceId, deviceName)
    await page.screenshot({ path: path.join(OUT, 'student-b-ready.png'), fullPage: true })
    await writeJson('student-b-ready.json', {
      role: 'student-b', deviceId, date: DATE, preflightAvailable: true,
      submitEnabled: await submit.isEnabled(), screenshot: path.join(OUT, 'student-b-ready.png'),
    })
    await record({ event: 'ready_for_race', deviceId, date: DATE })
    await waitForFile('submit-go.json')

    async function submitReservation(button) {
      const responsePromise = page.waitForResponse((response) =>
        response.request().method() === 'POST' && safePath(response.url()).endsWith('/api/v2/reservations'),
        { timeout: 30_000 },
      )
      await button.click()
      const response = await responsePromise
      let body = {}
      try { body = await response.json() } catch { /* status evidence is still retained */ }
      const payload = body?.data ?? body
      const created = payload?.created ?? []
      const reservation = Array.isArray(created) ? created[0] : null
      return { status: response.status(), reservationId: Number(reservation?.id) || null, body }
    }

    let booking = await submitReservation(submit)
    if (booking.status === 409) {
      await record({ event: 'race_lost_expected', status: 409, attemptedDeviceId: deviceId })
      deviceId = FALLBACK_DEVICE_ID
      deviceName = `${PRIMARY_DEVICE_NAME}-2`
      submit = await prepareDevice(deviceId, deviceName)
      booking = await submitReservation(submit)
    }
    if (booking.status !== 201 || !booking.reservationId) {
      throw new Error(`Reservation was not created: HTTP ${booking.status}, created record missing`)
    }
    const reservationId = booking.reservationId
    await page.locator('.mine__cell').filter({ hasText: deviceName }).first().waitFor({ timeout: 20_000 })
    const bookingCard = page.locator('.mine__cell').filter({ hasText: deviceName }).first()
    await bookingCard.getByText('待审批', { exact: true }).waitFor({ timeout: 15_000 })
    await page.screenshot({ path: path.join(OUT, 'student-b-booked.png'), fullPage: true })
    await writeJson('student-b-booking.json', {
      role: 'student-b', deviceId, date: DATE, status: 'PENDING', reservationId,
      createHttpStatus: booking.status, screenshot: path.join(OUT, 'student-b-booked.png'),
    })
    await record({ event: 'booking_created', deviceId, reservationId, status: 'PENDING', createHttpStatus: booking.status })

    const websocketCountBeforeOffline = websocketEvents.filter((item) => item.route?.endsWith('/api/v2/ws')).length
    offlineMode = true
    await context.setOffline(true)
    await writeJson('student-b-offline.json', {
      role: 'student-b', deviceId, date: DATE, reservationId, browserOffline: true,
      websocketCountBeforeOffline, at: new Date().toISOString(),
    })
    await record({ event: 'browser_offline_ready', deviceId, reservationId, websocketCountBeforeOffline })
    await waitForFile('admin-handover-done.json')

    const previousSocketCount = websocketEvents.filter((item) => item.route?.endsWith('/api/v2/ws')).length
    offlineMode = false
    const onlineAt = Date.now()
    await context.setOffline(false)
    await record({ event: 'browser_online', reservationId, previousSocketCount })
    let reconnectObserved = false
    try {
      await waitUntil(
        () => websocketEvents.filter((item) => item.route?.endsWith('/api/v2/ws') && item.createdAt >= onlineAt).length > 0
          || websocketEvents.some((item) => item.event === 'handshake_101' && item.at >= onlineAt),
        30_000,
        'WebSocket reconnect after network restoration',
        500,
      )
      reconnectObserved = true
    } catch (error) {
      await record({ event: 'websocket_reconnect_not_observed', reservationId, previousSocketCount, message: String(error.message) })
    }

    const historyResponsePromise = page.waitForResponse((response) => {
      if (response.status() !== 200 || !safePath(response.url()).endsWith('/api/v2/notifications/mine')) return false
      return !new URL(response.url()).searchParams.has('onlyUnread')
    }, { timeout: 30_000 })
    await page.goto(`${BASE_URL}/notifications`, { waitUntil: 'domcontentloaded' })
    let historyResponse = await historyResponsePromise
    let historyBody = await historyResponse.json()
    let historyPayload = historyBody?.data ?? historyBody
    let records = historyPayload?.records ?? historyPayload?.items ?? []
    let matchedNotification = Array.isArray(records) ? records.find((row) =>
      row.title === '预约申请已通过'
      && Number(row.related_id ?? row.relatedId) === reservationId,
    ) : null

    // The UI is the authority for this flow; reload only the notifications page if its first history snapshot predates the approval event.
    for (let attempt = 0; !matchedNotification && attempt < 5; attempt += 1) {
      await sleep(2000)
      const nextHistory = page.waitForResponse((response) => {
        if (response.status() !== 200 || !safePath(response.url()).endsWith('/api/v2/notifications/mine')) return false
        return !new URL(response.url()).searchParams.has('onlyUnread')
      }, { timeout: 20_000 })
      await page.reload({ waitUntil: 'domcontentloaded' })
      historyResponse = await nextHistory
      historyBody = await historyResponse.json()
      historyPayload = historyBody?.data ?? historyBody
      records = historyPayload?.records ?? historyPayload?.items ?? []
      matchedNotification = Array.isArray(records) ? records.find((row) =>
        row.title === '预约申请已通过'
        && Number(row.related_id ?? row.relatedId) === reservationId,
      ) : null
    }
    const visibleNotification = page.locator('.notif-row').filter({ hasText: '预约申请已通过' })
    await visibleNotification.first().waitFor({ timeout: 15_000 })
    if (!matchedNotification) throw new Error(`HTTP notification history did not include approval for reservation ${reservationId}`)
    await page.screenshot({ path: path.join(OUT, 'student-b-notification.png'), fullPage: true })
    await writeJson('student-b-notification.json', {
      role: 'student-b', reservationId, deviceId,
      historyHttpStatus: historyResponse.status(), notificationId: Number(matchedNotification.id) || null,
      relatedId: Number(matchedNotification.related_id ?? matchedNotification.relatedId),
      title: matchedNotification.title, websocketReconnectObserved: reconnectObserved,
      screenshot: path.join(OUT, 'student-b-notification.png'),
    })
    await record({ event: 'approval_history_compensation_verified', reservationId, relatedId: Number(matchedNotification.related_id ?? matchedNotification.relatedId), websocketReconnectObserved: reconnectObserved })

    await page.goto(`${BASE_URL}/reservations/mine`, { waitUntil: 'domcontentloaded' })
    let reservationCard = page.locator('.mine__cell').filter({ hasText: deviceName }).first()
    await reservationCard.waitFor({ timeout: 20_000 })
    await reservationCard.getByText('使用中', { exact: true }).waitFor({ timeout: 20_000 })
    await reservationCard.getByRole('button', { name: '归还', exact: true }).click()
    await page.locator('.mine__return-photos input[type="file"]').setInputFiles(EVIDENCE_PATH)
    await page.locator('.mine__return-photos').getByText('1 张已选择', { exact: true }).waitFor({ timeout: 5000 })
    const returnResponsePromise = page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && safePath(response.url()).endsWith(`/api/v2/reservations/${reservationId}/return`),
      { timeout: 30_000 },
    )
    await page.getByRole('button', { name: '确认归还', exact: true }).click()
    const returnResponse = await returnResponsePromise
    if (returnResponse.status() < 200 || returnResponse.status() >= 300) {
      throw new Error(`Return request failed with HTTP ${returnResponse.status()}`)
    }
    await reservationCard.getByText('待负责人验收', { exact: true }).waitFor({ timeout: 20_000 })
    await page.screenshot({ path: path.join(OUT, 'student-b-returned.png'), fullPage: true })
    await writeJson('student-b-returned.json', {
      role: 'student-b', reservationId, deviceId, date: DATE, status: 'IN_USE', handoverStatus: 'RETURN_PENDING',
      returnHttpStatus: returnResponse.status(), evidenceImage: EVIDENCE_PATH,
      screenshot: path.join(OUT, 'student-b-returned.png'),
    })
    await record({ event: 'return_submitted', reservationId, deviceId, returnHttpStatus: returnResponse.status() })

    // Wait for the administrator's actual acceptance, reloading only the UI's own reservation list.
    let completed = false
    const completionDeadline = Date.now() + 15 * 60 * 1000
    while (Date.now() < completionDeadline) {
      await page.reload({ waitUntil: 'domcontentloaded' })
      reservationCard = page.locator('.mine__cell').filter({ hasText: deviceName }).first()
      await reservationCard.waitFor({ timeout: 20_000 })
      if (await reservationCard.getByText('已完成', { exact: true }).count()) {
        completed = true
        break
      }
      await record({ event: 'waiting_for_admin_return_acceptance', reservationId })
      await sleep(5000)
    }
    if (!completed) throw new Error(`Reservation ${reservationId} was not accepted within 15 minutes`)
    await reservationCard.getByRole('button', { name: '详情', exact: true }).click()
    await page.waitForURL(new RegExp(`/reservations/${reservationId}$`), { timeout: 15_000 })
    await page.getByText('负责人已完成验收', { exact: true }).waitFor({ timeout: 15_000 })
    await page.getByText('已完成归还验收', { exact: true }).waitFor({ timeout: 15_000 })
    await page.getByText('验收正常', { exact: true }).waitFor({ timeout: 15_000 })
    await page.screenshot({ path: path.join(OUT, 'student-b-final.png'), fullPage: true })
    await writeJson('student-b-final.json', {
      role: 'student-b', reservationId, deviceId, date: DATE, status: 'COMPLETED', handoverStatus: 'RETURNED',
      inspectionCondition: 'NORMAL', screenshot: path.join(OUT, 'student-b-final.png'),
      pageErrors, httpErrors, failedRequests,
    })
    await record({ event: 'final_ui_acceptance_verified', reservationId, deviceId, status: 'COMPLETED', unexpectedHttpErrors: httpErrors.length, failedRequests: failedRequests.length, pageErrors: pageErrors.length })
  } catch (error) {
    const message = String(error?.stack || error?.message || error).replaceAll(username, '[redacted]').replaceAll(password, '[redacted]').slice(0, 4000)
    await record({ event: 'runner_error', message })
    try { await page.screenshot({ path: path.join(OUT, 'student-b-error.png'), fullPage: true }) } catch { /* page may be closed */ }
    await writeJson('student-b-error.json', {
      role: 'student-b', at: new Date().toISOString(), message,
      currentUrl: safePath(page.url()), pageErrors, httpErrors, failedRequests,
    })
    process.exitCode = 1
  } finally {
    await context.close().catch(() => {})
    await browser.close().catch(() => {})
  }
}

if (process.argv.includes('--history-only')) await verifyHistoryOnly()
else await main()
