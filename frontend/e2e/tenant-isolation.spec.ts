import { execFileSync } from 'node:child_process'
import { test, expect, type Page } from '@playwright/test'

type Fixture = {
  prefix: string
  username: string
  alternate_username: string
  password: string
  admin_username: string
  manager_username: string
  device_name: string
  college_id: number
}

const suffix = Date.now().toString(36)
const prefixA = `e2e-${suffix}-a`
const prefixB = `e2e-${suffix}-b`
let collegeA: Fixture
let collegeB: Fixture

function fixtureCommand(action: 'seed' | 'cleanup', prefix: string): string {
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

function dateAfter(days: number): string {
  const value = new Date()
  value.setDate(value.getDate() + days)
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

test.describe.serial('普通用户与实验室负责人学院隔离页面验收', () => {
  test.beforeAll(() => {
    collegeA = JSON.parse(fixtureCommand('seed', prefixA)) as Fixture
    collegeB = JSON.parse(fixtureCommand('seed', prefixB)) as Fixture
  })

  test.afterAll(() => {
    fixtureCommand('cleanup', prefixB)
    fixtureCommand('cleanup', prefixA)
  })

  test('跨学院设备、预约和审批不可见；本学院负责人及系统管理员范围正确', async ({ browser }, testInfo) => {
    test.setTimeout(150_000)
    // Cookie-based authentication is shared by pages in a BrowserContext.
    // Each principal therefore needs its own context to exercise real isolation.
    const userAContext = await browser.newContext()
    const userA = await userAContext.newPage()
    const userBContext = await browser.newContext()
    const userB = await userBContext.newPage()
    const managerAContext = await browser.newContext()
    const managerA = await managerAContext.newPage()
    const managerBContext = await browser.newContext()
    const managerB = await managerBContext.newPage()
    const systemContext = await browser.newContext()
    const systemAdmin = await systemContext.newPage()

    await login(userA, collegeA.username, collegeA.password)
    await userA.getByRole('menuitem', { name: '设备', exact: true }).click()
    const userSearch = userA.getByPlaceholder('搜索设备名称 / 型号')
    await userSearch.fill(collegeB.device_name)
    await userSearch.press('Enter')
    await expect(userA.getByRole('heading', { name: '未找到匹配的设备', exact: true })).toBeVisible()
    await expect(userA.locator('.device-card').filter({ hasText: collegeB.device_name })).toHaveCount(0)
    await userA.screenshot({ path: testInfo.outputPath('cross-college-user-empty-device-list.png'), fullPage: true })

    await login(userB, collegeB.username, collegeB.password)
    await userB.getByRole('menuitem', { name: '设备', exact: true }).click()
    const deviceB = userB.locator('.device-card').filter({ has: userB.getByText(collegeB.device_name, { exact: true }) })
    await expect(deviceB).toBeVisible()
    await deviceB.getByRole('button', { name: '预约' }).click()
    const bookingDate = dateAfter(2)
    const startInput = userB.getByPlaceholder('开始日期')
    await startInput.fill(bookingDate)
    await startInput.press('Enter')
    const endInput = userB.getByPlaceholder('结束日期')
    await endInput.fill(bookingDate)
    await endInput.press('Enter')
    const purpose = 'E2E 跨学院隔离审批申请'
    await userB.getByPlaceholder('例如：完成材料拉伸实验并采集三组数据').fill(purpose)
    await expect(userB.getByRole('button', { name: '提交预约' })).toBeEnabled()
    await userB.getByRole('button', { name: '提交预约' }).click()
    await expect(userB).toHaveURL(/reservations\/mine/)
    await expect(userB.locator('.mine__card').filter({ hasText: purpose })).toContainText('待审批')

    await login(managerA, collegeA.manager_username, collegeA.password)
    await managerA.getByRole('menuitem', { name: '设备管理', exact: true }).click()
    const managerASearch = managerA.getByPlaceholder('按名称 / 品牌 / 型号检索')
    await managerASearch.fill(collegeB.device_name)
    await managerASearch.press('Enter')
    await expect(managerA.getByText('暂无设备', { exact: true })).toBeVisible()

    await managerA.getByRole('menuitem', { name: '待审批', exact: true }).click()
    await expect(managerA.getByRole('heading', { name: '暂无待审批申请', exact: true })).toBeVisible()
    await expect(managerA.locator('.approval__card').filter({ hasText: purpose })).toHaveCount(0)

    await login(managerB, collegeB.manager_username, collegeB.password)
    await managerB.getByRole('menuitem', { name: '待审批', exact: true }).click()
    const ownApproval = managerB.locator('.approval__card').filter({ hasText: purpose })
    await expect(ownApproval).toBeVisible()
    await ownApproval.getByRole('button', { name: '通过' }).click()
    const handoversResponsePromise = managerB.waitForResponse((response) =>
      new URL(response.url()).pathname === '/api/v2/reservations/handovers'
      && new URL(response.url()).searchParams.get('status') === 'PENDING',
    )
    await managerB.getByRole('menuitem', { name: '设备交接', exact: true }).click()
    const handoversResponse = await handoversResponsePromise
    const handoversBody = await handoversResponse.json()
    expect(handoversResponse.status(), JSON.stringify(handoversBody)).toBe(200)
    expect(
      handoversBody.data.items.map((item: { purpose: string }) => item.purpose),
      JSON.stringify(handoversBody),
    ).toContain(purpose)
    await expect(managerB.locator('.handover-card').filter({ hasText: purpose })).toBeVisible()

    await userA.getByRole('menuitem', { name: '我的预约', exact: true }).click()
    await expect(userA.locator('.mine__card').filter({ hasText: purpose })).toHaveCount(0)
    await expect(userA.getByRole('heading', { name: '暂无预约记录', exact: true })).toBeVisible()

    await login(systemAdmin, collegeA.admin_username, collegeA.password)
    await systemAdmin.getByRole('menuitem', { name: '设备管理', exact: true }).click()
    const systemSearch = systemAdmin.getByPlaceholder('按名称 / 品牌 / 型号检索')
    await systemSearch.fill(collegeB.device_name)
    await systemSearch.press('Enter')
    await expect(systemAdmin.locator('.el-table__row').filter({ has: systemAdmin.getByText(collegeB.device_name, { exact: true }) })).toBeVisible()
    await systemAdmin.screenshot({ path: testInfo.outputPath('system-admin-cross-college-device-management.png'), fullPage: true })

    await userAContext.close()
    await userBContext.close()
    await managerAContext.close()
    await managerBContext.close()
    await systemContext.close()
  })
})
