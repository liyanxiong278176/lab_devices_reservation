import { chromium } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import readline from 'node:readline'

const baseUrl = 'http://127.0.0.1:5173'
const prefix = 'e2e-manual-agent-qa260929a'
const username = `${prefix}-user`
const password = 'E2e-123456'
const primaryDevice = { id: 11935, name: `${prefix}-device` }
const backupDevice = { id: 11936, name: `${prefix}-device-2` }
const reservationDate = '2026-09-29'
const artifactDir = path.resolve('.artifacts/manual-agent-fresh-2026-09-29/student-a')
const runnerDir = path.dirname(new URL(import.meta.url).pathname)
const evidence = {
  task: 'student-a fresh real-page reservation and return journey',
  startedAt: new Date().toISOString(),
  baseUrl,
  prefix,
  username,
  college: { id: 656, name: `E2E 测试学院 ${prefix}` },
  reservationDate,
  primaryDevice,
  backupDevice,
  steps: [],
  consoleErrors: [],
  pageErrors: [],
  requestFailures: [],
  httpErrors: [],
}

await fs.mkdir(artifactDir, { recursive: true })

function log(message, detail) {
  const suffix = detail === undefined ? '' : ` ${JSON.stringify(detail)}`
  process.stdout.write(`[student-a] ${message}${suffix}\n`)
}

async function saveEvidence() {
  evidence.updatedAt = new Date().toISOString()
  await fs.writeFile(path.join(artifactDir, 'run.json'), `${JSON.stringify(evidence, null, 2)}\n`, 'utf8')
}

async function screenshot(page, name) {
  const file = path.join(artifactDir, name)
  await page.screenshot({ path: file, fullPage: true, animations: 'disabled' })
  return file
}

async function addStep(page, name, details = {}) {
  const current = {
    name,
    at: new Date().toISOString(),
    url: page.url(),
    title: await page.title().catch(() => ''),
    text: (await page.locator('body').innerText().catch(() => '')).slice(0, 12000),
    toasts: await page.locator('.el-message').allInnerTexts().catch(() => []),
    ...details,
  }
  evidence.steps.push(current)
  await saveEvidence()
  log(name, { url: current.url, ...details })
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({
  locale: 'zh-CN',
  timezoneId: 'Asia/Shanghai',
  viewport: { width: 1440, height: 1000 },
  acceptDownloads: true,
})
const page = await context.newPage()

page.on('console', (message) => {
  if (message.type() === 'error') evidence.consoleErrors.push({ at: new Date().toISOString(), text: message.text() })
})
page.on('pageerror', (error) => {
  evidence.pageErrors.push({ at: new Date().toISOString(), text: error.stack || error.message })
})
page.on('requestfailed', (request) => {
  evidence.requestFailures.push({
    at: new Date().toISOString(),
    method: request.method(),
    url: request.url(),
    error: request.failure()?.errorText || 'request failed',
  })
})
page.on('response', async (response) => {
  if (response.status() < 400) return
  const request = response.request()
  let body = ''
  if (response.url().includes('/api/')) {
    try {
      body = (await response.text()).slice(0, 600)
    } catch {
      body = ''
    }
  }
  const pathname = new URL(response.url()).pathname
  const isAnonymousMe = response.status() === 401 && pathname.endsWith('/auth/me')
  const isExpectedConflict = response.status() === 409 && pathname.endsWith('/reservations')
  evidence.httpErrors.push({
    at: new Date().toISOString(),
    method: request.method(),
    url: response.url(),
    status: response.status(),
    expected: isAnonymousMe || isExpectedConflict,
    reason: isAnonymousMe ? 'anonymous auth probe before login' : isExpectedConflict ? 'reservation conflict during shared-device attempt' : undefined,
    body,
  })
  await saveEvidence()
})

function cardForDevice(deviceName) {
  return page.locator('.mine__cell').filter({ hasText: deviceName })
}

async function getReservationId(deviceName) {
  const card = cardForDevice(deviceName).first()
  await card.waitFor({ state: 'visible', timeout: 15000 })
  const idText = await card.locator('.mine__card-id').innerText()
  const id = Number(idText.match(/\d+/)?.[0])
  if (!Number.isFinite(id)) throw new Error(`Could not parse reservation ID from ${idText}`)
  return { id, text: await card.innerText() }
}

async function goToMine() {
  await page.goto(`${baseUrl}/reservations/mine`, { waitUntil: 'domcontentloaded' })
  await page.locator('.mine__grid').waitFor({ state: 'visible', timeout: 20000 })
}

async function tryReservation(device, purposeSuffix) {
  const url = new URL('/reservations/create', baseUrl)
  url.searchParams.set('deviceId', String(device.id))
  url.searchParams.set('startDate', reservationDate)
  url.searchParams.set('endDate', reservationDate)
  await page.goto(url.toString(), { waitUntil: 'domcontentloaded' })
  await page.locator('.reserve-create-v2__device h2').filter({ hasText: device.name }).first().waitFor({ state: 'visible', timeout: 20000 })
  await page.locator('textarea[placeholder^="例如"]').fill(`完成当天实验设备使用并记录结果（${purposeSuffix}）。`)
  await page.locator('.preflight-card .preflight-summary').waitFor({ state: 'visible', timeout: 20000 })
  await page.waitForTimeout(400)
  const formScreenshot = await screenshot(page, `reservation-form-${device.id}.png`)
  const cardText = await page.locator('.preflight-card').innerText()
  const submitButton = page.getByRole('button', { name: '提交预约', exact: true })
  const isDisabled = await submitButton.isDisabled().catch(() => false)
  const conflict = /冲突/.test(cardText) && !/0 天冲突/.test(cardText)

  await addStep(page, `preflight-device-${device.id}`, {
    device,
    date: reservationDate,
    purpose: `完成当天实验设备使用并记录结果（${purposeSuffix}）。`,
    preflightText: cardText,
    submitDisabled: isDisabled,
    screenshot: formScreenshot,
  })

  if (conflict || isDisabled) {
    return { created: false, conflict: true, reason: cardText, screenshot: formScreenshot }
  }

  await submitButton.click()
  const mineUrl = `${baseUrl}/reservations/mine`
  await page.waitForURL((current) => current.pathname === '/reservations/mine', { timeout: 20000 }).catch(() => {})
  await page.locator('.mine__grid').waitFor({ state: 'visible', timeout: 20000 })
  const idResult = await getReservationId(device.name)
  const mineScreenshot = await screenshot(page, `my-reservation-${idResult.id}.png`)
  await addStep(page, `reservation-created-device-${device.id}`, {
    device,
    reservationId: idResult.id,
    reservationCardText: idResult.text,
    screenshot: mineScreenshot,
  })

  await page.goto(`${baseUrl}/notifications`, { waitUntil: 'domcontentloaded' })
  await page.locator('.notif-list').waitFor({ state: 'visible', timeout: 20000 })
  await page.waitForTimeout(700)
  const notificationScreenshot = await screenshot(page, `notifications-after-create-${idResult.id}.png`)
  const notificationText = await page.locator('.notif-list').innerText().catch(() => '')
  await addStep(page, `notifications-after-create-${device.id}`, {
    device,
    reservationId: idResult.id,
    notificationText,
    screenshot: notificationScreenshot,
  })

  await goToMine()
  await addStep(page, `mine-after-notifications-${device.id}`, { reservationId: idResult.id })
  return { created: true, reservationId: idResult.id, cardText: idResult.text, screenshot: mineScreenshot }
}

try {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded' })
  await page.locator('.login-card').waitFor({ state: 'visible', timeout: 20000 })
  await screenshot(page, 'login-page.png')
  const inputs = page.locator('.login-card .el-input__inner')
  await inputs.nth(0).fill(username)
  await inputs.nth(1).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL((current) => !['/login', '/register'].includes(current.pathname), { timeout: 20000 })
  await page.waitForTimeout(300)
  await addStep(page, 'logged-in', { screenshot: await screenshot(page, 'dashboard-after-login.png') })

  let result = await tryReservation(primaryDevice, '共享设备首次尝试')
  evidence.primaryAttempt = result
  if (!result.created) {
    await addStep(page, 'primary-device-conflict', {
      device: primaryDevice,
      conflictReason: result.reason,
      note: '共享设备冲突按任务要求保留；页面预检已阻止提交时未强行绕过表单。',
      screenshot: result.screenshot,
    })
    result = await tryReservation(backupDevice, '备用设备成功预约')
  }

  if (!result.created) {
    throw new Error(`Could not create a reservation for either assigned device; last result: ${JSON.stringify(result)}`)
  }
  evidence.createdReservation = result
  evidence.activeDevice = result === evidence.primaryAttempt ? primaryDevice : backupDevice
  await addStep(page, 'ready-for-admin-approval-and-handover', {
    activeDevice: evidence.activeDevice,
    reservationId: result.reservationId,
    instruction: '保持此浏览器 context 开启；待 root 通知后输入 RETURN。',
  })
  await saveEvidence()
  log('预约流程已完成，保持浏览器会话开启。等待 root 协作通知后输入 RETURN。', {
    reservationId: result.reservationId,
    device: evidence.activeDevice,
    primaryAttempt: evidence.primaryAttempt.created ? 'created' : 'conflict',
  })

  const input = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: false })
  for await (const line of input) {
    const command = line.trim().toUpperCase()
    if (command === 'RETURN') {
      await submitReturn()
    } else if (command === 'VERIFY') {
      await verifyCompleted()
    } else if (command === 'QUIT') {
      break
    } else if (command) {
      log('未知指令；可用 RETURN、VERIFY 或 QUIT。')
    }
  }
  input.close()
} catch (error) {
  evidence.fatalError = { at: new Date().toISOString(), text: error.stack || String(error) }
  await screenshot(page, 'failure-current-page.png').catch(() => {})
  await saveEvidence()
  log('runner failed', evidence.fatalError)
  process.exitCode = 1
} finally {
  if (process.exitCode) {
    await context.close().catch(() => {})
    await browser.close().catch(() => {})
  }
}

async function submitReturn() {
  await goToMine()
  const current = await getReservationId(evidence.activeDevice.name)
  const card = cardForDevice(evidence.activeDevice.name).first()
  await screenshot(page, `before-return-${current.id}.png`)
  const cardStatus = await card.innerText()
  if (!/使用中/.test(cardStatus) && !/IN_USE/.test(cardStatus)) {
    await addStep(page, 'return-blocked-status', {
      reservationId: current.id,
      cardText: cardStatus,
      note: '页面尚未显示使用中，已保留会话等待管理员交接完成。',
    })
    return
  }

  await card.getByRole('button', { name: '归还', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '提交归还' })
  await dialog.waitFor({ state: 'visible', timeout: 10000 })
  const evidencePng = path.join(artifactDir, `return-evidence-${current.id}.png`)
  await page.screenshot({ path: evidencePng, fullPage: true, animations: 'disabled' })
  await dialog.getByText('设备状态正常', { exact: true }).click()
  await dialog.locator('textarea').fill('同日归还；设备外观与功能检查正常，无损坏或缺失。')
  await dialog.locator('input[type="file"]').setInputFiles(evidencePng)
  await dialog.getByText(/1 张已选择/).waitFor({ state: 'visible', timeout: 5000 })
  await addStep(page, 'return-form-ready', {
    reservationId: current.id,
    condition: 'NORMAL',
    note: '同日归还；设备外观与功能检查正常，无损坏或缺失。',
    evidencePng,
    screenshot: await screenshot(page, `return-form-${current.id}.png`),
  })
  await dialog.getByRole('button', { name: '确认归还', exact: true }).click()
  await page.getByText('已提交归还，等待负责人验收', { exact: true }).waitFor({ state: 'visible', timeout: 20000 })
  await goToMine()
  const after = await getReservationId(evidence.activeDevice.name)
  await addStep(page, 'return-submitted', {
    reservationId: current.id,
    cardText: after.text,
    returnToast: '已提交归还，等待负责人验收',
    screenshot: await screenshot(page, `return-submitted-${current.id}.png`),
  })
  log('正常归还已从页面提交并收到成功 toast；等待管理员验收后输入 VERIFY。', { reservationId: current.id })
}

async function verifyCompleted() {
  await goToMine()
  const current = await getReservationId(evidence.activeDevice.name)
  const completed = /已完成|COMPLETED/.test(current.text)
  const step = {
    name: 'final-completed-status-check',
    at: new Date().toISOString(),
    url: page.url(),
    reservationId: current.id,
    cardText: current.text,
    completed,
    screenshot: await screenshot(page, `final-status-${current.id}.png`),
  }
  evidence.steps.push(step)
  await saveEvidence()
  log(completed ? '页面已确认预约完成。' : '页面尚未显示已完成状态。', {
    reservationId: current.id,
    cardText: current.text,
  })
}
