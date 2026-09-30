import { chromium, expect } from '@playwright/test'
import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const baseURL = process.env.PREVIEW_URL || 'http://127.0.0.1:18080'
const username = process.env.QA_STUDENT_USERNAME || 'e2e-multi-qa260928-user'
const password = process.env.QA_STUDENT_PASSWORD || 'E2e-123456'
const artifactDir = path.resolve(
  process.env.QA_ARTIFACT_DIR || '.artifacts/manual-multi-flow/e2e-multi-qa260928-run2',
)

mkdirSync(artifactDir, { recursive: true })
const logPath = path.join(artifactDir, 'student-a-ws-diagnostic.log')
function log(event, details = {}) {
  const entry = { at: new Date().toISOString(), event, ...details }
  appendFileSync(logPath, `${JSON.stringify(entry)}\n`, 'utf8')
  console.log(JSON.stringify(entry))
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
const page = await context.newPage()
const sockets = []
const responses = []
const failedRequests = []
const errors = []
page.on('websocket', (socket) => {
  const entry = { url: socket.url(), openedAt: new Date().toISOString(), framesReceived: [], framesSent: [], closeCount: 0, socketErrors: [] }
  sockets.push(entry)
  socket.on('framereceived', (frame) => {
    const payload = String(frame.payload)
    entry.framesReceived.push(payload)
    log('ws_frame_received', { url: entry.url, payload })
  })
  socket.on('framesent', (frame) => {
    const payload = String(frame.payload)
    entry.framesSent.push(payload)
    log('ws_frame_sent', { url: entry.url, payload })
  })
  socket.on('close', () => {
    entry.closeCount += 1
    entry.closedAt = new Date().toISOString()
    log('ws_closed', { url: entry.url, closeCount: entry.closeCount })
  })
  socket.on('socketerror', (error) => {
    entry.socketErrors.push(String(error))
    log('ws_socket_error', { url: entry.url, error: String(error) })
  })
  log('ws_opened', { url: entry.url })
})
page.on('response', (response) => {
  const url = response.url()
  if (url.includes('/api/v2/auth/') || url.includes('/api/v2/notifications/')) {
    const entry = { status: response.status(), url, method: response.request().method() }
    responses.push(entry)
    log('http_response', entry)
  }
})
page.on('requestfailed', (request) => {
  const entry = { url: request.url(), method: request.method(), failure: request.failure()?.errorText }
  failedRequests.push(entry)
  log('http_request_failed', entry)
})
page.on('pageerror', (error) => errors.push(error.message))
page.on('console', (message) => {
  if (message.type() !== 'error') return
  const url = message.location().url
  if (url.includes('/api/v2/auth/me') && message.text().includes('401')) return
  errors.push(`${message.text()} @ ${url}`)
})

try {
  await page.goto(`${baseURL}/login`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await page.locator('input').nth(0).fill(username)
  await page.locator('input').nth(1).fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL('**/dashboard', { timeout: 20_000 })
  await expect(page.locator('main.layout__main')).toBeVisible()
  await page.screenshot({ path: path.join(artifactDir, 'student-a-ws-diagnostic-start.png'), fullPage: true })
  await page.waitForTimeout(25_000)
  await page.screenshot({ path: path.join(artifactDir, 'student-a-ws-diagnostic-end.png'), fullPage: true })
  const result = { sockets, responses, failedRequests, errors, url: page.url() }
  writeFileSync(path.join(artifactDir, 'student-a-ws-diagnostic.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8')
  log('ws_diagnostic_complete', result)
} catch (error) {
  const details = error instanceof Error ? { message: error.message, stack: error.stack } : { error: String(error) }
  writeFileSync(path.join(artifactDir, 'student-a-ws-diagnostic.failure.json'), `${JSON.stringify({ ...details, sockets, responses, failedRequests, errors }, null, 2)}\n`, 'utf8')
  log('ws_diagnostic_failed', { ...details, sockets, responses, failedRequests, errors })
  throw error
} finally {
  await context.close()
  await browser.close()
}
