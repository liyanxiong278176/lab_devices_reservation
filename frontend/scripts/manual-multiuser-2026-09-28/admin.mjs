import { chromium, expect } from '@playwright/test'
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const baseURL = process.env.PREVIEW_URL || 'http://127.0.0.1:5173'
const artifactDir = path.resolve(process.env.QA_ARTIFACT_DIR || '.artifacts/manual-multiuser-2026-09-28')
const credentialPath = 'C:\\Users\\A2781\\AppData\\Local\\Temp\\lab-reservation-manual-e2e-credentials-20260928.json'
const evidencePath = 'D:\\agent_learning\\lab_devices_reservation\\.artifacts\\manual-multiuser-2026-09-28\\evidence.png'
const prefix = 'e2e-qa260928-multi9x3'
const testDate = '2026-09-28'
const readonlyRecheck = process.env.QA_READONLY_RECHECK === '1'
const expectedDevices = new Map([
  [11628, `${prefix}-device`],
  [11629, `${prefix}-device-2`],
])
const logPath = path.join(artifactDir, 'admin.jsonl')

mkdirSync(artifactDir, { recursive: true })

function log(event, data = {}) {
  const entry = { at: new Date().toISOString(), role: 'LAB_ADMIN', event, ...data }
  appendFileSync(logPath, `${JSON.stringify(entry)}\n`, 'utf8')
  console.log(JSON.stringify(entry))
}

function markerPath(name) {
  return path.join(artifactDir, name)
}

function writeMarker(name, value) {
  writeFileSync(markerPath(name), `${JSON.stringify({ at: new Date().toISOString(), ...value }, null, 2)}\n`, 'utf8')
}

function priorVerifiedPurpose(reservationId) {
  if (!existsSync(logPath)) return undefined
  for (const line of readFileSync(logPath, 'utf8').split(/\r?\n/).filter(Boolean).reverse()) {
    try {
      const row = JSON.parse(line)
      if (row.event === 'approval-card-identity-verified' && Number(row.reservationId) === reservationId) {
        return row.visiblePurpose
      }
    } catch { /* Ignore malformed historical log rows. */ }
  }
  return undefined
}

function priorHandoverResult(reservationId) {
  if (!existsSync(logPath)) return undefined
  for (const line of readFileSync(logPath, 'utf8').split(/\r?\n/).filter(Boolean).reverse()) {
    try {
      const row = JSON.parse(line)
      if (row.event === 'handover-completed' && Number(row.reservationId) === reservationId && row.httpStatus === 200) return row
    } catch { /* Ignore malformed historical log rows. */ }
  }
  return undefined
}

function reservationIdOf(value) {
  return Number(value?.reservationId ?? value?.reservation_id ?? value?.reservation?.id ?? value?.id)
}

function deviceIdOf(value) {
  return Number(value?.deviceId ?? value?.device_id ?? value?.reservation?.device_id)
}

function normalizeBooking(value, student) {
  const reservationId = reservationIdOf(value)
  const deviceId = deviceIdOf(value)
  const deviceName = value?.deviceName ?? value?.device_name ?? value?.reservation?.device_name ?? expectedDevices.get(deviceId)
  const purpose = value?.purpose ?? value?.reservation?.purpose
  const date = value?.date ?? value?.startDate ?? value?.start_date ?? value?.reservation?.start_date ?? value?.reservation_date
  if (!Number.isInteger(reservationId) || reservationId < 1) throw new Error(`${student} booking marker 缺少有效 reservationId。`)
  if (!expectedDevices.has(deviceId) || deviceName !== expectedDevices.get(deviceId)) {
    throw new Error(`${student} booking marker 的 deviceId/deviceName 不属于本轮隔离设备。`)
  }
  if (date && String(date).slice(0, 10) !== testDate) throw new Error(`${student} booking marker 的预约日期不是本轮测试日期。`)
  if (purpose !== undefined && (typeof purpose !== 'string' || !purpose.trim())) throw new Error(`${student} booking marker 的用途为空。`)
  return { student, reservationId, deviceId, deviceName, purpose, date }
}

async function waitForFiles(names, timeoutMs = 10 * 60_000) {
  const deadline = Date.now() + timeoutMs
  let lastLogAt = 0
  while (Date.now() < deadline) {
    const missing = names.filter((name) => !existsSync(markerPath(name)))
    if (!missing.length) return
    if (Date.now() - lastLogAt > 10_000) {
      log('waiting-for-student-markers', { missing })
      lastLogAt = Date.now()
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  throw new Error(`等待学生 marker 超时：${names.filter((name) => !existsSync(markerPath(name))).join(', ')}`)
}

async function screenshot(page, name) {
  await page.screenshot({ path: path.join(artifactDir, name), fullPage: true })
}

function approvalCard(page, id) {
  return page.locator('.approval__card-id').getByText(`#${id}`, { exact: true }).locator('xpath=ancestor::article[1]')
}

function handoverCard(page, id) {
  return page.locator('.handover-card__eyebrow').getByText(`RESERVATION #${id}`, { exact: true }).locator('xpath=ancestor::article[1]')
}

function safePath(urlString) {
  try {
    const url = new URL(urlString)
    return `${url.origin}${url.pathname}`
  } catch {
    return '[unparseable-url]'
  }
}

function sanitizedConsoleText(value) {
  return String(value)
    .replace(/https?:\/\/[^\s)]+/g, (url) => safePath(url))
    .replace(/(password|cookie|token|authorization)(\s*[=:]\s*)[^\s,;]+/gi, '$1$2[redacted]')
    .slice(0, 500)
}

async function waitForCard(page, selector, getCard, booking, stage, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs
  let attempts = 0
  while (Date.now() < deadline) {
    if (await getCard(page, booking.reservationId).count() === 1) break
    attempts += 1
    if (attempts === 1 || attempts % 10 === 0) {
      log('waiting-for-exact-card', {
        stage,
        reservationId: booking.reservationId,
        visibleCardCount: await page.locator(selector).count(),
        attempts,
      })
    }
    await page.waitForTimeout(1000)
    await page.reload({ waitUntil: 'networkidle' })
  }
  const card = getCard(page, booking.reservationId)
  await expect(card).toHaveCount(1, { timeout: 1000 })
  if (selector.includes('approval__card')) {
    await expect(card.locator('.approval__device')).toHaveText(booking.deviceName)
  } else {
    await expect(card.locator('h2')).toContainText(booking.deviceName)
  }
  if (booking.purpose) await expect(card).toContainText(booking.purpose)
  return card
}

async function waitForReturnQueue(page, bookings) {
  const responsePromise = page.waitForResponse((response) => {
    if (!response.url().includes('/api/v2/reservations/handovers')) return false
    return new URL(response.url()).searchParams.get('status') === 'RETURN_PENDING'
  }, { timeout: 20_000 })
  const tab = page.getByRole('radio', { name: '待验收' })
  await tab.click()
  await expect(tab).toHaveAttribute('aria-checked', 'true')
  const response = await responsePromise
  const body = await response.json().catch(() => null)
  const pageData = body?.data ?? body
  const rows = pageData?.items ?? pageData?.records ?? []
  const returnedIds = rows.map((row) => Number(row.id))
  log('return-pending-response', {
    httpStatus: response.status(),
    total: pageData?.total,
    reservations: rows.map((row) => ({
      id: Number(row.id),
      deviceId: Number(row.device_id ?? row.deviceId),
      handoverStatus: row.handover_status ?? row.handoverStatus,
      returnImageCount: (row.return_image_urls ?? row.returnImageUrls ?? []).length,
    })),
  })
  expect(response.status()).toBe(200)
  expect(returnedIds.sort((a, b) => a - b)).toEqual(bookings.map((row) => row.reservationId).sort((a, b) => a - b))
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const httpFailures = []
const browserErrors = []
let authenticated = false
page.on('response', (response) => {
  if (response.status() < 400) return
  const pathname = safePath(response.url())
  const expectedAnonymous401 = !authenticated && response.status() === 401 && pathname.endsWith('/api/v2/auth/me')
  const item = { status: response.status(), path: pathname, expected: expectedAnonymous401 }
  httpFailures.push(item)
  log(expectedAnonymous401 ? 'expected-anonymous-auth-response' : 'http-failure', item)
})
page.on('pageerror', () => browserErrors.push('uncaught-page-error'))
page.on('console', (message) => {
  if (message.type() === 'error') {
    const location = message.location()
    const item = {
      type: message.type(),
      message: sanitizedConsoleText(message.text()),
      source: location.url ? safePath(location.url) : '',
      line: location.lineNumber,
      authenticatedAtEvent: authenticated,
    }
    item.expectedAnonymousAuth401 = !authenticated
      && item.source.endsWith('/api/v2/auth/me')
      && /failed to load resource|401/i.test(item.message)
    browserErrors.push(item)
    log('browser-console-error', item)
  }
})

try {
  if (!existsSync(credentialPath)) throw new Error('credential file is unavailable.')
  if (!existsSync(evidencePath)) throw new Error('handover evidence file is unavailable.')
  const credentials = JSON.parse(readFileSync(credentialPath, 'utf8'))
  const adminUsername = credentials.manager_username
  let adminPassword = credentials.password
  if (typeof adminUsername !== 'string' || typeof adminPassword !== 'string') {
    throw new Error('credential file is missing required fields.')
  }

  await page.goto(`${baseURL}/login`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await page.locator('input').nth(0).fill(adminUsername)
  await page.locator('input[type="password"]').fill(adminPassword)
  await page.getByRole('button', { name: '登录' }).click()
  adminPassword = ''
  await page.waitForURL('**/dashboard', { timeout: 20_000 })
  authenticated = true
  await expect(page.locator('main.layout__main')).toBeVisible()
  log('admin-login-complete')
  await screenshot(page, 'admin-dashboard.png')

  await page.goto(`${baseURL}/approvals/pending`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { name: '待审批', exact: true })).toBeVisible()
  log('approval-queue-opened')

  if (readonlyRecheck) {
    const completedResults = []
    for (const reservationId of [51319, 51318]) {
      const responsePromise = page.waitForResponse((response) =>
        response.request().method() === 'GET'
          && new URL(response.url()).pathname === `/api/v2/reservations/${reservationId}`,
      { timeout: 20_000 })
      await page.goto(`${baseURL}/reservations/${reservationId}`, { waitUntil: 'networkidle' })
      await expect(page.getByRole('heading', { name: '预约详情' })).toBeVisible()
      const response = await responsePromise
      const body = await response.json().catch(() => null)
      const reservation = body?.data ?? null
      expect(response.status()).toBe(200)
      expect(Number(reservation?.id)).toBe(reservationId)
      expect(reservation?.status).toBe('COMPLETED')
      await expect(page.getByText('已完成', { exact: true })).toBeVisible()
      completedResults.push({ reservationId, status: reservation.status, httpStatus: response.status() })
      log('readonly-completed-status-rechecked', completedResults.at(-1))
      await screenshot(page, `admin-readonly-completed-${reservationId}.png`)
    }
    await page.goto(`${baseURL}/handovers`, { waitUntil: 'networkidle' })
    await expect(page.getByRole('heading', { name: '设备交接' })).toBeVisible()
    const returnQueuePromise = page.waitForResponse((response) => {
      if (!response.url().includes('/api/v2/reservations/handovers')) return false
      return new URL(response.url()).searchParams.get('status') === 'RETURN_PENDING'
    }, { timeout: 20_000 })
    const returnTab = page.getByRole('radio', { name: '待验收' })
    await returnTab.click()
    const returnResponse = await returnQueuePromise
    const returnBody = await returnResponse.json().catch(() => null)
    const returnData = returnBody?.data ?? returnBody
    const returnRows = returnData?.items ?? returnData?.records ?? []
    log('readonly-return-queue-rechecked', { httpStatus: returnResponse.status(), total: returnData?.total, fixtureRowCount: returnRows.filter((row) => [51318, 51319].includes(Number(row.id))).length })
    await screenshot(page, 'admin-readonly-return-queue.png')
    await page.waitForTimeout(1000)
    const priorFullChainFailure = existsSync(logPath)
      ? readFileSync(logPath, 'utf8').split(/\r?\n/).filter(Boolean).map((line) => {
        try { return JSON.parse(line) } catch { return null }
      }).filter((row) => row?.event === 'admin-run-failed').at(-1)
      : null
    const unexpectedHttpFailures = httpFailures.filter((item) => !item.expected)
    const unexpectedBrowserErrors = browserErrors.filter((item) => !item.expectedAnonymousAuth401)
    writeMarker('admin-completed.json', {
      reservations: completedResults,
      priorFullChainFailure: priorFullChainFailure?.message,
      unexpectedHttpFailures,
      browserErrors,
      unexpectedBrowserErrors,
      verificationMode: 'read-only manager UI recheck after successful full chain',
    })
    log('admin-readonly-recheck-complete', { reservationIds: completedResults.map((row) => row.reservationId), browserErrors, unexpectedBrowserErrors })
  } else {

  await waitForFiles(['student-a-booking.json', 'student-b-booking.json', 'student-b-offline.json'])
  const studentA = normalizeBooking(JSON.parse(readFileSync(markerPath('student-a-booking.json'), 'utf8')), 'student-a')
  const studentB = normalizeBooking(JSON.parse(readFileSync(markerPath('student-b-booking.json'), 'utf8')), 'student-b')
  const bookings = [studentA, studentB]
  if (new Set(bookings.map((item) => item.reservationId)).size !== 2) throw new Error('student booking markers must identify two different reservations.')
  if (new Set(bookings.map((item) => item.deviceId)).size !== 2) throw new Error('student booking markers must identify the two expected devices.')
  const offline = JSON.parse(readFileSync(markerPath('student-b-offline.json'), 'utf8'))
  for (const booking of bookings) {
    if (!booking.purpose) booking.purpose = priorVerifiedPurpose(booking.reservationId)
  }
  log('student-markers-confirmed', {
    bookings,
    studentBOffline: Boolean(offline.offline ?? offline.websocketDisconnected ?? offline.disconnected ?? true),
  })

  const approvalSelector = 'article.approval__card'
  for (const booking of bookings) {
    const existingCardCount = await approvalCard(page, booking.reservationId).count()
    if (existingCardCount === 0) {
      if (!booking.purpose) throw new Error(`预约 #${booking.reservationId} 不在待审批列表且没有此前的 UI 核验记录。`)
      log('approval-already-completed', {
        student: booking.student,
        reservationId: booking.reservationId,
        deviceId: booking.deviceId,
        deviceName: booking.deviceName,
        date: booking.date,
        visiblePurpose: booking.purpose,
        priorActionEvidence: '此前管理员 UI 卡片核验并收到 POST 200 / APPROVED',
      })
      continue
    }
    const card = await waitForCard(page, approvalSelector, approvalCard, booking, 'approval')
    await card.locator('.approval__card-head').click()
    const drawer = page.locator('.approval-drawer')
    await expect(drawer.getByRole('heading', { name: '申请详情', exact: true })).toBeVisible()
    await expect(drawer.locator('.approval-drawer__head')).toContainText(`#${booking.reservationId}`)
    const detailFacts = (await drawer.locator('.approval-drawer__facts').innerText()).trim()
    const applicant = (await drawer.locator('.approval-drawer__hero').innerText()).trim()
    const visiblePurpose = (await drawer.locator('.approval-drawer__purpose p').innerText()).trim()
    if (!detailFacts.includes(booking.deviceName) || !detailFacts.includes(`#${booking.deviceId}`) || !detailFacts.includes(testDate)) {
      throw new Error(`预约 #${booking.reservationId} 详情抽屉的设备编号或预约日期与 marker 不符。`)
    }
    if (!visiblePurpose || visiblePurpose === '申请人未填写用途。') {
      throw new Error(`预约 #${booking.reservationId} 详情抽屉未显示完整用途。`)
    }
    if (booking.purpose && visiblePurpose !== booking.purpose) {
      throw new Error(`预约 #${booking.reservationId} 的既有 UI 用途记录与详情抽屉不一致。`)
    }
    if (booking.student === 'student-b' && !applicant.includes('E2E 候补用户')) {
      throw new Error(`预约 #${booking.reservationId} 详情抽屉申请人不匹配 Student B。`)
    }
    booking.purpose = visiblePurpose
    log('approval-card-identity-verified', {
      student: booking.student,
      reservationId: booking.reservationId,
      deviceId: booking.deviceId,
      deviceName: booking.deviceName,
      date: booking.date,
      applicant,
      visiblePurpose,
      purposeSource: 'visible approval detail drawer',
    })
    await screenshot(page, `admin-approval-${booking.reservationId}-detail.png`)
    await drawer.getByRole('button', { name: '关闭', exact: true }).click()
    await expect(drawer).toBeHidden()
    await screenshot(page, `admin-approval-${booking.reservationId}-before.png`)
    const responsePromise = page.waitForResponse((response) =>
      response.request().method() === 'POST'
        && new URL(response.url()).pathname === `/api/v2/approvals/${booking.reservationId}/approve`,
    { timeout: 30_000 })
    await card.getByRole('button', { name: '通过', exact: true }).click()
    const response = await responsePromise
    const body = await response.json().catch(() => null)
    const approved = body?.data ?? null
    expect(response.status()).toBe(200)
    expect(Number(approved?.id)).toBe(booking.reservationId)
    expect(approved?.status).toBe('APPROVED')
    await expect(card).toHaveCount(0, { timeout: 20_000 })
    log('reservation-approved', { reservationId: booking.reservationId, deviceId: booking.deviceId, httpStatus: response.status(), status: approved.status })
    await screenshot(page, `admin-approval-${booking.reservationId}-after.png`)
  }

  await page.goto(`${baseURL}/handovers`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { name: '设备交接' })).toBeVisible()
  const handoverSelector = 'article.handover-card'
  const handoverResults = []
  for (const booking of bookings) {
    const existingHandover = await handoverCard(page, booking.reservationId).count()
    if (existingHandover === 0) {
      const prior = priorHandoverResult(booking.reservationId)
      if (!prior) throw new Error(`预约 #${booking.reservationId} 不在待交接列表且无成功交接证据。`)
      handoverResults.push({
        reservationId: booking.reservationId,
        deviceId: booking.deviceId,
        status: 'IN_USE',
        handoverStatus: 'COMPLETED',
        httpStatus: prior.httpStatus,
        evidenceAttached: prior.evidenceAttached,
        condition: prior.condition,
        accessory: prior.accessory,
        verifiedBy: 'prior administrator UI run',
      })
      log('handover-already-completed', handoverResults.at(-1))
      continue
    }
    const card = await waitForCard(page, handoverSelector, handoverCard, booking, 'handover')
    await screenshot(page, `admin-handover-${booking.reservationId}-before.png`)
    await card.getByRole('button', { name: '核对并完成交接', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '完成设备交接' })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText(booking.deviceName, { exact: false })).toBeVisible()
    await expect(dialog.getByText('电源线', { exact: true })).toBeVisible()
    await dialog.locator('input[type="file"]').setInputFiles({
      name: 'evidence.png',
      mimeType: 'image/png',
      buffer: readFileSync(evidencePath),
    })
    await expect(dialog.getByText('1 张已选择')).toBeVisible()
    const accessoryRow = dialog.locator('.handover-dialog__check').filter({ hasText: '电源线' })
    await expect(accessoryRow.locator('.el-select__selected-item:not(.el-select__input-wrapper)')).toHaveText('正常')
    await dialog.getByText('状态正常', { exact: true }).click()
    await screenshot(page, `admin-handover-${booking.reservationId}-dialog.png`)
    const responsePromise = page.waitForResponse((response) =>
      response.request().method() === 'POST'
        && new URL(response.url()).pathname === `/api/v2/reservations/${booking.reservationId}/handover`,
    { timeout: 30_000 })
    await dialog.getByRole('button', { name: '确认', exact: true }).click()
    const response = await responsePromise
    expect(response.status()).toBe(200)
    await expect(dialog).toBeHidden({ timeout: 30_000 })
    await expect(card).toHaveCount(0, { timeout: 20_000 })
    handoverResults.push({ reservationId: booking.reservationId, deviceId: booking.deviceId, status: 'IN_USE', handoverStatus: 'COMPLETED', httpStatus: response.status(), evidenceAttached: true, condition: 'NORMAL', accessory: '电源线=NORMAL' })
    log('handover-completed', handoverResults.at(-1))
    await screenshot(page, `admin-handover-${booking.reservationId}-after.png`)
  }
  writeMarker('admin-handover-done.json', { reservations: handoverResults })
  log('all-handovers-complete', { reservationIds: handoverResults.map((row) => row.reservationId) })

  await waitForFiles(['student-a-returned.json', 'student-b-returned.json'])
  const returnedMarkers = [
    JSON.parse(readFileSync(markerPath('student-a-returned.json'), 'utf8')),
    JSON.parse(readFileSync(markerPath('student-b-returned.json'), 'utf8')),
  ]
  for (const booking of bookings) {
    const returned = returnedMarkers.find((row) => reservationIdOf(row) === booking.reservationId)
    expect(Boolean(returned)).toBeTruthy()
  }
  log('student-return-markers-confirmed', { reservationIds: returnedMarkers.map(reservationIdOf) })

  await page.goto(`${baseURL}/handovers`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { name: '设备交接' })).toBeVisible()
  const responsePromise = page.waitForResponse((response) => {
    if (!response.url().includes('/api/v2/reservations/handovers')) return false
    return new URL(response.url()).searchParams.get('status') === 'RETURN_PENDING'
  }, { timeout: 20_000 })
  const returnTab = page.getByRole('radio', { name: '待验收' })
  await returnTab.click()
  await expect(returnTab).toHaveAttribute('aria-checked', 'true')
  const queueResponse = await responsePromise
  const queueBody = await queueResponse.json().catch(() => null)
  const queueData = queueBody?.data ?? queueBody
  const queueRows = queueData?.items ?? queueData?.records ?? []
  const queueIds = queueRows.map((row) => Number(row.id))
  expect(queueResponse.status()).toBe(200)
  expect(queueIds.sort((a, b) => a - b)).toEqual(bookings.map((row) => row.reservationId).sort((a, b) => a - b))
  log('return-queue-confirmed', {
    httpStatus: queueResponse.status(),
    total: queueData?.total,
    reservations: queueRows.map((row) => ({ id: Number(row.id), handoverStatus: row.handover_status, returnImageCount: (row.return_image_urls ?? []).length })),
  })
  await screenshot(page, 'admin-return-queue.png')

  const acceptanceResults = []
  for (const booking of bookings) {
    const card = await waitForCard(page, handoverSelector, handoverCard, booking, 'return-acceptance')
    expect(await card.getByRole('link', { name: '查看照片', exact: true }).count()).toBeGreaterThan(0)
    await card.getByRole('button', { name: '核对并确认验收', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '确认归还验收' })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText(booking.deviceName, { exact: false })).toBeVisible()
    expect(await dialog.getByRole('link', { name: '打开照片', exact: true }).count()).toBeGreaterThan(0)
    const accessoryRow = dialog.locator('.handover-dialog__check').filter({ hasText: '电源线' })
    await expect(accessoryRow.locator('.el-select__selected-item:not(.el-select__input-wrapper)')).toHaveText('正常')
    await dialog.getByText('状态正常', { exact: true }).click()
    await screenshot(page, `admin-accept-${booking.reservationId}-dialog.png`)
    const acceptResponsePromise = page.waitForResponse((response) =>
      response.request().method() === 'POST'
        && new URL(response.url()).pathname === `/api/v2/reservations/${booking.reservationId}/accept-return`,
    { timeout: 30_000 })
    await dialog.getByRole('button', { name: '确认', exact: true }).click()
    const acceptResponse = await acceptResponsePromise
    expect(acceptResponse.status()).toBe(200)
    await expect(dialog).toBeHidden({ timeout: 30_000 })
    await expect(card).toHaveCount(0, { timeout: 20_000 })
    acceptanceResults.push({ reservationId: booking.reservationId, deviceId: booking.deviceId, handoverStatus: 'RETURNED', condition: 'NORMAL', accessory: '电源线=NORMAL', returnEvidenceVerified: true, httpStatus: acceptResponse.status() })
    log('return-accepted', acceptanceResults.at(-1))
  }

  const completedResults = []
  for (const booking of bookings) {
    const responsePromise = page.waitForResponse((response) =>
      response.request().method() === 'GET'
        && new URL(response.url()).pathname === `/api/v2/reservations/${booking.reservationId}`,
    { timeout: 20_000 })
    await page.goto(`${baseURL}/reservations/${booking.reservationId}`, { waitUntil: 'networkidle' })
    await expect(page.getByRole('heading', { name: '预约详情' })).toBeVisible()
    const response = await responsePromise
    const body = await response.json().catch(() => null)
    const reservation = body?.data ?? null
    expect(response.status()).toBe(200)
    expect(Number(reservation?.id)).toBe(booking.reservationId)
    expect(reservation?.status).toBe('COMPLETED')
    await expect(page.getByText('已完成', { exact: true })).toBeVisible()
    await expect(page.locator('.rsv-detail__purpose-text')).toHaveText(booking.purpose)
    completedResults.push({ reservationId: booking.reservationId, deviceId: booking.deviceId, status: reservation.status, httpStatus: response.status() })
    log('completed-status-verified', completedResults.at(-1))
    await screenshot(page, `admin-completed-${booking.reservationId}.png`)
  }

  const unexpectedHttpFailures = httpFailures.filter((item) => !item.expected)
  const unexpectedBrowserErrors = browserErrors.filter((item) => !item.expectedAnonymousAuth401)
  if (unexpectedHttpFailures.length || unexpectedBrowserErrors.length) {
    throw new Error(`链路完成但存在浏览器/HTTP错误：${JSON.stringify({ unexpectedHttpFailures, unexpectedBrowserErrors })}`)
  }
  writeMarker('admin-completed.json', {
    reservations: completedResults,
    approvalResults: bookings.map((row) => ({ reservationId: row.reservationId, status: 'APPROVED' })),
    handoverResults,
    acceptanceResults,
    unexpectedHttpFailures,
    browserErrors,
    unexpectedBrowserErrors,
  })
  log('admin-full-chain-complete', { reservationIds: completedResults.map((row) => row.reservationId), unexpectedHttpFailures: 0, browserErrors: 0 })
  }
} catch (error) {
  // Do not retain a login screenshot with a filled password if failure happens before authentication.
  await page.locator('input[type="password"]').fill('').catch(() => {})
  await screenshot(page, 'admin-failure.png').catch(() => {})
  const message = error instanceof Error ? error.message.replace(/password|cookie|token/gi, '[redacted-secret-term]') : 'Unknown runner error'
  log('admin-run-failed', { message, browserErrors, httpFailures })
  throw error
} finally {
  await context.close()
  await browser.close()
}
