import { execFileSync } from 'node:child_process'
import { mkdir } from 'node:fs/promises'
import { dirname } from 'node:path'
import { test, expect, type Page, type TestInfo } from '@playwright/test'

type Fixture = {
  prefix: string
  username: string
  alternate_username: string
  password: string
  admin_username: string
  device_id: number
  device_name: string
  second_device_name: string
}

const samplePng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p1sAAAAASUVORK5CYII=',
  'base64',
)

let prefix = ''
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

async function login(page: Page, username: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/dashboard/)
}

function today(): string {
  const date = new Date()
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

async function selectDateRange(page: Page, date: string) {
  const start = page.locator('input[placeholder="开始日期"]')
  await start.click()
  await start.fill(date)
  await page.keyboard.press('Enter')
  const end = page.locator('input[placeholder="结束日期"]')
  await end.fill(date)
  await page.keyboard.press('Enter')
}

async function attachEvidence(page: Page, dialogName: string, fileName: string) {
  await page.getByRole('dialog', { name: dialogName }).locator('input[type="file"]').setInputFiles({
    name: fileName,
    mimeType: 'image/png',
    buffer: samplePng,
  })
}

async function capture(page: Page, testInfo: TestInfo, name: string) {
  const file = testInfo.outputPath(`${name}.png`)
  await mkdir(dirname(file), { recursive: true })
  await expect(page.locator('.layout__canvas')).toBeVisible()
  await expect(page.locator('.layout__canvas .el-loading-mask')).toHaveCount(0)
  await page.screenshot({ path: file, fullPage: true, animations: 'disabled' })
  console.log(`PAGE_SCREENSHOT ${file}`)
}

async function visitMenuPage(
  page: Page,
  testInfo: TestInfo,
  menu: string,
  heading: string,
  screenshot: string,
) {
  await page.getByRole('menuitem', { name: menu, exact: true }).click()
  await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
  await capture(page, testInfo, screenshot)
}

test.describe('普通用户与管理员非 AI 页面实际渲染截图验收', () => {
  test.beforeEach(() => {
    prefix = `e2e-page-${Date.now().toString(36)}`
    fixture = JSON.parse(fixtureCommand('seed')) as Fixture
  })

  test.afterEach(() => {
    fixtureCommand('cleanup')
  })

  test('非 AI 菜单页面、预约与报修协作链路及预期错误状态均截图验证', async ({ browser }, testInfo) => {
    test.setTimeout(240_000)

    const pageErrors: string[] = []
    const serverErrors: string[] = []
    const unresolvedComponents: string[] = []
    const csrfFailures: string[] = []
    const watchPage = (page: Page) => {
      page.on('pageerror', (error) => pageErrors.push(error.message))
      page.on('console', (message) => {
        if (message.type() === 'warning' && /Failed to resolve component/.test(message.text())) {
          unresolvedComponents.push(message.text())
        }
      })
      page.on('response', (response) => {
        if (new URL(response.url()).hostname === '127.0.0.1' && response.status() >= 500) {
          serverErrors.push(`${response.status()} ${response.request().method()} ${response.url()}`)
        }
      })
    }

    const invalidContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    const invalidPage = await invalidContext.newPage()
    watchPage(invalidPage)
    invalidPage.on('response', async (response) => {
      if (response.status() < 400) return
      const url = new URL(response.url())
      if (!url.pathname.startsWith('/api/v2/')) return
      const body = await response.json().catch(() => null)
      if (typeof body?.code === 'string' && body.code.startsWith('CSRF_')) {
        csrfFailures.push(`${response.request().method()} ${url.pathname} ${body.code}`)
      }
    })
    await invalidPage.goto('/login')
    await invalidPage.getByLabel('用户名').fill(`${prefix}-missing`)
    await invalidPage.getByLabel('密码').fill('Wrong-password-123')
    await invalidPage.getByRole('button', { name: '登录' }).click()
    await expect(invalidPage.getByText('用户名或密码错误')).toBeVisible()
    await expect(invalidPage.locator('.el-message--error')).toHaveCount(1)
    await expect(invalidPage.locator('.el-message--error .el-message__content')).toHaveText(
      '用户名或密码错误',
    )
    expect(csrfFailures, '错误凭据只应显示凭据错误，不应混入 CSRF 会话错误').toEqual([])
    // The login toast is viewport-fixed; a full-page capture can clip it at
    // the document's top edge even though it is visible in the browser.
    await invalidPage.waitForTimeout(450) // Let Element Plus finish its 400 ms enter transition.
    await invalidPage.screenshot({ path: testInfo.outputPath('expected-error-invalid-login.png') })
    await invalidContext.close()

    const userContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    const userPage = await userContext.newPage()
    watchPage(userPage)
    await login(userPage, fixture.username, fixture.password)
    await expect(userPage.getByRole('heading', { name: '我的仪表盘', exact: true })).toBeVisible()

    const reservationPurpose = `页面验收预约 ${prefix}`
    const reservationDate = today()
    await userPage.getByRole('menuitem', { name: '设备', exact: true }).click()
    await expect(userPage.getByRole('heading', { name: '设备浏览', exact: true })).toBeVisible()
    const deviceCard = userPage.locator('.device-card').filter({
      has: userPage.getByText(fixture.device_name, { exact: true }),
    })
    await expect(deviceCard).toBeVisible()
    await deviceCard.getByRole('button', { name: '预约' }).click()
    await expect(userPage.getByRole('heading', { name: '预约设备', exact: true })).toBeVisible()
    await selectDateRange(userPage, reservationDate)
    await userPage.getByPlaceholder('例如：完成材料拉伸实验并采集三组数据').fill(reservationPurpose)
    await expect(userPage.locator('.preflight-summary')).toContainText('1 天可用')
    await expect(userPage.getByRole('button', { name: '提交预约' })).toBeEnabled()
    await capture(userPage, testInfo, 'user-reservation-create-available')
    await userPage.getByRole('button', { name: '提交预约' }).click()
    await expect(userPage).toHaveURL(/reservations\/mine/)
    const reservationCard = userPage.locator('.mine__card').filter({ hasText: reservationPurpose })
    await expect(reservationCard).toBeVisible()
    await expect(reservationCard).toContainText('待审批')

    const alternateContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    const alternatePage = await alternateContext.newPage()
    watchPage(alternatePage)
    await login(alternatePage, fixture.alternate_username, fixture.password)
    await alternatePage.goto(`/reservations/create?deviceId=${fixture.device_id}&startDate=${reservationDate}&endDate=${reservationDate}`)
    await expect(alternatePage.locator('.conflict-tip')).toBeVisible()
    await expect(alternatePage.getByRole('button', { name: '提交预约' })).toBeDisabled()
    await capture(alternatePage, testInfo, 'expected-error-reservation-date-conflict')
    await alternateContext.close()

    const repairTitle = `页面验收报修 ${prefix}`
    await userPage.getByRole('menuitem', { name: '提交报修', exact: true }).click()
    await expect(userPage.getByRole('heading', { name: '提交报修', exact: true })).toBeVisible()
    await expect(userPage.getByText('JPG、PNG、WebP，最多 6 张，每张不超过 5 MB')).toBeVisible()
    await capture(userPage, testInfo, 'user-repair-submit-empty')
    await userPage.getByRole('button', { name: '提交报修' }).click()
    await expect(userPage.locator('.el-form-item__error').first()).toBeVisible()
    await userPage.screenshot({ path: testInfo.outputPath('expected-error-repair-required-fields.png'), fullPage: true })
    await userPage.locator('.rsubmit__el-form .el-select').click()
    await userPage.getByRole('option', { name: new RegExp(fixture.second_device_name) }).click()
    await userPage.getByPlaceholder('一句话描述故障').fill(repairTitle)
    await userPage.getByPlaceholder('故障现象、复现步骤等').fill('页面联调验收：设备启动后无法完成自检，需负责人检查。')
    await userPage.getByRole('button', { name: '提交报修' }).click()
    await expect(userPage).toHaveURL(/repairs\/mine/)
    const repairCard = userPage.locator('.rmine__card').filter({ hasText: repairTitle })
    await expect(repairCard).toBeVisible()
    await expect(repairCard.locator('.rmine__card-head')).toContainText('待受理')

    const adminContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    const adminPage = await adminContext.newPage()
    watchPage(adminPage)
    await login(adminPage, fixture.admin_username, fixture.password)

    await adminPage.getByRole('menuitem', { name: '待审批', exact: true }).click()
    const approvalCard = adminPage.locator('.approval__card').filter({ hasText: fixture.device_name })
    await expect(approvalCard).toBeVisible()
    await expect(approvalCard).toContainText(fixture.device_name)
    await capture(adminPage, testInfo, 'admin-approvals-pending')
    await approvalCard.getByRole('button', { name: '通过' }).click()
    await expect(approvalCard).toHaveCount(0)

    await adminPage.getByRole('menuitem', { name: '设备交接', exact: true }).click()
    const handoverCard = adminPage.locator('.handover-card').filter({ hasText: fixture.device_name })
    await expect(handoverCard).toBeVisible()
    await capture(adminPage, testInfo, 'admin-handover-pending')
    await handoverCard.getByRole('button', { name: '核对并完成交接' }).click()
    await expect(adminPage.getByRole('dialog', { name: '完成设备交接' })).toBeVisible()
    await attachEvidence(adminPage, '完成设备交接', 'page-audit-handover.png')
    await adminPage.getByRole('dialog', { name: '完成设备交接' }).getByRole('button', { name: '确认' }).click()
    await expect(handoverCard).toHaveCount(0)

    await userPage.goto('/reservations/mine')
    const inUseCard = userPage.locator('.mine__card').filter({ hasText: reservationPurpose })
    await expect(inUseCard).toContainText('使用中')
    await inUseCard.getByRole('button', { name: '归还' }).click()
    await expect(userPage.getByRole('dialog', { name: '提交归还' })).toBeVisible()
    await attachEvidence(userPage, '提交归还', 'page-audit-return.png')
    await userPage.getByRole('dialog', { name: '提交归还' }).getByRole('button', { name: '确认归还' }).click()
    await expect(inUseCard).toContainText('待负责人验收')

    await adminPage.reload()
    await adminPage.getByRole('radio', { name: '待验收' }).click()
    const returnAcceptanceCard = adminPage.locator('.handover-card').filter({ hasText: fixture.device_name })
    await expect(returnAcceptanceCard).toBeVisible()
    await capture(adminPage, testInfo, 'admin-return-acceptance-pending')
    await returnAcceptanceCard.getByRole('button', { name: '核对并确认验收' }).click()
    const acceptanceDialog = adminPage.getByRole('dialog', { name: '确认归还验收' })
    await expect(acceptanceDialog).toBeVisible()
    await acceptanceDialog.getByRole('button', { name: '确认' }).click()
    await expect(returnAcceptanceCard).toHaveCount(0)

    await adminPage.getByRole('menuitem', { name: '报修处理', exact: true }).click()
    let repairRow = adminPage.locator('.el-table__row').filter({ hasText: repairTitle })
    await expect(repairRow).toBeVisible()
    await capture(adminPage, testInfo, 'admin-repair-pending')
    await repairRow.getByRole('button', { name: '受理' }).click()
    await repairRow.getByRole('button', { name: '解决' }).click()
    await adminPage.getByPlaceholder('说明处理方式与结果(必填)').fill('检查电源连接并完成自检，设备恢复正常。')
    await adminPage.locator('.radmin__drawer-actions').getByRole('button', { name: '确认处理', exact: true }).click()
    await expect(repairRow).toContainText('待用户确认')
    await userPage.goto('/repairs/mine')
    const resolvedRepairCard = userPage.locator('.rmine__card').filter({ hasText: repairTitle })
    await expect(resolvedRepairCard.getByRole('button', { name: '确认已修复' })).toBeVisible()
    await resolvedRepairCard.getByRole('button', { name: '确认已修复' }).click()
    await userPage.getByRole('dialog').getByRole('button', { name: '确认已修复' }).click()
    await expect(resolvedRepairCard.locator('.rmine__card-head')).toContainText('已完成')

    const userPages = [
      ['仪表盘', '我的仪表盘', 'user-dashboard'],
      ['设备', '设备浏览', 'user-devices'],
      ['我的预约', '我的预约', 'user-reservations'],
      ['我的通知', '通知中心', 'user-notifications'],
      ['提交报修', '提交报修', 'user-repair-submit'],
      ['我的报修', '我的报修', 'user-repairs'],
    ] as const
    for (const [menu, heading, screenshot] of userPages) {
      await visitMenuPage(userPage, testInfo, menu, heading, screenshot)
      if (screenshot === 'user-dashboard') {
        const badge = userPage.locator('.layout__icon-button .el-badge__content')
        const unreadCard = userPage.locator('.stat-card').filter({ hasText: '未读通知' })
        await expect.poll(async () => {
          const badgeCount = Number((await badge.textContent())?.trim() || 0)
          const cardCount = Number((await unreadCard.locator('.stat-card__value').textContent())?.trim() || 0)
          return badgeCount === cardCount ? badgeCount : -1
        }, { message: '仪表盘未读数与顶部通知铃铛必须收敛到同一计数' }).toBeGreaterThanOrEqual(0)
      }
      if (screenshot === 'user-notifications') {
        const badge = userPage.locator('.layout__icon-button .el-badge__content')
        const unreadSummary = userPage.locator('.notif-overview__count strong')
        await expect.poll(async () => {
          const badgeCount = Number((await badge.textContent())?.trim() || 0)
          const pageCount = Number((await unreadSummary.textContent())?.trim() || 0)
          return badgeCount === pageCount ? badgeCount : -1
        }, { message: '通知中心未读数与顶部通知铃铛必须一致' }).toBeGreaterThanOrEqual(0)
      }
    }
    await expect(userPage.getByRole('menuitem', { name: '待审批', exact: true })).toHaveCount(0)
    await userPage.goto('/users')
    await expect(userPage).toHaveURL(/dashboard/)
    await expect(userPage.getByRole('heading', { name: '我的仪表盘', exact: true })).toBeVisible()
    await capture(userPage, testInfo, 'expected-error-user-admin-route-redirect')

    const adminPages = [
      ['仪表盘', '仪表盘', 'admin-dashboard'],
      ['设备', '设备浏览', 'admin-devices'],
      ['我的通知', '通知中心', 'admin-notifications'],
      ['设备管理', '设备管理', 'admin-device-management'],
      ['运营报表', '运营报表', 'admin-reports'],
      ['预约规则', '预约规则中心', 'admin-reservation-rules'],
      ['维护与校准', '维护与校准', 'admin-maintenance'],
      ['用户管理', '用户管理', 'admin-users'],
      ['组织管理', '组织管理', 'admin-organization'],
      ['角色权限', '角色与权限', 'admin-rbac'],
    ] as const
    for (const [menu, heading, screenshot] of adminPages) {
      await visitMenuPage(adminPage, testInfo, menu, heading, screenshot)
    }

    expect(pageErrors, '所有已访问页面不得有未捕获的 Vue/浏览器异常').toEqual([])
    expect(unresolvedComponents, '所有已访问页面的 Vue 组件都必须正确注册').toEqual([])
    expect(serverErrors, '页面联调期间不应出现后端 5xx').toEqual([])
    await userContext.close()
    await adminContext.close()
  })
})
