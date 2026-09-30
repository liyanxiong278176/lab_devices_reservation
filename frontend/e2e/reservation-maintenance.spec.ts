import { execFileSync } from 'node:child_process'
import { test, expect, type Page } from '@playwright/test'

type Fixture = {
  password: string
  manager_username: string
  device_id: number
  device_name: string
}

const prefix = `e2e-maint-${Date.now().toString(36)}`
let fixture: Fixture

function fixtureCommand(action: 'seed' | 'cleanup'): string {
  return execFileSync(
    'uv',
    ['run', 'python', 'scripts/e2e_fixture.py', action, '--prefix', prefix],
    {
      cwd: new URL('../../backend', import.meta.url),
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'inherit'],
    },
  ).trim()
}

async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(fixture.manager_username)
  await page.getByLabel('密码').fill(fixture.password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/dashboard/)
}

function today(): string {
  const value = new Date()
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

test.describe('预约规则与设备维护实际页面链路', () => {
  test.beforeAll(() => {
    fixture = JSON.parse(fixtureCommand('seed')) as Fixture
  })

  test.afterAll(() => {
    fixtureCommand('cleanup')
  })

  test('负责人保存预约规则，并完成校准计划和凭证记录', async ({ page }, testInfo) => {
    // Exercise the UUID fallback used when randomUUID is unavailable on HTTP origins.
    await page.addInitScript(() => {
      Object.defineProperty(Crypto.prototype, 'randomUUID', {
        configurable: true,
        value: undefined,
      })
    })
    const apiErrors: string[] = []
    let evidenceUploads = 0
    page.on('pageerror', (error) => apiErrors.push(error.message))
    page.on('request', (request) => {
      if (/\/api\/v2\/devices\/\d+\/maintenance-evidence$/.test(new URL(request.url()).pathname)) {
        evidenceUploads += 1
      }
    })
    page.on('response', (response) => {
      if (response.status() >= 500) apiErrors.push(`${response.status()} ${new URL(response.url()).pathname}`)
    })
    await login(page)

    await page.goto('/reservation-rules')
    await expect(page.getByRole('heading', { name: '预约规则中心', exact: true })).toBeVisible()
    const editor = page.locator('.rules-panel__editor')
    await editor.locator('.el-form-item').nth(0).locator('.el-select').click()
    await page.getByRole('option', { name: '设备', exact: true }).click()

    const scopeObject = editor.locator('.el-form-item').nth(1).locator('.el-select')
    await scopeObject.click()
    await scopeObject.locator('input').fill(fixture.device_name)
    const deviceOption = page.getByRole('option', {
      name: new RegExp(`设备 #${fixture.device_id} · ${fixture.device_name} ·`),
    })
    await expect(deviceOption).toBeVisible()
    await deviceOption.click()

    const maxDays = editor.locator('.el-form-item').nth(3).locator('input')
    await maxDays.fill('3')
    await maxDays.press('Tab')
    await editor.locator('.el-form-item').nth(5).locator('.el-select').click()
    await page.getByRole('option', { name: '需要负责人审批', exact: true }).click()

    const saveRuleResponse = page.waitForResponse((response) =>
      response.request().method() === 'PUT' && new URL(response.url()).pathname.endsWith('/api/v2/reservation-rules'),
    )
    await editor.getByRole('button', { name: '保存规则' }).click()
    expect((await saveRuleResponse).status()).toBe(200)
    const ruleRow = page.locator('.rules-panel__table .el-table__row').filter({ hasText: fixture.device_name })
    await expect(ruleRow).toContainText('3 天')
    await expect(ruleRow).toContainText('需审批')

    const rulesFilter = page.locator('.rules-panel__filters')
    const filteredRulesResponse = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return response.request().method() === 'GET'
        && url.pathname.endsWith('/api/v2/reservation-rules')
        && url.searchParams.get('scope_type') === 'DEVICE'
    })
    await rulesFilter.locator('.el-select').nth(0).click()
    await page.getByRole('option', { name: '设备', exact: true }).last().click()
    expect((await filteredRulesResponse).status()).toBe(200)
    await expect(ruleRow).toContainText('3 天')

    const deleteRuleResponse = page.waitForResponse((response) =>
      response.request().method() === 'DELETE'
      && /^\/api\/v2\/reservation-rules\/\d+$/.test(new URL(response.url()).pathname),
    )
    await ruleRow.getByRole('button', { name: '删除' }).click()
    await page.getByRole('button', { name: '删除规则' }).click()
    expect((await deleteRuleResponse).status()).toBe(200)
    await expect(ruleRow).toHaveCount(0)

    await page.goto('/maintenance')
    await expect(page.getByRole('heading', { name: '设备维护计划', exact: true })).toBeVisible()
    await page.getByRole('button', { name: '新建维护计划' }).click()
    const planDialog = page.getByRole('dialog')
    const deviceSelect = planDialog.locator('.el-form-item').nth(0).locator('.el-select')
    await deviceSelect.click()
    await deviceSelect.locator('input').fill(fixture.device_name)
    const maintenanceDevice = page.getByRole('option', {
      name: new RegExp(`#${fixture.device_id} · ${fixture.device_name} ·`),
    })
    await expect(maintenanceDevice).toBeVisible()
    await maintenanceDevice.click()
    await planDialog.locator('.el-form-item').nth(1).locator('.el-select').click()
    await page.getByRole('option', { name: '仪器校准', exact: true }).click()
    await planDialog.locator('.el-form-item').nth(2).locator('input').fill(`${prefix} 年度校准`)
    await planDialog.locator('.el-form-item').nth(4).locator('input').fill(today())

    const createPlanResponse = page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && new URL(response.url()).pathname === `/api/v2/devices/${fixture.device_id}/maintenance-plans`,
    )
    await planDialog.getByRole('button', { name: '保存计划' }).click()
    expect((await createPlanResponse).status()).toBe(201)
    const planRow = page.locator('.el-table__row').filter({ hasText: `${prefix} 年度校准` })
    await expect(planRow).toBeVisible()

    await planRow.getByRole('button', { name: '完成记录' }).click()
    const historyDialog = page.getByRole('dialog')
    await expect(historyDialog.getByText('暂无完成记录')).toBeVisible()
    await expect(historyDialog.locator('.empty-state__icon-well svg')).toBeVisible()
    await historyDialog.locator('.el-dialog__headerbtn').click()

    await planRow.getByRole('button', { name: '登记完成' }).click()
    const completionDialog = page.getByRole('dialog')
    await completionDialog.getByRole('button', { name: '提交完成记录' }).click()
    await expect(page.getByText('校准与安全检查必须上传证书或检查记录')).toBeVisible()
    await completionDialog.locator('input[type="file"]').setInputFiles({
      name: 'calibration-certificate.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.7\nE2E calibration certificate'),
    })

    const recordEndpoint = /\/api\/v2\/maintenance-plans\/\d+\/records$/
    let discardFirstResponse = true
    await page.route(recordEndpoint, async (route) => {
      const upstream = await route.fetch()
      if (discardFirstResponse) {
        discardFirstResponse = false
        expect(upstream.status()).toBe(201)
        await route.abort('failed')
        return
      }
      await route.fulfill({ response: upstream })
    })
    const lostResponse = page.waitForEvent('requestfailed', (request) =>
      recordEndpoint.test(new URL(request.url()).pathname),
    )
    await completionDialog.getByRole('button', { name: '提交完成记录' }).click()
    await lostResponse
    const completeCycleResponse = page.waitForResponse((response) =>
      response.request().method() === 'POST'
      && recordEndpoint.test(new URL(response.url()).pathname),
    )
    await completionDialog.getByRole('button', { name: '提交完成记录' }).click()
    expect((await completeCycleResponse).status()).toBe(201)
    expect(evidenceUploads).toBe(1)
    await page.unroute(recordEndpoint)
    await expect(page.getByText('完成记录已保存，下次到期日已按实际完成日期顺延')).toBeVisible()
    await planRow.getByRole('button', { name: '完成记录' }).click()
    await expect(page.getByText('calibration-certificate.pdf')).toBeVisible()
    await page.getByRole('dialog').locator('.el-dialog__headerbtn').click()

    const deactivateResponse = page.waitForResponse((response) =>
      response.request().method() === 'PUT'
      && /^\/api\/v2\/maintenance-plans\/\d+$/.test(new URL(response.url()).pathname),
    )
    await planRow.getByRole('button', { name: '停用' }).click()
    const confirmDialog = page.locator('.el-message-box')
    await confirmDialog.getByRole('button', { name: '停用', exact: true }).click()
    expect((await deactivateResponse).status()).toBe(200)
    await expect(planRow).toHaveCount(0)
    await page.getByRole('radio', { name: '已停用' }).click()
    await expect(planRow).toBeVisible()
    await page.getByRole('radio', { name: '全部' }).click()
    await expect(planRow).toBeVisible()
    await page.getByRole('radio', { name: '生效中' }).click()
    await expect(planRow).toHaveCount(0)

    await page.screenshot({ path: testInfo.outputPath('maintenance-cycle-complete.png'), fullPage: true })
    expect(apiErrors).toEqual([])
  })
})
