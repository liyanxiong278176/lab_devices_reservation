import { execFileSync } from 'node:child_process'
import { test, expect, type Page } from '@playwright/test'

type Fixture = {
  prefix: string
  username: string
  password: string
  device_name: string
}

const prefix = `e2e-${Date.now().toString(36)}`
let fixture: Fixture

function fixtureCommand(action: 'seed' | 'cleanup'): string {
  const output = execFileSync(
    'uv',
    ['run', 'python', 'scripts/e2e_fixture.py', action, '--prefix', prefix],
    {
      cwd: new URL('../../backend', import.meta.url),
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'inherit'],
    },
  )
  return output.trim()
}

async function login(page: Page, username: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/dashboard/)
  await expect(page.getByText('实验室预约系统')).toBeVisible()
}

async function chooseDateRange(page: Page, start: string, end: string) {
  const startInput = page.locator('input[placeholder="开始日期"]')
  await startInput.click()
  await startInput.fill(start)
  await page.keyboard.press('Enter')
  const endInput = page.locator('input[placeholder="结束日期"]')
  await endInput.fill(end)
  await page.keyboard.press('Enter')
}

test.describe.serial('普通用户与管理员真实页面完整链路', () => {
  test.beforeAll(() => {
    fixture = JSON.parse(fixtureCommand('seed')) as Fixture
  })

  test.afterAll(() => {
    fixtureCommand('cleanup')
  })

  test('预约审批、报修处理和菜单隔离均通过页面完成', async ({ browser }) => {
    const userContext = await browser.newContext()
    const userPage = await userContext.newPage()
    await login(userPage, fixture.username, fixture.password)

    for (const menu of ['仪表盘', 'AI 工作台', '设备', '我的预约', '我的通知', '提交报修', '我的报修']) {
      await expect(userPage.getByRole('menuitem', { name: menu, exact: true })).toBeVisible()
    }
    await expect(userPage.getByRole('menuitem', { name: '待审批', exact: true })).toHaveCount(0)
    await expect(userPage.getByRole('menuitem', { name: '设备管理', exact: true })).toHaveCount(0)
    await expect(userPage.getByRole('menuitem', { name: '用户管理', exact: true })).toHaveCount(0)

    await userPage.getByRole('menuitem', { name: '设备', exact: true }).click()
    const search = userPage.getByPlaceholder('搜索设备名称 / 型号')
    await search.fill(fixture.device_name)
    await search.press('Enter')
    await expect(userPage.getByText(fixture.device_name, { exact: true })).toBeVisible()
    await userPage.getByRole('button', { name: '预约' }).click()
    await expect(userPage.getByText('预约设备')).toBeVisible()

    const start = new Date()
    const end = new Date()
    const format = (value: Date) => {
      const year = value.getFullYear()
      const month = String(value.getMonth() + 1).padStart(2, '0')
      const day = String(value.getDate()).padStart(2, '0')
      return `${year}-${month}-${day}`
    }
    await chooseDateRange(userPage, format(start), format(end))
    await userPage.getByPlaceholder('例如：完成材料拉伸实验并采集三组数据').fill('E2E 页面预约审批链路')
    await expect(userPage.getByRole('button', { name: '提交预约' })).toBeEnabled()
    await userPage.getByRole('button', { name: '提交预约' }).click()
    await expect(userPage).toHaveURL(/reservations\/mine/)
    await expect(
      userPage.locator('.mine__card').filter({ hasText: 'E2E 页面预约审批链路' }).getByText('待审批'),
    ).toBeVisible()

    const adminContext = await browser.newContext()
    const adminPage = await adminContext.newPage()
    await login(adminPage, 'admin', 'admin123')
    for (const menu of ['仪表盘', 'AI 工作台', '设备', '待审批', '我的通知', '报修处理', '设备管理', '用户管理', '组织管理']) {
      await expect(adminPage.getByRole('menuitem', { name: menu, exact: true })).toBeVisible()
    }
    await adminPage.getByRole('menuitem', { name: '待审批', exact: true }).click()
    await expect(adminPage.getByText(fixture.device_name, { exact: true })).toBeVisible()
    const approvalCard = adminPage.locator('.approval__card').filter({ hasText: fixture.device_name })
    await approvalCard.getByRole('button', { name: '通过' }).click()
    await expect(approvalCard).toHaveCount(0)

    await userPage.reload()
    await expect(userPage.getByText('已通过')).toBeVisible()

    // 预约首日完成签到、归还验收，确认状态机不是停留在审批层。
    await userPage.getByRole('button', { name: '签到' }).click()
    await expect(userPage.getByText('使用中', { exact: true })).toBeVisible()
    await userPage.getByRole('button', { name: '归还' }).click()
    await expect(userPage.getByRole('dialog', { name: '归还验收' })).toBeVisible()
    await userPage.getByRole('button', { name: '确认归还' }).click()
    await expect(userPage.getByText('已完成', { exact: true })).toBeVisible()

    await userPage.getByRole('button', { name: '详情' }).click()
    await expect(userPage).toHaveURL(/reservations\/\d+/)
    await userPage.getByRole('button', { name: '评价设备' }).click()
    await expect(userPage.getByText('评价本次使用')).toBeVisible()
    await userPage.locator('textarea').last().fill('设备运行稳定，页面链路验收通过。')
    const feedbackResponsePromise = userPage.waitForResponse(
      (response) => response.url().includes('/feedback') && response.request().method() === 'POST',
    )
    await userPage.getByRole('button', { name: '提交评价' }).click()
    const feedbackResponse = await feedbackResponsePromise
    expect(feedbackResponse.status()).toBe(201)
    await expect(userPage.getByText(/使用评价/)).toBeVisible()

    // 页面级通知入口可打开，未读列表保留在当前页面并可执行已读操作。
    await userPage.getByRole('menuitem', { name: '我的通知', exact: true }).click()
    await expect(userPage.getByRole('heading', { name: '通知中心', exact: true })).toBeVisible()

    // 管理员端可以打开设备文档区域和预约规则入口。
    await adminPage.getByRole('menuitem', { name: '设备', exact: true }).click()
    await adminPage.getByText(fixture.device_name, { exact: true }).click()
    await adminPage.getByText('查看完整详情').click()
    await expect(adminPage.getByText('设备手册与操作规程')).toBeVisible()
    await adminPage.getByRole('button', { name: '上传文档' }).click()
    await adminPage.getByRole('dialog').getByLabel('标题').fill('E2E 设备操作规程')
    await adminPage.locator('input[type="file"]').setInputFiles({
      name: 'e2e-sop.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.7\nE2E SOP'),
    })
    await adminPage.getByRole('dialog').getByRole('button', { name: '上传' }).click()
    await expect(adminPage.getByText('E2E 设备操作规程')).toBeVisible()

    await adminPage.getByRole('menuitem', { name: '设备管理', exact: true }).click()
    await adminPage.getByRole('button', { name: '预约规则' }).click()
    await expect(adminPage.getByRole('heading', { name: '预约规则', exact: true })).toBeVisible()

    await userPage.getByRole('menuitem', { name: '提交报修', exact: true }).click()
    await expect(userPage.getByRole('heading', { name: '提交报修', exact: true })).toBeVisible()
    await userPage.locator('.rsubmit__el-form .el-select').click()
    await userPage.getByRole('option', { name: new RegExp(fixture.device_name) }).click()
    await userPage.getByPlaceholder('一句话描述故障').fill('E2E 设备故障')
    await userPage.getByPlaceholder('故障现象、复现步骤等').fill('用于验证普通用户提交、管理员处理和状态同步。')
    await userPage.getByRole('button', { name: '提交报修' }).click()
    await expect(userPage).toHaveURL(/repairs\/mine/)
    await expect(userPage.getByText('E2E 设备故障')).toBeVisible()

    await adminPage.getByRole('menuitem', { name: '报修处理', exact: true }).click()
    await expect(adminPage.getByText('E2E 设备故障')).toBeVisible()
    const repairRow = adminPage.locator('.el-table__row').filter({ hasText: 'E2E 设备故障' })
    await repairRow.getByRole('button', { name: '受理' }).click()
    await expect(repairRow.getByRole('button', { name: '解决' })).toBeVisible()
    await repairRow.getByRole('button', { name: '解决' }).click()
    await adminPage.getByPlaceholder('说明处理方式与结果(必填)').fill('E2E 页面链路处理完成。')
    await adminPage.getByRole('button', { name: '确认' }).click()
    await expect(repairRow.getByText('已解决')).toBeVisible()

    await userPage.reload()
    await expect(
      userPage
        .locator('.rmine__card')
        .filter({ hasText: 'E2E 设备故障' })
        .getByText('已解决', { exact: true })
        .first(),
    ).toBeVisible()
    await userContext.close()
    await adminContext.close()
  })
})
