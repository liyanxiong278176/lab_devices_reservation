import { chromium } from '@playwright/test'
import { mkdir, readFile, writeFile, appendFile } from 'node:fs/promises'
import path from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'

const baseURL = process.env.PREVIEW_URL || 'http://127.0.0.1:18080'
const username = process.env.QA_STUDENT_USERNAME || 'e2e-multi-qa260928-user2'
const password = process.env.QA_STUDENT_PASSWORD || 'E2e-123456'
const date = '2026-09-28'
const primaryDeviceId = 13
const fallbackDeviceId = 14
const purpose = `Student B browser chain ${Date.now()}`
const runDir = path.resolve(process.env.QA_ARTIFACT_DIR || '../.artifacts/manual-multi-flow/e2e-multi-qa260928-run2')
const marker = (name) => path.join(runDir, name)
const logPath = path.join(runDir, 'student-b.log.jsonl')

await mkdir(runDir, { recursive: true })
const record = async (event, details = {}) => {
  const row = { at: new Date().toISOString(), event, ...details }
  await appendFile(logPath, `${JSON.stringify(row)}\n`)
  console.log(JSON.stringify(row))
}
const assert = (condition, message) => {
  if (!condition) throw new Error(message)
}
const waitForMarker = async (name, timeoutMs = 45 * 60 * 1000) => {
  const end = Date.now() + timeoutMs
  while (Date.now() < end) {
    try {
      return await readFile(marker(name), 'utf8')
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error
    }
    await delay(1000)
  }
  throw new Error(`Timed out waiting for ${name}`)
}
const reservationResponse = (response) =>
  response.request().method() === 'POST' && /\/api\/v2\/reservations(?:\?.*)?$/.test(new URL(response.url()).pathname + new URL(response.url()).search)

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const browserErrors = []
page.on('pageerror', (error) => browserErrors.push(error.message))
page.on('console', (message) => {
  const text = message.text()
  if (
    message.type() === 'error'
    && !/server responded with a 401|server responded with a 409|ERR_INTERNET_DISCONNECTED|WebSocket.*failed/i.test(text)
  ) {
    browserErrors.push(text)
  }
})
page.on('response', (response) => {
  if (response.status() >= 400) {
    void record('http_error', { status: response.status(), url: response.url() })
  }
})
let responseMeta = null
const http5xx = []
page.on('response', async (response) => {
  if (response.status() >= 500) http5xx.push({ status: response.status(), url: response.url() })
  if (!reservationResponse(response)) return
  try {
    responseMeta = { status: response.status(), body: await response.json() }
  } catch (error) {
    responseMeta = { status: response.status(), bodyError: String(error) }
  }
})

try {
  await page.goto(`${baseURL}/login`, { waitUntil: 'networkidle' })
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL('**/dashboard', { timeout: 20_000 })
  await page.locator('main.layout__main').waitFor({ state: 'visible' })
  await record('logged_in', { username })

  if (process.env.QA_FINAL_CHECK_ONLY === '1') {
    const booked = JSON.parse(await readFile(marker('student-b.booked.json'), 'utf8'))
    const detailUrl = `${baseURL}/reservations/${booked.reservationId}`
    const detailResponsePromise = page.waitForResponse((response) =>
      response.request().method() === 'GET'
      && new URL(response.url()).pathname === `/api/v2/reservations/${booked.reservationId}`,
    { timeout: 30_000 })
    await page.goto(detailUrl, { waitUntil: 'networkidle' })
    const detailResponse = await detailResponsePromise
    const detailBody = await detailResponse.json()
    const detailData = detailBody.data ?? detailBody
    assert(detailResponse.status() === 200, `Fresh detail GET returned HTTP ${detailResponse.status()}`)
    assert(detailData.status === 'COMPLETED', `Fresh detail data status=${detailData.status}`)
    assert(detailData.handover_status === 'RETURNED', `Fresh detail handover_status=${detailData.handover_status}`)
    assert(Array.isArray(detailData.return_image_urls) && detailData.return_image_urls.length === 1, `Expected one persisted return photo URL; got ${JSON.stringify(detailData.return_image_urls)}`)
    await page.locator('.rsv-detail__layout').waitFor({ state: 'visible', timeout: 20_000 })
    await page.getByText('已完成', { exact: true }).waitFor({ state: 'visible', timeout: 20_000 })
    await page.getByText('已完成归还验收', { exact: true }).waitFor({ state: 'visible', timeout: 20_000 })
    await page.getByText('验收正常', { exact: true }).waitFor({ state: 'visible', timeout: 20_000 })
    await expectReservationPurpose(page, booked.purpose)
    await page.screenshot({ path: path.join(runDir, 'student-b-final-fresh-detail.png'), fullPage: true })
    await record('fresh_final_detail_verified', {
      reservationId: booked.reservationId,
      status: detailData.status,
      handoverStatus: detailData.handover_status,
      returnImageCount: detailData.return_image_urls.length,
      inspectionCondition: detailData.inspection_condition,
      httpStatus: detailResponse.status(),
    })

    await page.goto(`${baseURL}/notifications`, { waitUntil: 'networkidle' })
    const notificationRows = await page.locator('.notif-row').allTextContents()
    const approvalHistoryVisible = notificationRows.some((value) => value.includes('预约申请已通过'))
    const returnAcceptanceHistoryVisible = notificationRows.some((value) => value.includes('设备归还已验收'))
    await record('fresh_notification_history', { approvalHistoryVisible, returnAcceptanceHistoryVisible, rowCount: notificationRows.length })
    assert(approvalHistoryVisible, 'Approval notification is missing from HTTP-loaded notification history.')
    assert(returnAcceptanceHistoryVisible, 'Return acceptance notification is missing from HTTP-loaded notification history.')
    assert(http5xx.length === 0, `Unexpected server errors: ${JSON.stringify(http5xx)}`)
    await page.screenshot({ path: path.join(runDir, 'student-b-final-fresh-notifications.png'), fullPage: true })
    await writeFile(marker('student-b.final-fresh.json'), JSON.stringify({
      reservationId: booked.reservationId,
      finalStatus: detailData.status,
      handoverStatus: detailData.handover_status,
      returnImageCount: detailData.return_image_urls.length,
      approvalHistoryVisible,
      returnAcceptanceHistoryVisible,
      http5xx,
      verifiedAt: new Date().toISOString(),
    }, null, 2))
    await record('fresh_manual_check_passed', { reservationId: booked.reservationId, http5xx: http5xx.length })
  } else {
  const submitBooking = async (deviceId, mode) => {
    responseMeta = null
    await page.goto(`${baseURL}/reservations/create?deviceId=${deviceId}&startDate=${date}&endDate=${date}`, { waitUntil: 'networkidle' })
    await page.locator('main.layout__main').waitFor({ state: 'visible' })
    await page.getByLabel('使用用途').fill(purpose)
    const submit = page.getByRole('button', { name: '提交预约', exact: true })
    await submit.waitFor({ state: 'visible' })
    await page.waitForTimeout(1500)
    const beforeSubmit = await page.evaluate(() => ({
      url: location.href,
      submitButtons: Array.from(document.querySelectorAll('button'))
        .filter((button) => button.textContent?.trim() === '提交预约')
        .map((button) => ({ disabled: button.disabled, ariaDisabled: button.getAttribute('aria-disabled'), text: button.textContent?.trim() })),
      preflight: document.querySelector('.preflight-card')?.innerText,
      bodyStart: document.body.innerText.slice(0, 3000),
    }))
    await page.screenshot({ path: path.join(runDir, `student-b-create-${deviceId}.png`), fullPage: true })
    await record('preflight_ready_state', { mode, deviceId, beforeSubmit })
    await page.waitForFunction(() => {
      const buttons = Array.from(document.querySelectorAll('button'))
      const target = buttons.find((button) => button.textContent?.trim() === '提交预约')
      return Boolean(target && !target.disabled && target.getAttribute('aria-disabled') !== 'true')
    }, null, { timeout: 30_000 })
    if (mode === 'initial') {
      await writeFile(marker('student-b.ready'), JSON.stringify({ username, deviceId, date, readyAt: new Date().toISOString() }, null, 2))
      await record('ready_for_race', { deviceId, date, purpose })
      await waitForMarker('submit.go')
    }
    const responsePromise = page.waitForResponse((response) => reservationResponse(response), { timeout: 45_000 })
    await submit.click()
    const response = await responsePromise
    await response.finished()
    await delay(250)
    const payload = responseMeta?.body?.data ?? responseMeta?.body
    const created = Array.isArray(payload?.created) ? payload.created : []
    const skipped = Array.isArray(payload?.skipped_conflicts) ? payload.skipped_conflicts : []
    const booked = created[0]
      ? { reservationId: Number(created[0].id), deviceId: Number(created[0].device_id ?? deviceId), status: created[0].status ?? 'PENDING' }
      : null
    await record('booking_submit', { mode, deviceId, httpStatus: response.status(), createdCount: created.length, skipped, body: responseMeta?.body })
    return { booked, httpStatus: response.status(), skipped }
  }

  let result = await submitBooking(primaryDeviceId, 'initial')
  let booked = result.booked
  if (!booked) {
    assert(result.httpStatus < 500, `Primary device submit failed unexpectedly with HTTP ${result.httpStatus}`)
    await record('primary_conflict', { deviceId: primaryDeviceId, httpStatus: result.httpStatus, skipped: result.skipped })
    result = await submitBooking(fallbackDeviceId, 'fallback')
    booked = result.booked
  }
  assert(booked?.reservationId > 0, `No booking created; last submit HTTP ${result.httpStatus}`)
  assert([primaryDeviceId, fallbackDeviceId].includes(booked.deviceId), `Unexpected booked device ${booked.deviceId}`)
  await page.waitForURL('**/reservations/mine', { timeout: 20_000 }).catch(() => {})
  await page.goto(`${baseURL}/reservations/mine`, { waitUntil: 'networkidle' })
  const ownCard = page.locator('.mine__card').filter({ hasText: purpose })
  await ownCard.waitFor({ state: 'visible', timeout: 20_000 })
  await assert((await ownCard.innerText()).includes('待审批'), 'New reservation did not appear as pending approval in my reservations.')
  booked.purpose = purpose
  booked.date = date
  booked.username = username
  await writeFile(marker('student-b.booked.json'), JSON.stringify(booked, null, 2))
  await page.screenshot({ path: path.join(runDir, 'student-b-pending.png'), fullPage: true })
  await record('booking_confirmed_in_ui', booked)

  await context.setOffline(true)
  await writeFile(marker('student-b.offline-ready'), JSON.stringify({ ...booked, offlineAt: new Date().toISOString() }, null, 2))
  await record('offline_before_admin_approval', { reservationId: booked.reservationId })
  await waitForMarker('reconnect.go')
  await context.setOffline(false)
  await page.goto(`${baseURL}/notifications`, { waitUntil: 'networkidle' })
  await page.locator('main.layout__main').waitFor({ state: 'visible' })
  await page.getByText('预约申请已通过', { exact: false }).first().waitFor({ state: 'visible', timeout: 25_000 })
  await page.screenshot({ path: path.join(runDir, 'student-b-reconnected-notification.png'), fullPage: true })
  await writeFile(marker('student-b.reconnected.json'), JSON.stringify({ reservationId: booked.reservationId, notificationVisible: true, checkedAt: new Date().toISOString() }, null, 2))
  await record('reconnect_compensation_verified', { reservationId: booked.reservationId, notification: '预约申请已通过' })

  await waitForMarker('return.go')
  await page.goto(`${baseURL}/reservations/mine`, { waitUntil: 'networkidle' })
  const activeCard = page.locator('.mine__card').filter({ hasText: purpose })
  await activeCard.waitFor({ state: 'visible', timeout: 20_000 })
  const activeText = await activeCard.innerText()
  assert(activeText.includes('使用中'), `Expected reservation to be IN_USE before return; card text: ${activeText}`)
  await activeCard.getByRole('button', { name: '归还', exact: true }).click()
  const photoPath = path.join(runDir, 'student-b-return-1x1.png')
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j4j8AAAAASUVORK5CYII=', 'base64')
  await writeFile(photoPath, png)
  await page.locator('.mine__return-photos input[type="file"]').setInputFiles(photoPath)
  await page.getByRole('button', { name: '确认归还', exact: true }).click()
  await page.getByText('已提交归还，等待负责人验收', { exact: false }).waitFor({ state: 'visible', timeout: 25_000 })
  await page.waitForTimeout(300)
  const returnPayload = { ...booked, status: 'IN_USE', handoverStatus: 'RETURN_PENDING', returnSubmitted: true, returnCondition: 'NORMAL', returnImageCount: 1, returnedAt: new Date().toISOString() }
  await writeFile(marker('student-b.returned.json'), JSON.stringify(returnPayload, null, 2))
  await page.screenshot({ path: path.join(runDir, 'student-b-return-pending.png'), fullPage: true })
  await record('return_submitted', returnPayload)

  await waitForMarker('final-check.go')
  await page.goto(`${baseURL}/reservations/${booked.reservationId}`, { waitUntil: 'networkidle' })
  await page.locator('.rsv-detail__layout').waitFor({ state: 'visible', timeout: 20_000 })
  const completedStatus = page.getByText('已完成', { exact: true })
  await completedStatus.waitFor({ state: 'visible', timeout: 20_000 })
  await expectReservationPurpose(page, purpose)
  await page.screenshot({ path: path.join(runDir, 'student-b-completed-detail.png'), fullPage: true })
  await writeFile(marker('student-b.final.json'), JSON.stringify({ ...booked, finalStatus: 'COMPLETED', verifiedAt: new Date().toISOString() }, null, 2))
  await record('final_chain_verified', { ...booked, finalStatus: 'COMPLETED' })

  assert(browserErrors.length === 0, `Browser console/page errors: ${browserErrors.slice(0, 8).join(' | ')}`)
  await record('script_passed', { reservationId: booked.reservationId, deviceId: booked.deviceId, browserErrors: browserErrors.length })
  }
} catch (error) {
  await record('script_failed', { error: String(error), browserErrors: browserErrors.slice(0, 10) })
  throw error
} finally {
  await context.close().catch(() => {})
  await browser.close()
}

async function expectReservationPurpose(activePage, expectedPurpose) {
  const purposeText = activePage.locator('.rsv-detail__purpose-text')
  assert((await purposeText.innerText()) === expectedPurpose, 'Reservation detail purpose did not match the user-created booking.')
}
