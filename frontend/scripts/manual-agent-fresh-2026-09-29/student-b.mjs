import { chromium } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import readline from 'node:readline/promises'
import { stdin as input, stdout as output } from 'node:process'

const baseUrl = 'http://127.0.0.1:5173'
const prefix = 'e2e-manual-agent-qa260929a'
const username = `${prefix}-user2`
const password = 'E2e-123456'
const deviceName = `${prefix}-device`
const backupDeviceName = `${prefix}-device-2`
const reservationDate = '2026-09-29'
const sharedDeviceId = 11935
const backupDeviceId = 11936
const purpose = `${prefix} 普通用户 B 同日预约联调`
const artifactsDir = path.resolve('.artifacts/manual-agent-fresh-2026-09-29/student-b')
const statePath = path.join(artifactsDir, 'observations.json')
let offlinePhase = false

await fs.mkdir(artifactsDir, { recursive: true })

const observations = {
  task: 'fresh manual Vue page journey: student B',
  startedAt: new Date().toISOString(),
  account: username,
  prefix,
  requestedDate: reservationDate,
  deviceIds: { shared: sharedDeviceId, backup: backupDeviceId },
  sharedDeviceAttempt: null,
  successfulReservation: null,
  formAndMinePage: {},
  notificationBaseline: [],
  notificationRecovery: null,
  websocket: [],
  consoleErrors: [],
  pageErrors: [],
  failedRequests: [],
  httpErrors: [],
  actions: [],
}

async function saveState() {
  observations.updatedAt = new Date().toISOString()
  await fs.writeFile(statePath, `${JSON.stringify(observations, null, 2)}\n`, 'utf8')
}

function pause(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function commandPrompt(rl, prompt) {
  console.log(`\n${prompt}`)
  return (await rl.question('命令> ')).trim().toLowerCase()
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  locale: 'zh-CN',
  timezoneId: 'Asia/Shanghai',
})
const page = await context.newPage()
const rl = readline.createInterface({ input, output })

page.on('console', (message) => {
  if (message.type() === 'error') {
    observations.consoleErrors.push({ at: new Date().toISOString(), text: message.text() })
  }
})
page.on('pageerror', (error) => {
  observations.pageErrors.push({ at: new Date().toISOString(), message: error.message })
})
page.on('requestfailed', (request) => {
  observations.failedRequests.push({
    at: new Date().toISOString(),
    method: request.method(),
    url: request.url(),
    failure: request.failure()?.errorText || 'unknown',
    whileOffline: offlinePhase,
  })
})
page.on('response', async (response) => {
  if (response.status() < 400) return
  const request = response.request()
  const url = new URL(response.url())
  let responseText = ''
  try {
    responseText = (await response.text()).slice(0, 1200)
  } catch {
    responseText = '[response body unavailable]'
  }
  const expectedReservationConflict =
    response.status() === 409 && request.method() === 'POST' && url.pathname.endsWith('/reservations')
  const expectedUnauthenticatedProbe =
    response.status() === 401 && request.method() === 'GET' && url.pathname.endsWith('/auth/me')
  observations.httpErrors.push({
    at: new Date().toISOString(),
    status: response.status(),
    method: request.method(),
    path: url.pathname,
    expectedReservationConflict,
    expectedUnauthenticatedProbe,
    classification: expectedReservationConflict
      ? 'expected_reservation_conflict'
      : expectedUnauthenticatedProbe
        ? 'expected_bootstrap_auth_probe'
        : 'unexpected_http_error',
    responseText,
  })
})
context.on('websocket', (webSocket) => {
  const record = { at: new Date().toISOString(), url: webSocket.url(), events: ['opened'] }
  observations.websocket.push(record)
  webSocket.on('close', () => record.events.push('closed'))
  webSocket.on('socketerror', (error) => record.events.push(`socketerror:${error}`))
})

async function screenshot(name, options = {}) {
  const file = path.join(artifactsDir, name)
  await page.screenshot({ path: file, fullPage: true, animations: 'disabled', ...options })
  return file
}

async function waitForText(text, timeout = 12000) {
  await page.getByText(text, { exact: false }).first().waitFor({ state: 'visible', timeout })
}

async function readMineRecord(deviceId, expectedDeviceName) {
  await page.goto(`${baseUrl}/reservations/mine`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('heading', { name: '我的预约' }).waitFor({ state: 'visible', timeout: 15000 })
  await page.locator('.mine__cell').first().waitFor({ state: 'visible', timeout: 15000 })
  const cells = await page.locator('.mine__cell').all()
  const records = []
  for (const cell of cells) {
    const text = (await cell.innerText()).replace(/\s+/g, ' ').trim()
    records.push(text)
    if (text.includes(`#${deviceId}`) || text.includes(expectedDeviceName)) {
      const idText = await cell.locator('.mine__card-id').innerText()
      const statusText = await cell.locator('.el-tag').first().innerText()
      return { id: Number(idText.replace('#', '').trim()), statusText: statusText.trim(), text, records }
    }
  }
  return { id: null, statusText: null, text: null, records }
}

async function prepareForm(deviceId) {
  await page.goto(
    `${baseUrl}/reservations/create?deviceId=${deviceId}&startDate=${reservationDate}&endDate=${reservationDate}`,
    { waitUntil: 'domcontentloaded' },
  )
  await page.getByRole('heading', { name: deviceId === sharedDeviceId ? deviceName : backupDeviceName, exact: true })
    .waitFor({ state: 'visible', timeout: 20000 })
  const purposeBox = page.getByPlaceholder('例如：完成材料拉伸实验并采集三组数据')
  await purposeBox.fill(purpose)
  await page.locator('.preflight-card').waitFor({ state: 'visible', timeout: 15000 })
  await page.waitForFunction(() => {
    const card = document.querySelector('.preflight-card')
    return Boolean(card && !card.classList.contains('is-loading'))
  }, null, { timeout: 15000 }).catch(() => undefined)
  await pause(700)
  const preflightText = (await page.locator('.preflight-card').innerText()).replace(/\s+/g, ' ').trim()
  const summaryText = (await page.locator('.summary-card').innerText()).replace(/\s+/g, ' ').trim()
  const submit = page.getByRole('button', { name: '提交预约' })
  const submitDisabled = await submit.isDisabled()
  return { preflightText, summaryText, submitDisabled }
}

async function tryBooking(deviceId) {
  const form = await prepareForm(deviceId)
  const formShot = await screenshot(deviceId === sharedDeviceId ? 'shared-device-form.png' : 'backup-device-form.png')
  const result = { deviceId, deviceName: deviceId === sharedDeviceId ? deviceName : backupDeviceName, ...form, screenshot: path.basename(formShot) }
  if (form.preflightText.includes('冲突')) {
    result.outcome = 'page_preflight_conflict'
    result.expectedConflictMessage = form.preflightText
    await saveState()
    return result
  }

  if (form.submitDisabled) {
    result.outcome = 'blocked_without_explicit_conflict'
    return result
  }

  const createResponsePromise = page.waitForResponse((response) => {
    const request = response.request()
    const url = new URL(response.url())
    return request.method() === 'POST' && url.pathname.endsWith('/reservations')
  }, { timeout: 18000 }).catch(() => null)
  await page.getByRole('button', { name: '提交预约' }).click()
  const response = await createResponsePromise
  if (response) {
    result.createStatus = response.status()
    if (response.status() === 409) result.outcome = 'expected_http_409_conflict'
    else if (response.ok()) result.outcome = 'created'
    else result.outcome = 'unexpected_create_status'
  } else {
    result.outcome = 'create_request_not_observed'
  }
  await page.getByRole('heading', { name: '我的预约' }).waitFor({ state: 'visible', timeout: 20000 }).catch(() => undefined)
  await pause(800)
  if (page.url().includes('/reservations/mine')) {
    const mine = await readMineRecord(deviceId, result.deviceName)
    result.reservationId = mine.id
    result.mineStatus = mine.statusText
    result.mineText = mine.text
    result.mineRecords = mine.records
  } else {
    result.pageMessage = await page.locator('body').innerText().catch(() => '')
  }
  await saveState()
  return result
}

try {
  console.log(`启动独立 Chromium context，账号 ${username}`)
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded' })
  await page.getByPlaceholder('请输入用户名').fill(username)
  await page.getByPlaceholder('请输入密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL((url) => !url.pathname.endsWith('/login'), { timeout: 18000 })
  await page.getByRole('heading').first().waitFor({ state: 'visible', timeout: 15000 })
  observations.actions.push({ action: 'login', result: 'success', at: new Date().toISOString() })
  await screenshot('logged-in.png')

  console.log('尝试学院内共享设备 #11935。')
  const shared = await tryBooking(sharedDeviceId)
  observations.sharedDeviceAttempt = shared

  let successful = shared.outcome === 'created' && shared.reservationId
    ? { ...shared }
    : null

  if (!successful) {
    const expectedPageConflict = shared.outcome === 'page_preflight_conflict'
    const expectedHttpConflict = shared.outcome === 'expected_http_409_conflict'
    if (!expectedPageConflict && !expectedHttpConflict) {
      observations.actions.push({
        action: 'shared_device_attempt',
        result: 'unexpected_failure_before_backup',
        detail: shared,
        at: new Date().toISOString(),
      })
      await saveState()
      console.log('共享设备尝试不是可解释的冲突；已保存页面与网络信息，保留表单供分析。')
      await commandPrompt(rl, '检查后输入 retry-backup 重试备用设备，或 stop 暂停')
    }
    if (shared.outcome === 'expected_http_409_conflict') {
      await page.getByText(/冲突|已被预约|不可用/).first().waitFor({ state: 'visible', timeout: 5000 }).catch(() => undefined)
      await screenshot('shared-device-409.png')
    }
    console.log(`共享设备结果：${shared.outcome}；记录为预期冲突后转用 #11936。`)
    const backup = await tryBooking(backupDeviceId)
    if (backup.outcome !== 'created' || !backup.reservationId) {
      observations.actions.push({ action: 'backup_device_attempt', result: 'failed', detail: backup, at: new Date().toISOString() })
      await saveState()
      console.log('备用设备未能建立并从“我的预约”核验预约 ID。')
      await commandPrompt(rl, '检查备用预约失败原因后输入 retry-backup，或 stop 暂停')
    } else {
      successful = backup
      observations.backupDeviceAttempt = backup
    }
  }

  observations.successfulReservation = {
    id: successful.reservationId,
    deviceId: successful.deviceId,
    deviceName: successful.deviceName,
    date: reservationDate,
    status: successful.mineStatus,
    purpose,
  }
  observations.formAndMinePage = {
    dateFieldValue: reservationDate,
    purposeFieldValue: purpose,
    categoryControlVisibleByFieldLabel: await page.locator('.reserve-form .el-form-item').filter({ hasText: '用途类别' }).isVisible().catch(() => false),
    mineRecordVisible: Boolean(successful.mineText),
    mineRecordText: successful.mineText,
    successfulDevice: successful.deviceName,
    successfulReservationId: successful.reservationId,
  }
  observations.actions.push({ action: 'create_reservation', result: 'success', at: new Date().toISOString() })
  await screenshot('reservation-created.png')

  await page.goto(`${baseUrl}/notifications`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('heading', { name: '通知中心' }).waitFor({ state: 'visible', timeout: 15000 })
  await pause(900)
  observations.notificationBaseline = await page.locator('.notif-row').allInnerTexts().catch(() => [])
  await screenshot('notifications-before-offline.png')

  const socketCountBeforeOffline = observations.websocket.length
  offlinePhase = true
  await context.setOffline(true)
  observations.offlineStartedAt = new Date().toISOString()
  observations.onlineValueWhileOffline = await page.evaluate(() => navigator.onLine)
  await screenshot('offline-wait.png')
  await saveState()

  console.log(`预约 #${successful.reservationId} 已从“我的预约”页面核验。共享设备结果：${shared.outcome}。`)
  console.log(`浏览器已离线，session/context 保留；当前 WebSocket 记录数 ${socketCountBeforeOffline}。`)
  console.log(`预约：#${successful.reservationId} · ${successful.deviceName} · ${reservationDate}`)
  console.log('等待 root 通知审批和交接完成后输入 resume。')

  while (true) {
    const command = await commandPrompt(rl, '审批和交接完成后输入 resume；或输入 stop')
    if (command === 'stop') break
    if (command !== 'resume') continue

    await context.setOffline(false)
    offlinePhase = false
    observations.onlineRestoredAt = new Date().toISOString()
    observations.onlineValueAfterRestore = await page.evaluate(() => navigator.onLine)
    const reconnectDeadline = Date.now() + 35000
    while (Date.now() < reconnectDeadline && observations.websocket.length <= socketCountBeforeOffline) {
      await pause(500)
    }
    await page.goto(`${baseUrl}/notifications`, { waitUntil: 'domcontentloaded' })
    if (page.url().includes('/login')) {
      observations.notificationRecovery = { result: 'session_redirected_to_login', at: new Date().toISOString() }
      await screenshot('notifications-session-redirect.png')
      await saveState()
      console.log('恢复在线后被重定向登录页；保留现场等待分析。')
      continue
    }
    await page.getByRole('heading', { name: '通知中心' }).waitFor({ state: 'visible', timeout: 15000 })
    await page.locator('.notif-row, .notif-list__empty').first().waitFor({ state: 'visible', timeout: 15000 })
    await pause(800)
    const recoveredRows = await page.locator('.notif-row').allInnerTexts().catch(() => [])
    const normalizedRows = recoveredRows.map((row) => row.replace(/\s+/g, ' ').trim())
    const freshRows = normalizedRows.filter((row) => !observations.notificationBaseline.some((old) => old.replace(/\s+/g, ' ').trim() === row))
    const reservationRelatedRows = normalizedRows.filter((row) =>
      row.includes(`#${successful.reservationId}`) || /审批|通过|交接|领用|使用中/.test(row),
    )
    observations.notificationRecovery = {
      result: 'history_loaded_after_reconnect',
      at: new Date().toISOString(),
      baselineCount: observations.notificationBaseline.length,
      recoveredCount: normalizedRows.length,
      freshRows,
      reservationRelatedRows,
      allRows: normalizedRows,
      websocketReconnectObserved: observations.websocket.length > socketCountBeforeOffline,
      websocketRecordCount: observations.websocket.length,
      reservationId: successful.reservationId,
    }
    observations.actions.push({ action: 'restore_online_and_verify_notification_history', result: 'history_loaded_after_reconnect', at: new Date().toISOString() })
    await screenshot('notifications-after-offline.png')
    await saveState()
    console.log(`恢复在线；WebSocket 重连记录 ${observations.websocket.length} 个，离线前后新增通知行 ${freshRows.length} 条。`)
    console.log(`审批/交接相关通知：${JSON.stringify(reservationRelatedRows)}`)
    console.log('通知历史检查完成。等待 root 指令后输入 return 提交正常归还。')
    break
  }

  while (true) {
    const command = await commandPrompt(rl, 'root 通知提交归还后输入 return；收到管理员验收完成通知后输入 verify-completed；或 stop')
    if (command === 'stop') break
    if (command === 'return') {
      await page.goto(`${baseUrl}/reservations/mine`, { waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: '我的预约' }).waitFor({ state: 'visible', timeout: 15000 })
      await page.locator('.mine__cell').first().waitFor({ state: 'visible', timeout: 15000 })
      const cells = await page.locator('.mine__cell').all()
      let targetCell = null
      for (const cell of cells) {
        const text = await cell.innerText()
        if (text.includes(`#${successful.reservationId}`) || text.includes(purpose)) {
          targetCell = cell
          break
        }
      }
      if (!targetCell) throw new Error(`预约 #${successful.reservationId} 不在“我的预约”首屏列表中`)
      const cardStatus = await targetCell.locator('.el-tag').first().innerText()
      if (!cardStatus.includes('使用中')) {
        observations.actions.push({ action: 'pre_return_status', result: 'unexpected_status', status: cardStatus.trim(), at: new Date().toISOString() })
        await screenshot('return-status-not-in-use.png')
        await saveState()
        console.log(`提交归还前状态是“${cardStatus.trim()}”，等待 root 处理或状态更新。`)
        continue
      }
      await targetCell.getByRole('button', { name: '归还' }).click()
      await page.getByRole('dialog', { name: '提交归还' }).waitFor({ state: 'visible', timeout: 5000 })
      await page.getByPlaceholder('补充验收备注（可选）').fill(`${prefix} 正常归还；PNG 页面证据已附。`)
      const evidencePath = await screenshot('return-evidence.png')
      await page.locator('.mine__return-photos input[type="file"]').setInputFiles(evidencePath)
      await waitForText('1 张已选择', 5000)
      await screenshot('return-form-with-png.png')
      await page.getByRole('button', { name: '确认归还' }).click()
      await waitForText('已提交归还，等待负责人验收', 12000)
      await pause(700)
      const refreshed = await readMineRecord(successful.deviceId, successful.deviceName)
      observations.returnSubmission = {
        at: new Date().toISOString(),
        reservationId: successful.reservationId,
        condition: 'NORMAL',
        uploadedPng: path.basename(evidencePath),
        statusAfterSubmit: refreshed.statusText,
        textAfterSubmit: refreshed.text,
        expectedInterimHandoverTag: refreshed.text?.includes('待负责人验收') || false,
      }
      observations.actions.push({ action: 'submit_normal_return', result: 'success', at: observations.returnSubmission.at })
      await screenshot('return-submitted.png')
      await saveState()
      console.log(`已提交正常归还并上传 ${path.basename(evidencePath)}。当前预约状态展示：${refreshed.statusText}；页面记录：${refreshed.text}`)
      console.log('如果 root 随后完成负责人验收，输入 verify-completed 核验 COMPLETED。')
    }
    if (command === 'verify-completed') {
      const mine = await readMineRecord(successful.deviceId, successful.deviceName)
      const completed = /已完成|COMPLETED/.test(mine.statusText || '')
      observations.finalVerification = {
        at: new Date().toISOString(),
        reservationId: successful.reservationId,
        statusText: mine.statusText,
        completed,
        recordText: mine.text,
      }
      await screenshot('final-status.png')
      await saveState()
      console.log(`最终状态页面核验：${mine.statusText}；COMPLETED=${completed}`)
      if (completed) break
    }
  }

  observations.finishedAt = new Date().toISOString()
  await saveState()
  console.log(`观察记录：${statePath}`)
  await commandPrompt(rl, '当前联调已暂停。保持进程及会话打开可输入 keep；root 完成全部核验后输入 close')
} catch (error) {
  observations.fatalError = { at: new Date().toISOString(), message: error?.stack || String(error) }
  await screenshot('failure-current-page.png').catch(() => undefined)
  await saveState()
  console.error(error)
  await commandPrompt(rl, '脚本遇到异常并保存现场，分析/通知 root 后输入 keep 或 close')
} finally {
  if (process.argv.includes('--close')) {
    rl.close()
    await context.close()
    await browser.close()
  }
}

// Keep the isolated browser session alive until the parent explicitly closes it.
while (true) {
  const command = await commandPrompt(rl, 'session 仍保持打开；输入 keep 等待，输入 close 结束')
  if (command === 'close') break
}
rl.close()
await context.close()
await browser.close()
