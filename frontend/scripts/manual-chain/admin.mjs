import { chromium, expect } from '@playwright/test'
import { mkdirSync, appendFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const baseURL = process.env.PREVIEW_URL || 'http://127.0.0.1:18080'
const username = process.env.QA_ADMIN_USERNAME || 'e2e-multi-qa260928-admin'
const password = process.env.QA_ADMIN_PASSWORD || 'E2e-123456'
const fixturePrefix = 'e2e-multi-qa260928'
const deviceNames = [`${fixturePrefix}-device`, `${fixturePrefix}-device-2`]
const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const projectRoot = path.resolve(scriptDir, '../../..')
const artifactDir = path.resolve(process.env.QA_ARTIFACT_DIR || path.join(projectRoot, '.artifacts/manual-multi-flow/e2e-multi-qa260928'))
const logPath = path.join(artifactDir, 'admin.jsonl')
const signalPath = (name) => path.join(artifactDir, name)

mkdirSync(artifactDir, { recursive: true })

function log(event, data = {}) {
  const entry = { at: new Date().toISOString(), role: 'SYS_ADMIN', event, ...data }
  appendFileSync(logPath, `${JSON.stringify(entry)}\n`, 'utf8')
  console.log(JSON.stringify(entry))
}

function writeSignal(name, data = {}) {
  writeFileSync(signalPath(name), `${JSON.stringify({ at: new Date().toISOString(), ...data }, null, 2)}\n`, 'utf8')
}

async function waitForSignal(name, timeoutMs = 10 * 60 * 1000) {
  const deadline = Date.now() + timeoutMs
  log('waiting-for-signal', { signal: name })
  while (Date.now() < deadline) {
    if (existsSync(signalPath(name))) {
      log('received-signal', { signal: name })
      return
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  throw new Error(`Timed out waiting for ${name}`)
}

async function waitForAnySignal(names, timeoutMs = 10 * 60 * 1000) {
  const deadline = Date.now() + timeoutMs
  log('waiting-for-any-signal', { signals: names })
  while (Date.now() < deadline) {
    const signal = names.find((name) => existsSync(signalPath(name)))
    if (signal) {
      log('received-signal', { signal })
      return signal
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  throw new Error(`Timed out waiting for any of ${names.join(', ')}`)
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function reservationCard(page, selector, reservationId) {
  const marker = selector.includes('approval__card')
    ? page.locator('.approval__card-id').getByText(`#${reservationId}`, { exact: true })
    : page.locator('.handover-card__eyebrow').getByText(`RESERVATION #${reservationId}`, { exact: true })
  return marker.locator('xpath=ancestor::article[1]')
}

async function activateReturnPendingTab(page) {
  const responsePromise = page.waitForResponse((response) => {
    if (!response.url().includes('/api/v2/reservations/handovers')) return false
    return new URL(response.url()).searchParams.get('status') === 'RETURN_PENDING'
  }, { timeout: 15_000 })
  const returnTab = page.getByRole('radio', { name: '待验收' })
  await returnTab.click()
  await expect(returnTab).toHaveAttribute('aria-checked', 'true')
  const response = await responsePromise
  const body = await response.json()
  const pageData = body?.data ?? body
  const records = pageData?.items ?? pageData?.records ?? []
  log('return-pending-api-response', {
    httpStatus: response.status(),
    code: body?.code,
    total: pageData?.total,
    reservations: records.map((row) => ({
      id: row.id,
      deviceId: row.device_id ?? row.deviceId,
      deviceName: row.device_name ?? row.deviceName,
      status: row.status,
      handoverStatus: row.handover_status ?? row.handoverStatus,
      returnImageCount: (row.return_image_urls ?? row.returnImageUrls ?? []).length,
    })),
  })
  expect(response.status()).toBe(200)
}

async function readBookingTargets() {
  const files = [
    path.join(artifactDir, 'student-a.booked.json'),
    path.join(artifactDir, 'student-b.booked.json'),
  ]
  const deadline = Date.now() + 5 * 60_000
  while (Date.now() < deadline) {
    if (files.every(existsSync)) {
      const a = JSON.parse(readFileSync(files[0], 'utf8'))
      const b = JSON.parse(readFileSync(files[1], 'utf8'))
      const targets = [
        { reservationId: Number(a.reservationId), deviceId: Number(a.deviceId), deviceName: a.deviceName, purpose: a.purpose },
        {
          reservationId: Number(b.reservationId),
          deviceId: Number(b.deviceId),
          deviceName: Number(b.deviceId) === 14 ? deviceNames[1] : deviceNames[0],
          purpose: b.purpose,
        },
      ]
      expect(targets.map((target) => target.reservationId).every((id) => id > 0)).toBeTruthy()
      expect(targets.map((target) => target.deviceName).sort()).toEqual([...deviceNames].sort())
      log('booking-targets-loaded', { targets })
      return targets
    }
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  throw new Error(`学生预约记录标记未齐：${files.join(', ')}`)
}

async function verifyReservationCard(card, selector, target) {
  await expect(card).toHaveCount(1)
  if (selector.includes('approval__card')) {
    await expect(card.locator('.approval__device')).toHaveText(target.deviceName)
  } else {
    const heading = (await card.locator('h2').innerText()).replace(/\s+/g, ' ').trim()
    expect(heading).toMatch(new RegExp(`^#\\S+ · ${escapeRegExp(target.deviceName)}$`))
  }
  await expect(card).toContainText(target.purpose)
}

async function waitForEachTarget(page, selector, label, targets) {
  const deadline = Date.now() + 5 * 60_000
  let attempts = 0
  while (Date.now() < deadline) {
    const totalCards = await page.locator(selector).count()
    const counts = await Promise.all(targets.map((target) => reservationCard(page, selector, target.reservationId).count()))
    if (totalCards === 2 && counts.every((count) => count === 1)) {
      for (const target of targets) await verifyReservationCard(reservationCard(page, selector, target.reservationId), selector, target)
      return
    }
    attempts += 1
    if (attempts % 5 === 1) {
      const cardTexts = await page.locator(selector).allTextContents()
      log('queue-wait-refresh', { label, counts, totalCards, cardTexts, attempts })
    }
    await page.waitForTimeout(1000)
    await page.reload({ waitUntil: 'networkidle' })
    if (label === '待验收队列') {
      await activateReturnPendingTab(page)
    }
  }
  throw new Error(`等待 ${label} 中的两个 fixture 设备超时`)
}

async function screenshot(page, name) {
  await page.screenshot({ path: path.join(artifactDir, name), fullPage: true })
}

async function runRealtimeApproval(page) {
  await page.goto(`${baseURL}/login`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await page.locator('input').nth(0).fill(username)
  await page.locator('input').nth(1).fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL('**/dashboard', { timeout: 20_000 })
  await expect(page.locator('main.layout__main')).toBeVisible()
  log('realtime-admin-logged-in', { username, url: page.url() })

  const readyPath = signalPath('student-a.realtime.ready.json')
  const deadline = Date.now() + 5 * 60_000
  while (!existsSync(readyPath) && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }
  if (!existsSync(readyPath)) throw new Error('等待 student-a.realtime.ready.json 超时')
  const target = JSON.parse(readFileSync(readyPath, 'utf8'))
  const reservationId = Number(target.reservationId)
  expect(reservationId).toBe(5)
  expect(Number(target.deviceId)).toBe(13)
  expect(target.deviceName).toBe(deviceNames[0])
  expect(target.date).toBe('2026-09-29')
  log('realtime-target-loaded', { reservationId, deviceId: target.deviceId, deviceName: target.deviceName, date: target.date, purpose: target.purpose })

  await page.goto(`${baseURL}/approvals/pending`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { name: '待审批', exact: true })).toBeVisible()
  const selector = 'article.approval__card'
  const card = reservationCard(page, selector, reservationId)
  const queueDeadline = Date.now() + 90_000
  while (Date.now() < queueDeadline && (await card.count()) !== 1) {
    log('realtime-approval-wait-refresh', {
      reservationId,
      visibleCards: await page.locator(selector).allTextContents(),
    })
    await page.waitForTimeout(1000)
    await page.reload({ waitUntil: 'networkidle' })
  }
  await expect(card).toHaveCount(1)
  await expect(card.locator('.approval__device')).toHaveText(target.deviceName)
  await expect(card).toContainText(target.purpose)
  await screenshot(page, 'admin-realtime-approval-before.png')

  const responsePromise = page.waitForResponse((response) =>
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === `/api/v2/approvals/${reservationId}/approve`,
  { timeout: 30_000 })
  await card.getByRole('button', { name: '通过', exact: true }).click()
  const response = await responsePromise
  const responseBody = await response.json().catch(() => null)
  expect(response.status()).toBe(200)
  await expect(card).toHaveCount(0, { timeout: 20_000 })
  await screenshot(page, 'admin-realtime-approval-after.png')
  const result = {
    reservationId,
    deviceId: Number(target.deviceId),
    deviceName: target.deviceName,
    date: target.date,
    purpose: target.purpose,
    httpStatus: response.status(),
    responseBody,
    approvedThroughUi: true,
  }
  writeSignal('admin.realtime-approval-complete', result)
  log('realtime-approval-complete', result)
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const pageErrors = []
const failedResponses = []
page.on('pageerror', (error) => pageErrors.push(error.message))
page.on('response', (response) => {
  if (response.status() >= 500) failedResponses.push(`${response.status()} ${response.url()}`)
})

try {
  if (process.argv[2] === 'realtime') {
    await runRealtimeApproval(page)
  } else {
  await page.goto(`${baseURL}/login`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await page.locator('input').nth(0).fill(username)
  await page.locator('input').nth(1).fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL('**/dashboard', { timeout: 20_000 })
  await expect(page.locator('main.layout__main')).toBeVisible()
  log('logged-in', { username, url: page.url() })
  await screenshot(page, 'admin-dashboard.png')

  await page.goto(`${baseURL}/approvals/pending`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { name: '待审批', exact: true })).toBeVisible()
  const approvalSelector = 'article.approval__card'
  const targets = await readBookingTargets()
  const approvalCardTexts = await page.locator(approvalSelector).allTextContents()
  const initialApprovalCounts = await Promise.all(targets.map((target) => reservationCard(page, approvalSelector, target.reservationId).count()))
  log('approval-card-snapshot', { approvalCardTexts, initialApprovalCounts })
  await screenshot(page, 'admin-approval-observed.png')
  if (initialApprovalCounts.every((count) => count === 0) && approvalCardTexts.length === 0) {
    log('approval-stage-resumed', { reservationIds: targets.map((target) => target.reservationId), reason: 'approval queue is already empty' })
  } else {
    await waitForEachTarget(page, approvalSelector, '待审批队列', targets)
    const targetApprovalCards = await Promise.all(targets.map((target) => reservationCard(page, approvalSelector, target.reservationId).count()))
    expect(targetApprovalCards).toEqual([1, 1])
    await screenshot(page, 'admin-approvals-before.png')
    log('approval-queue-confirmed', { deviceNames, targetApprovalCards })

    for (const target of targets) {
      const card = reservationCard(page, approvalSelector, target.reservationId)
      await expect(card.getByRole('button', { name: '通过', exact: true })).toBeVisible()
      await card.getByRole('button', { name: '通过', exact: true }).click()
      await expect(card).toHaveCount(0, { timeout: 20_000 })
      log('reservation-approved', { reservationId: target.reservationId, deviceName: target.deviceName, username: target.username })
    }
    await screenshot(page, 'admin-approvals-after.png')
  }

  await page.goto(`${baseURL}/handovers`, { waitUntil: 'networkidle' })
  await expect(page.getByRole('heading', { name: '设备交接' })).toBeVisible()
  const handoverSelector = 'article.handover-card'
  if (existsSync(signalPath('admin.handover-complete'))) {
    log('handover-stage-resumed', { reservationIds: targets.map((target) => target.reservationId), reason: 'handover completion marker exists' })
  } else {
    await waitForEachTarget(page, handoverSelector, '待交接队列', targets)
    await screenshot(page, 'admin-handovers-before.png')
    const handoverImage = Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/pZ8AAAAASUVORK5CYII=',
      'base64',
    )

    for (const target of targets) {
      const deviceName = target.deviceName
      const card = reservationCard(page, handoverSelector, target.reservationId)
      await card.getByRole('button', { name: '核对并完成交接', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: '完成设备交接' })
      await expect(dialog).toBeVisible()
      await expect(dialog.getByText(deviceName, { exact: false })).toBeVisible()
      await expect(dialog.getByText('电源线', { exact: true })).toBeVisible()
      await dialog.locator('input[type="file"]').setInputFiles({
        name: 'handover-evidence.png',
        mimeType: 'image/png',
        buffer: handoverImage,
      })
      await expect(dialog.getByText('1 张已选择')).toBeVisible()
      await dialog.getByText('状态正常', { exact: true }).click()
      await expect(dialog.locator('.el-select__selected-item:not(.el-select__input-wrapper)')).toHaveText('正常')
      await dialog.getByRole('button', { name: '确认', exact: true }).click()
      await expect(dialog).toBeHidden({ timeout: 30_000 })
      await expect(card).toHaveCount(0, { timeout: 20_000 })
      log('handover-completed', { reservationId: target.reservationId, deviceName, condition: 'NORMAL', accessory: '电源线=NORMAL', evidenceAttached: true })
    }
    await screenshot(page, 'admin-handovers-after.png')
    writeSignal('admin.handover-complete', { deviceNames })
    log('handover-stage-complete', { deviceNames })
  }

  await waitForAnySignal(['acceptance.go', 'return.go'])
  await page.reload({ waitUntil: 'networkidle' })
  await activateReturnPendingTab(page)
  await waitForEachTarget(page, handoverSelector, '待验收队列', targets)
  await screenshot(page, 'admin-return-queue.png')
  log('return-queue-confirmed', { deviceNames })

  for (const target of targets) {
    const deviceName = target.deviceName
    const card = reservationCard(page, handoverSelector, target.reservationId)
    expect(await card.getByRole('link', { name: '查看照片', exact: true }).count()).toBeGreaterThan(0)
    await card.getByRole('button', { name: '核对并确认验收', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '确认归还验收' })
    await expect(dialog).toBeVisible()
    expect(await dialog.getByRole('link', { name: '打开照片', exact: true }).count()).toBeGreaterThan(0)
    await dialog.getByText('状态正常', { exact: true }).click()
    await expect(dialog.locator('.el-select__selected-item:not(.el-select__input-wrapper)')).toHaveText('正常')
    await dialog.getByRole('button', { name: '确认', exact: true }).click()
    await expect(dialog).toBeHidden({ timeout: 30_000 })
    await expect(card).toHaveCount(0, { timeout: 20_000 })
    log('return-accepted', { reservationId: target.reservationId, deviceName, condition: 'NORMAL', accessory: '电源线=NORMAL', evidenceLinkPresent: true })
  }
  await screenshot(page, 'admin-return-accepted.png')
  writeSignal('admin.return-acceptance-complete', { deviceNames })
  log('return-acceptance-complete', { deviceNames })

  await waitForSignal('final-check.go')
  await page.goto(`${baseURL}/handovers`, { waitUntil: 'networkidle' })
  await page.getByRole('radio', { name: '待交接' }).click()
  for (const target of targets) {
    await expect(reservationCard(page, handoverSelector, target.reservationId)).toHaveCount(0)
  }
  await page.getByRole('radio', { name: '待验收' }).click()
  for (const target of targets) {
    await expect(reservationCard(page, handoverSelector, target.reservationId)).toHaveCount(0)
  }
  await screenshot(page, 'admin-final-check.png')

  if (pageErrors.length || failedResponses.length) {
    throw new Error(`Browser/API errors: ${JSON.stringify({ pageErrors, failedResponses })}`)
  }
  writeSignal('admin.final-check-complete', { targets, pageErrors: 0, failedResponses: 0 })
  log('final-check-complete', { targets, pageErrors: 0, failedResponses: 0 })
  }
} catch (error) {
  await screenshot(page, 'admin-failure.png').catch(() => {})
  log('failed', { message: error instanceof Error ? error.message : String(error), pageErrors, failedResponses })
  throw error
} finally {
  await context.close()
  await browser.close()
}
