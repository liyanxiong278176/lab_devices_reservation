import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const qaDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const rootDir = path.resolve(qaDir, '..')
const require = createRequire(path.join(rootDir, 'frontend', 'package.json'))
const { chromium } = require('@playwright/test')
const resultsDir = path.join(qaDir, 'results', 'playwright')
const accounts = JSON.parse(await readFile(path.join(qaDir, 'results', 'accounts.local.json'), 'utf8'))
const seed = JSON.parse(await readFile(path.join(qaDir, 'results', 'seed_ids.json'), 'utf8'))
const prefix = seed.prefix
const deviceAName = `${prefix} approval device`
const deviceBName = `${prefix} direct device`
const baseUrl = 'http://127.0.0.1:5173'
const errors = []
const browser = await chromium.launch({ headless: true })

async function login(page, account) {
  await page.goto(`${baseUrl}/login`)
  await page.getByPlaceholder('请输入用户名').fill(accounts[account].username)
  await page.getByPlaceholder('请输入密码').fill(accounts[account].password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL('**/dashboard', { timeout: 15000 })
  await page.locator('.layout__menu').waitFor()
}

try {
  await mkdir(resultsDir, { recursive: true })

  const studentContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const student = await studentContext.newPage()
  student.on('pageerror', (error) => errors.push(`student pageerror: ${error.message}`))
  await login(student, 'student_a')
  const studentMenu = student.locator('.layout__menu')
  assert.equal(await studentMenu.getByText('AI 工作台', { exact: true }).count(), 1)
  assert.equal(await studentMenu.getByText('待审批', { exact: true }).count(), 0)
  await student.goto(`${baseUrl}/devices`)
  await student.getByText(deviceAName, { exact: false }).waitFor({ timeout: 15000 })
  const studentDeviceText = await student.locator('body').innerText()
  const normalizedDeviceText = studentDeviceText.toLocaleLowerCase()
  assert.ok(normalizedDeviceText.includes(deviceAName.toLocaleLowerCase()), 'student cannot see the own-college fixture device')
  assert.ok(!normalizedDeviceText.includes(deviceBName.toLocaleLowerCase()), 'student page leaked the other-college fixture device')
  await student.screenshot({ path: path.join(resultsDir, 'student-device-tenant-scope.png'), fullPage: true })

  await studentMenu.getByText('AI 工作台', { exact: true }).click()
  await student.waitForURL('**/ai', { timeout: 10000 })
  await student.getByText('AI 服务就绪', { exact: true }).waitFor({ timeout: 15000 })
  await student.getByText('查看我的预约', { exact: true }).click()
  await student.getByRole('button', { name: '发送' }).click()
  const assistantMessage = student.locator('.chat-message--assistant').last()
  await assistantMessage.waitFor({ timeout: 45000 })
  await student.waitForFunction(() => {
    const items = document.querySelectorAll('.chat-message--assistant .chat-message__bubble')
    return items.length > 0 && (items[items.length - 1].textContent || '').trim().length > 0
  }, null, { timeout: 45000 })
  const answer = await assistantMessage.innerText()
  assert.ok(answer.length > 0, 'AI business-query response is empty')
  await student.screenshot({ path: path.join(resultsDir, 'student-ai-business-query.png'), fullPage: true })

  const managerContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const manager = await managerContext.newPage()
  manager.on('pageerror', (error) => errors.push(`manager pageerror: ${error.message}`))
  await login(manager, 'manager_a')
  const managerMenu = manager.locator('.layout__menu')
  assert.equal(await managerMenu.getByText('待审批', { exact: true }).count(), 1)
  await manager.goto(`${baseUrl}/approvals/pending`)
  await manager.getByText('待审批', { exact: false }).first().waitFor({ timeout: 15000 })
  await manager.screenshot({ path: path.join(resultsDir, 'manager-approval-scope.png'), fullPage: true })

  assert.deepEqual(errors, [], 'browser reported uncaught errors')
  await writeFile(
    path.join(resultsDir, 'summary.json'),
    JSON.stringify({
      outcome: 'passed',
      checks: [
        'student menu permissions hide approvals',
        'student device page shows own college and hides other college',
        'student can use live API-backed read-only AI reservation query',
        'manager menu exposes pending approvals',
      ],
      ai_answer_characters: answer.length,
      screenshots: [
        'student-device-tenant-scope.png',
        'student-ai-business-query.png',
        'manager-approval-scope.png',
      ],
    }, null, 2),
    'utf8',
  )
  console.log('UI_E2E_PASSED: student tenant scope, permissions, AI business query, manager approval visibility')
  await managerContext.close()
  await studentContext.close()
} finally {
  await browser.close()
}
