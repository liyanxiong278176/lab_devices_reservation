import { javaCommand } from './java-command'
import { test, expect, type Page } from './flow-test'

const prefix = `e2e-preflight-${Date.now().toString(36)}`
let fixture: { username: string; admin_username: string; password: string; device_name: string }

async function login(page: Page, username: string) {
  await page.goto('/login')
  await page.getByLabel('用户名', { exact: true }).fill(username)
  await page.getByLabel('密码', { exact: true }).fill(fixture.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/dashboard/)
}

test.beforeAll(() => { fixture = JSON.parse(javaCommand('seed', prefix)) })
test.afterAll(() => { javaCommand('cleanup', prefix) })

test('预约预检422显示持久原因、不产生未处理异常并可恢复提交', async ({ browser }, testInfo) => {
  test.setTimeout(120_000)
  const adminContext = await browser.newContext()
  const userContext = await browser.newContext()
  const admin = await adminContext.newPage()
  const user = await userContext.newPage()
  admin.setDefaultTimeout(10_000)
  user.setDefaultTimeout(10_000)
  const errors: string[] = []
  user.on('pageerror', (error) => errors.push(error.message))
  try {
    await login(admin, fixture.admin_username)
    await admin.getByRole('menuitem', { name: '预约规则', exact: true }).click()
    const form = admin.locator('.rules-panel__editor')
    await form.locator('.el-form-item').filter({ has: admin.getByText('资源范围', { exact: true }) }).locator('.el-select').click()
    await admin.getByRole('option', { name: '设备', exact: true }).click()
    await form.locator('.el-form-item').filter({ hasText: '范围对象' }).locator('.el-select').click()
    await admin.getByRole('option').filter({ hasText: fixture.device_name }).filter({ hasNotText: `${fixture.device_name}-2` }).click()
    await form.locator('.el-form-item').filter({ hasText: '单次最多连续预约' }).getByRole('spinbutton').fill('1')
    await form.getByRole('button', { name: '保存规则', exact: true }).click()
    await expect(admin.locator('.el-table__row').filter({ hasText: fixture.device_name }).filter({ hasText: '普通用户' })).toBeVisible()

    await login(user, fixture.username)
    await user.getByRole('menuitem', { name: '设备', exact: true }).click()
    await user.locator('.device-card').filter({ has: user.getByText(fixture.device_name, { exact: true }) })
      .getByRole('button', { name: '预约', exact: true }).click()
    const days = user.locator('.availability-calendar__day')
    await expect(days.first()).toBeVisible()
    await days.nth(0).click()
    const rejected = user.waitForResponse((response) => new URL(response.url()).pathname === '/api/v2/reservations/preflight' && response.status() === 422)
    const nextDay = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai',
      year: 'numeric', month: '2-digit', day: '2-digit',
    }).format(new Date(Date.now() + 24 * 60 * 60 * 1000))
    await user.getByPlaceholder('结束日期').fill(nextDay)
    await user.getByPlaceholder('结束日期').press('Enter')
    expect((await rejected).status()).toBe(422)
    await user.getByPlaceholder('例如：完成材料拉伸实验并采集三组数据').fill('E2E 预检错误恢复')
    await expect(user.locator('.preflight-card').getByRole('alert')).toContainText(/预约|天/)
    await expect(user.getByRole('button', { name: '提交预约', exact: true })).toBeDisabled()
    await expect(user.locator('.el-message')).toHaveCount(0, { timeout: 10_000 })
    await expect(user.locator('.preflight-card').getByRole('alert')).toBeVisible()
    await user.screenshot({ path: testInfo.outputPath('preflight-error-visible.png'), fullPage: true })

    await days.nth(0).click()
    await expect(user.locator('.preflight-card').getByRole('alert')).toHaveCount(0)
    await expect(user.getByRole('button', { name: '提交预约', exact: true })).toBeEnabled()
    expect(errors).toEqual([])
  } finally {
    await adminContext.close()
    await userContext.close()
  }
})
