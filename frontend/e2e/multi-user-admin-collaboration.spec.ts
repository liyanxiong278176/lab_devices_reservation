import { execFileSync } from 'node:child_process'
import { test, expect, type Page, type TestInfo } from '@playwright/test'

type Fixture = {
  username: string
  alternate_username: string
  password: string
  admin_username: string
  device_id: number
  device_name: string
}

const prefix = `e2e-multi-${Date.now().toString(36)}`
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

function dateAfter(days: number): string {
  const value = new Date()
  value.setDate(value.getDate() + days)
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

async function prepareBooking(page: Page, purpose: string, date: string) {
  await page.getByRole('menuitem', { name: '设备', exact: true }).click()
  const deviceCard = page.locator('.device-card').filter({
    has: page.getByText(fixture.device_name, { exact: true }),
  })
  await expect(deviceCard).toBeVisible()
  await deviceCard.getByRole('button', { name: '预约' }).click()
  await expect(page.getByRole('heading', { name: '预约设备', exact: true })).toBeVisible()

  const start = page.getByPlaceholder('开始日期')
  await start.fill(date)
  await start.press('Enter')
  const end = page.getByPlaceholder('结束日期')
  await end.fill(date)
  await end.press('Enter')
  await page.getByPlaceholder('例如：完成材料拉伸实验并采集三组数据').fill(purpose)
  await expect(page.locator('.preflight-summary')).toContainText('1 天可用')
  await expect(page.getByRole('button', { name: '提交预约' })).toBeEnabled()
}

async function capture(page: Page, testInfo: TestInfo, name: string) {
  const path = testInfo.outputPath(`${name}.png`)
  await page.screenshot({ path, fullPage: true, animations: 'disabled' })
  console.log(`PAGE_SCREENSHOT ${path}`)
}

test.describe.serial('多个普通用户与一个管理员的真实页面协作', () => {
  test.beforeAll(() => {
    fixture = JSON.parse(fixtureCommand('seed')) as Fixture
  })

  test.afterAll(() => {
    fixtureCommand('cleanup')
  })

  test('两个用户并发预约同一设备，管理员审批唯一成功申请', async ({ browser }, testInfo) => {
    test.setTimeout(150_000)
    const userOneContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    const userTwoContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    const adminContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    const userOne = await userOneContext.newPage()
    const userTwo = await userTwoContext.newPage()
    const admin = await adminContext.newPage()
    const pageErrors: string[] = []

    for (const page of [userOne, userTwo, admin]) {
      page.on('pageerror', (error) => pageErrors.push(error.message))
    }

    try {
      await Promise.all([
        login(userOne, fixture.username, fixture.password),
        login(userTwo, fixture.alternate_username, fixture.password),
        login(admin, fixture.admin_username, fixture.password),
      ])

      const reservationDate = dateAfter(3)
      const purposeOne = `并发预约申请 A ${prefix}`
      const purposeTwo = `并发预约申请 B ${prefix}`
      await Promise.all([
        prepareBooking(userOne, purposeOne, reservationDate),
        prepareBooking(userTwo, purposeTwo, reservationDate),
      ])
      await capture(userOne, testInfo, '01-user-one-ready-to-submit')
      await capture(userTwo, testInfo, '02-user-two-ready-to-submit')

      const reservationResponse = (page: Page) => page.waitForResponse((response) =>
        response.request().method() === 'POST'
        && new URL(response.url()).pathname === '/api/v2/reservations',
      )
      const responseOnePromise = reservationResponse(userOne)
      const responseTwoPromise = reservationResponse(userTwo)
      const submissions = Promise.all([
        userOne.getByRole('button', { name: '提交预约' }).click(),
        userTwo.getByRole('button', { name: '提交预约' }).click(),
      ])
      const [responseOne, responseTwo] = await Promise.all([
        responseOnePromise,
        responseTwoPromise,
      ])
      await submissions

      expect([responseOne.status(), responseTwo.status()].sort()).toEqual([201, 409])
      const winner = responseOne.status() === 201
        ? { page: userOne, purpose: purposeOne }
        : { page: userTwo, purpose: purposeTwo }
      const loser = responseOne.status() === 409
        ? { page: userOne, purpose: purposeOne }
        : { page: userTwo, purpose: purposeTwo }

      await expect(winner.page).toHaveURL(/reservations\/mine/)
      const winnerCard = winner.page.locator('.mine__card').filter({ hasText: winner.purpose })
      await expect(winnerCard).toBeVisible()
      await expect(winnerCard).toContainText('待审批')
      await expect(loser.page.locator('.el-message--error')).toContainText(
        /日期存在冲突|被其他用户占用/,
      )
      await capture(winner.page, testInfo, '03-winning-user-pending-reservation')

      await loser.page.goto(
        `/reservations/create?deviceId=${fixture.device_id}&startDate=${reservationDate}&endDate=${reservationDate}`,
      )
      await expect(loser.page.locator('.conflict-tip')).toBeVisible()
      await expect(loser.page.getByRole('button', { name: '提交预约' })).toBeDisabled()
      await capture(loser.page, testInfo, '04-losing-user-date-conflict')

      await admin.getByRole('menuitem', { name: '待审批', exact: true }).click()
      const approvalCard = admin.locator('.approval__card').filter({ hasText: winner.purpose })
      await expect(approvalCard).toBeVisible()
      await expect(admin.locator('.approval__card').filter({ hasText: loser.purpose })).toHaveCount(0)
      await capture(admin, testInfo, '05-admin-pending-approval')

      const approvalResponsePromise = admin.waitForResponse((response) =>
        response.request().method() === 'POST'
        && /\/api\/v2\/approvals\/\d+\/approve$/.test(new URL(response.url()).pathname),
      )
      await approvalCard.getByRole('button', { name: '通过' }).click()
      const approvalResponse = await approvalResponsePromise
      expect(approvalResponse.status(), await approvalResponse.text()).toBe(200)
      await expect(approvalCard).toHaveCount(0)

      await winner.page.reload()
      const approvedCard = winner.page.locator('.mine__card').filter({ hasText: winner.purpose })
      await expect(approvedCard.locator('.mine__card-head')).toContainText('已通过')
      await expect(loser.page.locator('.mine__card').filter({ hasText: winner.purpose })).toHaveCount(0)
      await capture(winner.page, testInfo, '06-winning-user-approved-reservation')
      await capture(admin, testInfo, '07-admin-approval-complete')

      expect(pageErrors).toEqual([])
    } finally {
      await Promise.all([
        userOneContext.close(),
        userTwoContext.close(),
        adminContext.close(),
      ])
    }
  })
})
