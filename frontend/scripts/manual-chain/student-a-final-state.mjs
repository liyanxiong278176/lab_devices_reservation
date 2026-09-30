import { chromium, expect } from '@playwright/test'
import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const baseURL = process.env.PREVIEW_URL || 'http://127.0.0.1:18080'
const username = process.env.QA_STUDENT_USERNAME || 'e2e-multi-qa260928-user'
const password = process.env.QA_STUDENT_PASSWORD || 'E2e-123456'
const artifactDir = path.resolve(
  process.env.QA_ARTIFACT_DIR || '.artifacts/manual-multi-flow/e2e-multi-qa260928-run2',
)
const primaryPurpose = 'Student A 手工全链路预约与归还验证 QA260928'
const realtimePurpose = 'Student A 实时审批通知验证 QA260928 run2'
const deviceName = 'e2e-multi-qa260928-device'

mkdirSync(artifactDir, { recursive: true })
const logPath = path.join(artifactDir, 'student-a-final-state.log')
function log(event, details = {}) {
  const entry = { at: new Date().toISOString(), event, ...details }
  appendFileSync(logPath, `${JSON.stringify(entry)}\n`, 'utf8')
  console.log(JSON.stringify(entry))
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
const page = await context.newPage()
try {
  await page.goto(`${baseURL}/login`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await page.locator('input').nth(0).fill(username)
  await page.locator('input').nth(1).fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await page.waitForURL('**/dashboard', { timeout: 20_000 })
  await page.goto(`${baseURL}/reservations/mine`, { waitUntil: 'domcontentloaded' })
  const completedCard = page.locator('.mine__card').filter({ hasText: primaryPurpose }).filter({ hasText: deviceName })
  const approvedCard = page.locator('.mine__card').filter({ hasText: realtimePurpose }).filter({ hasText: deviceName })
  await expect(completedCard).toHaveCount(1, { timeout: 30_000 })
  await expect(completedCard).toContainText('已完成')
  await expect(approvedCard).toHaveCount(1, { timeout: 30_000 })
  await expect(approvedCard).toContainText('已通过')
  await page.screenshot({ path: path.join(artifactDir, 'student-a-final-mine.png'), fullPage: true })

  await completedCard.getByRole('button', { name: '详情' }).click()
  await expect(page.locator('.rsv-detail')).toContainText('负责人已完成验收')
  await expect(page.locator('.rsv-detail')).toContainText('设备已归还')
  await page.screenshot({ path: path.join(artifactDir, 'student-a-final-detail.png'), fullPage: true })
  const result = {
    completedReservation: { reservationId: 3, purpose: primaryPurpose, status: 'COMPLETED', detailVerified: true },
    realtimeReservation: { reservationId: 5, purpose: realtimePurpose, status: 'APPROVED' },
  }
  writeFileSync(path.join(artifactDir, 'student-a.final-state.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8')
  log('student_a_final_state_verified', result)
} catch (error) {
  const details = error instanceof Error ? { message: error.message, stack: error.stack } : { error: String(error) }
  try { await page.screenshot({ path: path.join(artifactDir, 'student-a-final-state-failure.png'), fullPage: true }) } catch {}
  writeFileSync(path.join(artifactDir, 'student-a-final-state.failure.json'), `${JSON.stringify(details, null, 2)}\n`, 'utf8')
  log('student_a_final_state_failed', { ...details, url: page.url() })
  throw error
} finally {
  await context.close()
  await browser.close()
}
