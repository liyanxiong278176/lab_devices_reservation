import { chromium } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'

const baseUrl = 'http://127.0.0.1:5173'
const prefix = 'e2e-manual-agent-qa260929a'
const username = `${prefix}-user2`
const password = 'E2e-123456'
const artifactsDir = path.resolve('.artifacts/manual-agent-fresh-2026-09-29/student-b')
const statePath = path.join(artifactsDir, 'websocket-strict.json')
await fs.mkdir(artifactsDir, { recursive: true })

const result = {
  scenario: 'same-page browser offline and API WebSocket reconnect observation',
  account: username,
  applicationWebSocketPath: '/api/v2/ws',
  sockets: [],
  consoleErrors: [],
  pageErrors: [],
  failedRequests: [],
}
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN', timezoneId: 'Asia/Shanghai' })
await context.addInitScript(() => {
  const nativeWebSocket = window.WebSocket
  const records = []
  const instances = []
  Object.defineProperty(window, '__qaApiWebSocketRecords', { value: records, configurable: false })
  Object.defineProperty(window, '__qaApiSocketInstances', { value: instances, configurable: false })
  window.WebSocket = new Proxy(nativeWebSocket, {
    construct(target, args) {
      const instance = Reflect.construct(target, args)
      let pathname = ''
      try { pathname = new URL(String(args[0]), window.location.href).pathname } catch { /* ignore malformed URL */ }
      if (pathname === '/api/v2/ws') {
        const record = { pathname, url: `${window.location.origin}/api/v2/ws`, createdAt: new Date().toISOString(), readyState: 'CONNECTING' }
        records.push(record)
        instances.push(instance)
        instance.addEventListener('open', () => {
          record.openedAt = new Date().toISOString()
          record.readyState = 'OPEN'
        })
        instance.addEventListener('close', (event) => {
          record.closedAt = new Date().toISOString()
          record.closeCode = event.code
          record.closeReason = event.reason
          record.wasClean = event.wasClean
          record.readyState = 'CLOSED'
        })
        instance.addEventListener('error', () => {
          record.errorAt = new Date().toISOString()
          record.readyState = 'ERROR'
        })
      }
      return instance
    },
  })
})
const page = await context.newPage()
let offline = false
let firstOpenResolve
const firstOpen = new Promise((resolve) => { firstOpenResolve = resolve })
let secondOpenResolve
const secondOpen = new Promise((resolve) => { secondOpenResolve = resolve })

page.on('websocket', (webSocket) => {
  let pathname = ''
  try { pathname = new URL(webSocket.url()).pathname } catch { return }
  if (pathname !== '/api/v2/ws') return
  const requestedAt = new Date().toISOString()
  const record = { pathname, requestedAt, events: [{ event: 'requested', at: requestedAt }] }
  result.sockets.push(record)
  if (result.sockets.length === 1) firstOpenResolve(record)
  if (result.sockets.length === 2) secondOpenResolve(record)
  webSocket.on('close', () => record.events.push({ event: 'close', at: new Date().toISOString() }))
  webSocket.on('socketerror', (error) => record.events.push({ event: 'socketerror', at: new Date().toISOString(), error }))
})
page.on('console', (message) => {
  if (message.type() === 'error') result.consoleErrors.push({ at: new Date().toISOString(), text: message.text() })
})
page.on('pageerror', (error) => result.pageErrors.push({ at: new Date().toISOString(), message: error.message }))
page.on('requestfailed', (request) => result.failedRequests.push({
  at: new Date().toISOString(), method: request.method(), url: request.url(),
  failure: request.failure()?.errorText || 'unknown', whileOffline: offline,
}))
page.on('response', (response) => {
  const url = new URL(response.url())
  if (url.pathname === '/api/v2/notifications/mine' && url.searchParams.get('onlyUnread') === 'true') {
    result.unreadRefreshResponses ||= []
    result.unreadRefreshResponses.push({ at: new Date().toISOString(), status: response.status(), method: response.request().method(), path: url.pathname, query: url.search })
  }
})

async function waitFor(promise, ms) {
  return Promise.race([promise, new Promise((resolve) => setTimeout(() => resolve(null), ms))])
}
async function save() {
  result.updatedAt = new Date().toISOString()
  await fs.writeFile(statePath, `${JSON.stringify(result, null, 2)}\n`, 'utf8')
}
async function screenshot(name) {
  await page.screenshot({ path: path.join(artifactsDir, name), fullPage: true, animations: 'disabled' })
}

try {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded' })
  await page.getByPlaceholder('请输入用户名').fill(username)
  await page.getByPlaceholder('请输入密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL((url) => !url.pathname.endsWith('/login'), { timeout: 18000 })
  await page.getByRole('heading').first().waitFor({ state: 'visible', timeout: 15000 })
  result.loginAt = new Date().toISOString()
  result.pageBeforeOffline = page.url()

  const first = await waitFor(firstOpen, 12000)
  result.initialApiSocketRequestObserved = Boolean(first)
  result.initialSocketRequest = first || null
  const initialOpened = await page.waitForFunction(() => window.__qaApiWebSocketRecords?.[0]?.openedAt || false, null, { timeout: 12000 }).then(() => true).catch(() => false)
  result.initialApiSocketOpened = initialOpened
  result.initialSocket = await page.evaluate(() => window.__qaApiWebSocketRecords?.[0] || null)
  result.onlineBeforeOffline = await page.evaluate(() => navigator.onLine)
  if (!first || !initialOpened) throw new Error('没有观察到初始 /api/v2/ws 握手成功，无法测试同连接断开/重连')
  await screenshot('websocket-strict-before-offline.png')

  offline = true
  await context.setOffline(true)
  result.offlineAt = new Date().toISOString()
  result.onlineDuringOffline = await page.evaluate(() => navigator.onLine)
  await screenshot('websocket-strict-offline.png')
  result.offlineCloseObserved = await page.waitForFunction(() => window.__qaApiWebSocketRecords?.[0]?.closedAt || false, null, { timeout: 10000 }).then(() => true).catch(() => false)
  result.initialSocketAfterOffline = await page.evaluate(() => window.__qaApiWebSocketRecords?.[0] || null)

  if (result.offlineCloseObserved) {
    result.closeMechanism = 'browser_context_offline'
  } else {
    result.closeMechanism = 'controlled_native_websocket_close_after_offline_did_not_close'
    result.note = 'BrowserContext.setOffline(true) left the established socket open; observed offline separately and used the captured native app socket close() in the same SPA page.'
    await context.setOffline(false)
    offline = false
    result.onlineRestoredAt = new Date().toISOString()
    result.onlineAfterRestore = await page.evaluate(() => navigator.onLine)
    result.manualCloseRequestedAt = new Date().toISOString()
    await page.evaluate(() => {
      const socket = window.__qaApiWebSocketRecords?.[0]
      if (!socket) throw new Error('missing tracked /api/v2/ws record')
      const openSocket = (window.__qaApiSocketInstances || []).find((candidate) =>
        new URL(candidate.url).pathname === '/api/v2/ws' && candidate.readyState === WebSocket.OPEN,
      )
      if (!openSocket) throw new Error('no open native /api/v2/ws instance available for controlled close')
      openSocket.close(1000, 'manual offline QA')
    })
    result.controlledCloseObserved = await page.waitForFunction(() => window.__qaApiWebSocketRecords?.[0]?.closedAt || false, null, { timeout: 8000 }).then(() => true).catch(() => false)
  }

  result.closeAt = await page.evaluate(() => window.__qaApiWebSocketRecords?.[0]?.closedAt || null)
  const unreadRefresh = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return url.pathname === '/api/v2/notifications/mine' && url.searchParams.get('onlyUnread') === 'true' && response.status() === 200
  }, { timeout: 20000 }).catch(() => null)
  if (result.closeMechanism === 'browser_context_offline') {
    await context.setOffline(false)
    offline = false
    result.onlineRestoredAt = new Date().toISOString()
    result.onlineAfterRestore = await page.evaluate(() => navigator.onLine)
  }
  result.minimumReconnectDelayWaitStartedAt = new Date().toISOString()
  result.secondApiSocketRequest = await waitFor(secondOpen, 15000)
  result.secondApiSocketOpened = await page.waitForFunction(() => window.__qaApiWebSocketRecords?.[1]?.openedAt || false, null, { timeout: 12000 }).then(() => true).catch(() => false)
  result.secondSocket = await page.evaluate(() => window.__qaApiWebSocketRecords?.[1] || null)
  result.reconnectElapsedMs = result.secondSocket?.openedAt && result.closeAt
    ? new Date(result.secondSocket.openedAt).getTime() - new Date(result.closeAt).getTime()
    : null
  result.reconnectObserved = Boolean(result.closeAt && result.secondApiSocketOpened && result.onlineAfterRestore === true)
  result.unreadRefreshAfterReconnect = await unreadRefresh
  result.minimumFiveSecondRetryConfirmed = result.reconnectElapsedMs !== null && result.reconnectElapsedMs >= 5000
  result.result = result.reconnectObserved && result.minimumFiveSecondRetryConfirmed && result.unreadRefreshAfterReconnect?.status() === 200
    ? 'same_page_close_and_reconnect_observed'
    : 'unproven_automatic_reconnect'
  result.finalPageUrl = page.url()
  await screenshot('websocket-strict-after-restore.png')
} catch (error) {
  result.result = 'diagnostic_error'
  result.error = error?.stack || String(error)
  await screenshot('websocket-strict-failure.png').catch(() => undefined)
} finally {
  await save()
  console.log(JSON.stringify(result, null, 2))
  await context.close()
  await browser.close()
}
