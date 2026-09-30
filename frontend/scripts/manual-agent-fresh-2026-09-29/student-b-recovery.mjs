import { chromium } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import readline from 'node:readline/promises'
import { stdin as input, stdout as output } from 'node:process'

const baseUrl = 'http://127.0.0.1:5173'
const prefix = 'e2e-manual-agent-qa260929a'
const username = `${prefix}-user2`
const password = 'E2e-123456'
const reservationId = 71539
const deviceId = 11936
const deviceName = `${prefix}-device-2`
const purpose = `${prefix} 普通用户 B 同日预约联调`
const artifactsDir = path.resolve('.artifacts/manual-agent-fresh-2026-09-29/student-b')
const statePath = path.join(artifactsDir, 'recovery-detail.json')
await fs.mkdir(artifactsDir, { recursive: true })

const result = {
  account: username,
  reservationId,
  websocket: [],
  consoleErrors: [],
  pageErrors: [],
  failedRequests: [],
  httpErrors: [],
}
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN', timezoneId: 'Asia/Shanghai' })
const page = await context.newPage()
const rl = readline.createInterface({ input, output })
let offlinePhase = false
let wsOpenedResolve
const wsOpened = new Promise((resolve) => { wsOpenedResolve = resolve })
let reconnectResolve
const wsReconnected = new Promise((resolve) => { reconnectResolve = resolve })
let wsClosedResolve
const wsClosed = new Promise((resolve) => { wsClosedResolve = resolve })

page.on('websocket', (webSocket) => {
  const socket = { at: new Date().toISOString(), url: webSocket.url(), events: [{ at: new Date().toISOString(), event: 'opened' }] }
  result.websocket.push(socket)
  if (result.websocket.length === 1) wsOpenedResolve(socket)
  if (result.websocket.length > 1) reconnectResolve(socket)
  webSocket.on('close', () => {
    const closedAt = new Date().toISOString()
    socket.events.push({ at: closedAt, event: 'closed' })
    if (result.websocket.length === 1) wsClosedResolve({ at: closedAt, url: socket.url })
  })
  webSocket.on('socketerror', (error) => socket.events.push({ at: new Date().toISOString(), event: 'socketerror', error }))
})
page.on('console', (message) => {
  if (message.type() === 'error') result.consoleErrors.push({ at: new Date().toISOString(), text: message.text() })
})
page.on('pageerror', (error) => result.pageErrors.push({ at: new Date().toISOString(), message: error.message }))
page.on('requestfailed', (request) => result.failedRequests.push({
  at: new Date().toISOString(), method: request.method(), url: request.url(),
  failure: request.failure()?.errorText || 'unknown', whileOffline: offlinePhase,
}))
page.on('response', async (response) => {
  const url = new URL(response.url())
  const pathIsAuthRefresh = url.pathname.endsWith('/auth/refresh')
  const pathIsNotificationHistory = url.pathname.endsWith('/notifications/mine')
  if (pathIsAuthRefresh || pathIsNotificationHistory) {
    result.authAndNotificationResponses ||= []
    result.authAndNotificationResponses.push({
      at: new Date().toISOString(), method: response.request().method(), path: url.pathname,
      status: response.status(), query: url.search,
    })
  }
  if (response.status() < 400) return
  let body = ''
  try { body = (await response.text()).slice(0, 1000) } catch { body = '[unavailable]' }
  const expectedAuthProbe = response.status() === 401 && response.request().method() === 'GET' && url.pathname.endsWith('/auth/me')
  result.httpErrors.push({ at: new Date().toISOString(), status: response.status(), method: response.request().method(), path: url.pathname, expectedAuthProbe, body })
})

async function screenshot(name) {
  const file = path.join(artifactsDir, name)
  await page.screenshot({ path: file, fullPage: true, animations: 'disabled' })
  return file
}
async function save() {
  result.updatedAt = new Date().toISOString()
  await fs.writeFile(statePath, `${JSON.stringify(result, null, 2)}\n`, 'utf8')
}
async function waitFor(wsPromise, ms) {
  return Promise.race([wsPromise, new Promise((resolve) => setTimeout(() => resolve(null), ms))])
}

try {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded' })
  await page.getByPlaceholder('请输入用户名').fill(username)
  await page.getByPlaceholder('请输入密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL((url) => !url.pathname.endsWith('/login'), { timeout: 18000 })
  await page.getByRole('heading').first().waitFor({ state: 'visible', timeout: 15000 })
  result.login = { at: new Date().toISOString(), url: page.url() }
  const firstSocket = await waitFor(wsOpened, 12000)
  result.initialSocketOpened = Boolean(firstSocket)
  result.onlineBeforeOffline = await page.evaluate(() => navigator.onLine)
  await screenshot('websocket-connected.png')

  offlinePhase = true
  await context.setOffline(true)
  result.offlineStartedAt = new Date().toISOString()
  result.onlineWhileOffline = await page.evaluate(() => navigator.onLine)
  result.offlineSocketClose = firstSocket ? await waitFor(wsClosed, 10000) : null
  result.socketCloseObservedByRecord = Boolean(result.offlineSocketClose)
  result.offlinePhaseObserved = Boolean(result.onlineWhileOffline === false && result.socketCloseObservedByRecord)

  await context.setOffline(false)
  offlinePhase = false
  result.onlineRestoredAt = new Date().toISOString()
  result.onlineAfterRestore = await page.evaluate(() => navigator.onLine)
  const secondSocket = await waitFor(wsReconnected, 30000)
  result.reconnectObserved = Boolean(secondSocket)
  result.reconnectSocket = secondSocket || null
  result.websocketConnectionCount = result.websocket.length
  await screenshot('websocket-reconnected.png')
  await save()
  console.log(`WebSocket 初次连接=${result.initialSocketOpened}；离线=${result.onlineWhileOffline}；恢复在线=${result.onlineAfterRestore}；重连=${result.reconnectObserved}`)

  await page.goto(`${baseUrl}/reservations/${reservationId}`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('heading', { name: '预约详情' }).waitFor({ state: 'visible', timeout: 15000 })
  await page.getByText(deviceName, { exact: false }).first().waitFor({ state: 'visible', timeout: 15000 })
  const initialDetail = (await page.locator('.rsv-detail').innerText()).replace(/\s+/g, ' ').trim()
  result.detailBeforeReturn = { at: new Date().toISOString(), text: initialDetail }
  await screenshot('reservation-detail-in-use.png')
  await page.locator('.rsv-detail__actions').getByRole('button', { name: '归还' }).click()
  const dialog = page.getByRole('dialog', { name: '提交归还' })
  await dialog.waitFor({ state: 'visible', timeout: 5000 })
  await dialog.getByText('设备状态正常', { exact: true }).click()
  await page.getByPlaceholder('补充验收备注（可选）').fill(`${prefix} 正常归还；已上传 PNG 页面证据。`)
  const evidencePath = await screenshot('return-evidence.png')
  await page.locator('.rsv-detail__return-photos input[type="file"]').setInputFiles(evidencePath)
  await page.getByText('1 张已选择', { exact: true }).waitFor({ state: 'visible', timeout: 5000 })
  await screenshot('detail-return-form-with-png.png')
  await dialog.getByRole('button', { name: '确认归还' }).click()
  await page.getByText('已提交归还，等待负责人验收', { exact: true }).waitFor({ state: 'visible', timeout: 15000 })
  await page.waitForTimeout(700)
  result.returnSubmission = {
    at: new Date().toISOString(), condition: 'NORMAL', evidence: path.basename(evidencePath),
    detailTextAfterSubmit: (await page.locator('.rsv-detail').innerText()).replace(/\s+/g, ' ').trim(),
  }
  await screenshot('detail-return-submitted.png')
  await save()
  console.log(`预约详情页已提交正常归还；PNG=${path.basename(evidencePath)}。等待负责人验收后输入 verify-completed。`)

  while (true) {
    const command = (await rl.question('命令 (verify-completed / keep / close)> ')).trim().toLowerCase()
    if (command === 'close') break
    if (command === 'verify-completed') {
      await page.reload({ waitUntil: 'domcontentloaded' })
      await page.getByRole('heading', { name: '预约详情' }).waitFor({ state: 'visible', timeout: 15000 })
      await page.waitForTimeout(400)
      const detailText = (await page.locator('.rsv-detail').innerText()).replace(/\s+/g, ' ').trim()
      result.finalVerification = { at: new Date().toISOString(), statusText: detailText, completed: /已完成|COMPLETED/.test(detailText) }
      await screenshot('detail-final-status.png')
      await save()
      console.log(`预约详情最终状态含 COMPLETED/已完成=${result.finalVerification.completed}`)
      if (result.finalVerification.completed) break
    }
  }
} catch (error) {
  result.fatalError = { at: new Date().toISOString(), message: error?.stack || String(error) }
  await screenshot('recovery-failure-current-page.png').catch(() => undefined)
  await save()
  console.error(error)
  await rl.question('runner error saved; press enter to leave browser open> ')
}

await save()
console.log(`Recovery evidence: ${statePath}`)
await rl.question('Keep this recovery context open? press enter to finish only after root confirms> ')
rl.close()
await context.close()
await browser.close()
