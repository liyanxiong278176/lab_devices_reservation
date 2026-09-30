import { chromium, expect } from '@playwright/test'
import { appendFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const baseURL = process.env.PREVIEW_URL || 'http://127.0.0.1:18080'
const username = process.env.QA_STUDENT_USERNAME || 'e2e-multi-qa260928-user'
const password = process.env.QA_STUDENT_PASSWORD || 'E2e-123456'
const artifactDir = path.resolve(
  process.env.QA_ARTIFACT_DIR || '.artifacts/manual-multi-flow/e2e-multi-qa260928-run2',
)
const reservationId = Number(process.env.QA_RESERVATION_ID || 3)
const deviceName = 'e2e-multi-qa260928-device'
const purpose = 'Student A 手工全链路预约与归还验证 QA260928'

mkdirSync(artifactDir, { recursive: true })
const logPath = path.join(artifactDir, 'student-a-return.log')
const returnGoPath = path.join(artifactDir, 'return.go')
const acceptanceGoPath = path.join(artifactDir, 'acceptance.go')
const readyPath = path.join(artifactDir, 'student-a-return.ready.json')

function log(event, details = {}) {
  const entry = { at: new Date().toISOString(), event, ...details }
  appendFileSync(logPath, `${JSON.stringify(entry)}\n`, 'utf8')
  console.log(JSON.stringify(entry))
}

async function waitForFile(file, label, timeoutMs = 10 * 60_000) {
  const start = Date.now()
  while (!existsSync(file)) {
    if (Date.now() - start > timeoutMs) throw new Error(`Timed out waiting for ${label}: ${file}`)
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  log('signal_received', { label })
}

function ownCard(page) {
  return page.locator('.mine__card').filter({ hasText: deviceName }).filter({ hasText: purpose })
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
const page = await context.newPage()
const websocketUrls = []
const websocketFrames = []
page.on('websocket', (socket) => {
  websocketUrls.push(socket.url())
  socket.on('framereceived', (frame) => {
    const payload = String(frame.payload)
    websocketFrames.push(payload)
    log('websocket_frame_received', { payload })
  })
  log('websocket_connected', { url: socket.url() })
})

try {
  await page.goto(`${baseURL}/login`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await page.locator('input').nth(0).fill(username)
  await page.locator('input').nth(1).fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL('**/dashboard', { timeout: 20_000 })
  await expect.poll(() => websocketUrls.length, { timeout: 15_000 }).toBeGreaterThan(0)
  await page.goto(`${baseURL}/reservations/mine`, { waitUntil: 'domcontentloaded' })
  const card = ownCard(page)
  await expect(card).toHaveCount(1, { timeout: 30_000 })
  await expect(card.locator('.mine__card-id')).toHaveText(`#${reservationId}`)
  await page.screenshot({ path: path.join(artifactDir, 'student-a-return-ready.png'), fullPage: true })
  writeFileSync(readyPath, `${JSON.stringify({ username, reservationId, deviceName, ready: true }, null, 2)}\n`, 'utf8')
  log('return_runner_ready', { reservationId, initialCard: (await card.innerText()).slice(0, 300) })

  await waitForFile(returnGoPath, 'return.go')
  await page.reload({ waitUntil: 'domcontentloaded' })
  const activeCard = ownCard(page)
  await expect(activeCard).toContainText('使用中', { timeout: 30_000 })
  const returnButton = activeCard.getByRole('button', { name: '归还' })
  await expect(returnButton).toBeVisible()
  await returnButton.click()
  const dialog = page.getByRole('dialog', { name: '提交归还' })
  await expect(dialog).toBeVisible()
  const image = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jvuoAAAAASUVORK5CYII=',
    'base64',
  )
  await dialog.locator('input[type="file"]').setInputFiles({
    name: 'student-a-return-1x1.png',
    mimeType: 'image/png',
    buffer: image,
  })
  await expect(dialog.getByText('1 张已选择')).toBeVisible()
  const responsePromise = page.waitForResponse((response) =>
    response.url().includes(`/api/v2/reservations/${reservationId}/return`)
      && response.request().method() === 'POST', { timeout: 30_000 })
  await dialog.getByRole('button', { name: '确认归还' }).click()
  const response = await responsePromise
  expect(response.status()).toBe(200)
  await expect(activeCard).toContainText('待负责人验收', { timeout: 30_000 })
  await page.screenshot({ path: path.join(artifactDir, 'student-a-return-pending.png'), fullPage: true })
  const returned = { reservationId, deviceName, returnCondition: 'NORMAL', image: 'student-a-return-1x1.png', status: 'RETURN_PENDING' }
  writeFileSync(path.join(artifactDir, 'student-a.returned.json'), `${JSON.stringify(returned, null, 2)}\n`, 'utf8')
  log('return_submitted', { ...returned, httpStatus: response.status() })

  // Stay on the live reservation page. This title is emitted only by the real-time notification handler.
  const acceptedToast = page.locator('.el-notification').filter({ hasText: '设备归还已验收' }).first()
  await expect(acceptedToast).toBeVisible({ timeout: 180_000 })
  await page.screenshot({ path: path.join(artifactDir, 'student-a-acceptance-toast.png'), fullPage: true })
  log('acceptance_realtime_toast_verified', { reservationId, websocketUrls, websocketFrames })

  await page.goto(`${baseURL}/notifications`, { waitUntil: 'domcontentloaded' })
  const acceptanceRow = page.locator('.notif-row').filter({ hasText: '设备归还已验收' })
  await expect(acceptanceRow.first()).toBeVisible({ timeout: 30_000 })
  await expect(acceptanceRow.first()).toContainText(deviceName)
  await page.screenshot({ path: path.join(artifactDir, 'student-a-acceptance-history.png'), fullPage: true })
  const realtimeAcceptance = {
    reservationId,
    deviceName,
    toast: '设备归还已验收',
    notificationHistory: true,
    websocketUrls,
    websocketFrames,
  }
  writeFileSync(
    path.join(artifactDir, 'student-a.realtime-acceptance.json'),
    `${JSON.stringify(realtimeAcceptance, null, 2)}\n`,
    'utf8',
  )
  log('acceptance_realtime_history_verified', realtimeAcceptance)

  await waitForFile(acceptanceGoPath, 'acceptance.go')
  await page.goto(`${baseURL}/reservations/mine`, { waitUntil: 'domcontentloaded' })
  const completedCard = ownCard(page)
  await expect(completedCard).toContainText('已完成', { timeout: 60_000 })
  await completedCard.getByRole('button', { name: '详情' }).click()
  await expect(page.locator('.rsv-detail')).toContainText('负责人已完成验收', { timeout: 30_000 })
  await page.screenshot({ path: path.join(artifactDir, 'student-a-completed-detail.png'), fullPage: true })
  const completed = { reservationId, deviceName, status: 'COMPLETED', finalAcceptance: 'verified in reservation details' }
  writeFileSync(path.join(artifactDir, 'student-a.completed.json'), `${JSON.stringify(completed, null, 2)}\n`, 'utf8')
  log('complete_chain_verified', completed)
} catch (error) {
  const details = error instanceof Error ? { message: error.message, stack: error.stack } : { error: String(error) }
  try {
    await page.screenshot({ path: path.join(artifactDir, 'student-a-return-failure.png'), fullPage: true })
  } catch {
    // Preserve the first error if the browser is already unavailable.
  }
  writeFileSync(path.join(artifactDir, 'student-a-return.failure.json'), `${JSON.stringify(details, null, 2)}\n`, 'utf8')
  log('return_runner_failed', { ...details, url: page.url() })
  throw error
} finally {
  await context.close()
  await browser.close()
}
