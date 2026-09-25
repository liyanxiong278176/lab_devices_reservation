import { execFileSync } from 'node:child_process'
import { test, expect, type Locator, type Page } from '@playwright/test'

type Fixture = {
  prefix: string
  username: string
  alternate_username: string
  password: string
  device_name: string
  second_device_id: number
  second_device_name: string
}

const samplePng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p1sAAAAASUVORK5CYII=',
  'base64',
)

let prefix = ''
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

function dateAfter(days: number): string {
  const value = new Date()
  value.setDate(value.getDate() + days)
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

async function attachEvidence(dialog: Locator, name: string) {
  await dialog.locator('input[type="file"]').setInputFiles({
    name,
    mimeType: 'image/png',
    buffer: samplePng,
  })
}

async function submitReservation(page: Page, deviceName: string, date: string, purpose: string) {
  await page.getByRole('menuitem', { name: '设备', exact: true }).click()
  const deviceCard = page.locator('.device-card').filter({ has: page.getByText(deviceName, { exact: true }) })
  await expect(deviceCard).toBeVisible()
  await deviceCard.getByRole('button', { name: '预约' }).click()
  await expect(page.getByRole('heading', { name: '预约设备' })).toBeVisible()
  await chooseDateRange(page, date, date)
  await page.getByPlaceholder('例如：完成材料拉伸实验并采集三组数据').fill(purpose)
  await expect(page.getByRole('button', { name: '提交预约' })).toBeEnabled()
  await page.getByRole('button', { name: '提交预约' }).click()
  await expect(page).toHaveURL(/reservations\/mine/)
  const reservationCard = page.locator('.mine__card').filter({ hasText: purpose })
  await expect(reservationCard).toBeVisible()
  return reservationCard
}

test.describe('普通用户与管理员真实页面完整链路', () => {
  test.beforeEach(() => {
    prefix = `e2e-${Date.now().toString(36)}`
    fixture = JSON.parse(fixtureCommand('seed')) as Fixture
  })

  test.afterEach(() => {
    fixtureCommand('cleanup')
  })

  test('预约审批、报修处理和菜单隔离均通过页面完成', async ({ browser }, testInfo) => {
    test.setTimeout(180_000)
    const userContext = await browser.newContext()
    const userPage = await userContext.newPage()
    await login(userPage, fixture.username, fixture.password)
    await expect(userPage.getByRole('heading', { name: '我的仪表盘', exact: true })).toBeVisible()

    for (const menu of ['仪表盘', 'AI 工作台', '设备', '我的预约', '我的通知', '提交报修', '我的报修']) {
      await expect(userPage.getByRole('menuitem', { name: menu, exact: true })).toBeVisible()
    }
    await expect(userPage.getByRole('menuitem', { name: '待审批', exact: true })).toHaveCount(0)
    await expect(userPage.getByRole('menuitem', { name: '设备管理', exact: true })).toHaveCount(0)
    await expect(userPage.getByRole('menuitem', { name: '用户管理', exact: true })).toHaveCount(0)

    await userPage.getByRole('menuitem', { name: '设备', exact: true }).click()
    await expect(userPage.locator('.segmented--vertical').first()).toBeVisible()
    const search = userPage.getByPlaceholder('搜索设备名称 / 型号')
    await search.fill(fixture.device_name)
    await search.press('Enter')
    await expect(userPage.getByText(fixture.device_name, { exact: true })).toBeVisible()
    const primaryDeviceCard = userPage.locator('.device-card').filter({ has: userPage.getByText(fixture.device_name, { exact: true }) })
    await primaryDeviceCard.getByRole('button', { name: '预约' }).click()
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
    for (const menu of ['仪表盘', 'AI 工作台', '设备', '待审批', '我的通知', '报修处理', '设备管理', '设备交接', '运营报表', '用户管理', '组织管理']) {
      await expect(adminPage.getByRole('menuitem', { name: menu, exact: true })).toBeVisible()
    }
    await expect(adminPage.getByRole('menuitem', { name: '设备交接', exact: true }).locator('svg')).toHaveCount(1)
    await expect(adminPage.getByRole('menuitem', { name: '运营报表', exact: true }).locator('svg')).toHaveCount(1)
    await adminPage.getByRole('menuitem', { name: '待审批', exact: true }).click()
    await expect(adminPage.getByText(fixture.device_name, { exact: true })).toBeVisible()
    const approvalCard = adminPage.locator('.approval__card').filter({ hasText: fixture.device_name })
    await approvalCard.getByRole('button', { name: '通过' }).click()
    await expect(approvalCard).toHaveCount(0)

    await userPage.reload()
    await expect(userPage.getByText('已通过')).toBeVisible()

    // 当前履约由管理员完成现场交接来启动使用；用户不能绕过交接直接签到。
    await expect(userPage.getByText('等待负责人交接')).toBeVisible()
    await expect(userPage.getByRole('button', { name: '签到' })).toHaveCount(0)
    await adminPage.getByRole('menuitem', { name: '设备交接', exact: true }).click()
    await expect(adminPage.getByRole('heading', { name: '设备交接', exact: true })).toBeVisible()
    const handoverSlider = adminPage.locator('.handover-page__filter .segmented__slider')
    const pendingSliderBox = await handoverSlider.boundingBox()
    await adminPage.getByRole('radio', { name: '待验收' }).click()
    await expect(adminPage.getByRole('radio', { name: '待验收' })).toHaveAttribute('aria-checked', 'true')
    expect(pendingSliderBox).not.toBeNull()
    await expect.poll(async () => (await handoverSlider.boundingBox())?.y ?? 0).toBeGreaterThan(pendingSliderBox!.y)
    await adminPage.getByRole('radio', { name: '待交接' }).click()
    const handoverCard = adminPage.locator('.handover-card').filter({ hasText: fixture.device_name })
    await expect(handoverCard).toBeVisible()
    await handoverCard.getByRole('button', { name: '核对并完成交接' }).click()
    const handoverDialog = adminPage.getByRole('dialog', { name: '完成设备交接' })
    await expect(handoverDialog).toBeVisible()
    await attachEvidence(handoverDialog, 'handover.png')
    const handoverResponsePromise = adminPage.waitForResponse((response) =>
      response.request().method() === 'POST'
      && /\/api\/v2\/reservations\/\d+\/handover$/.test(new URL(response.url()).pathname),
    )
    await handoverDialog.getByRole('button', { name: '确认' }).click()
    const handoverResponse = await handoverResponsePromise
    expect(handoverResponse.status(), await handoverResponse.text()).toBe(200)
    await expect(handoverCard).toHaveCount(0)

    // 用户归还后进入待验收；只有管理员确认验收，预约才显示完成。
    await userPage.reload()
    const inUseReservationCard = userPage.locator('.mine__card').filter({ hasText: 'E2E 页面预约审批链路' })
    await expect(inUseReservationCard.getByText('使用中', { exact: true })).toBeVisible()
    await userPage.getByRole('button', { name: '归还' }).click()
    const returnDialog = userPage.getByRole('dialog', { name: '提交归还' })
    await expect(returnDialog).toBeVisible()
    await attachEvidence(returnDialog, 'return.png')
    const returnResponsePromise = userPage.waitForResponse((response) =>
      response.request().method() === 'POST'
      && /\/api\/v2\/reservations\/\d+\/return$/.test(new URL(response.url()).pathname),
    )
    await returnDialog.getByRole('button', { name: '确认归还' }).click()
    const returnResponse = await returnResponsePromise
    const returnedReservation = await returnResponse.json()
    expect(returnResponse.status(), JSON.stringify(returnedReservation)).toBe(200)
    expect(returnedReservation.data.status, JSON.stringify(returnedReservation)).toBe('IN_USE')
    expect(returnedReservation.data.handover_status, JSON.stringify(returnedReservation)).toBe('RETURN_PENDING')
    await expect(inUseReservationCard.getByText('待负责人验收', { exact: true })).toBeVisible()
    const userAcceptanceFilterPromise = userPage.waitForResponse((response) =>
      new URL(response.url()).pathname === '/api/v2/reservations/mine'
      && new URL(response.url()).searchParams.get('handover_status') === 'RETURN_PENDING',
    )
    await userPage.getByRole('radio', { name: '待验收' }).click()
    const userAcceptanceResponse = await userAcceptanceFilterPromise
    expect(userAcceptanceResponse.status(), await userAcceptanceResponse.text()).toBe(200)
    await expect(inUseReservationCard).toBeVisible()
    const acceptanceQueuePromise = adminPage.waitForResponse((response) =>
      new URL(response.url()).pathname === '/api/v2/reservations/handovers'
      && new URL(response.url()).searchParams.get('status') === 'RETURN_PENDING',
    )
    await adminPage.getByRole('radio', { name: '待验收' }).click()
    const acceptanceQueueResponse = await acceptanceQueuePromise
    const acceptanceQueue = await acceptanceQueueResponse.json()
    expect(acceptanceQueueResponse.status(), JSON.stringify(acceptanceQueue)).toBe(200)
    expect(
      acceptanceQueue.data.items.map((item: { purpose: string }) => item.purpose),
      JSON.stringify(acceptanceQueue),
    ).toContain('E2E 页面预约审批链路')
    const acceptanceCard = adminPage.locator('.handover-card').filter({ hasText: fixture.device_name })
    await expect(acceptanceCard).toBeVisible()
    await acceptanceCard.getByRole('button', { name: '核对并确认验收' }).click()
    const acceptanceDialog = adminPage.getByRole('dialog', { name: '确认归还验收' })
    await expect(acceptanceDialog).toBeVisible()
    await expect(acceptanceDialog.getByText('打开照片')).toBeVisible()
    await acceptanceDialog.getByRole('button', { name: '确认' }).click()
    await expect(acceptanceCard).toHaveCount(0)
    await userPage.reload()
    await expect(userPage.getByText('已完成', { exact: true })).toBeVisible()
    await userPage.screenshot({ path: testInfo.outputPath('reservation-completed-user.png'), fullPage: true })
    await adminPage.screenshot({ path: testInfo.outputPath('handover-queue-completed-admin.png'), fullPage: true })

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

    // 验证未读点击后不消失、徽标减少、未读筛选准确、全部列表仍保留已读历史。
    await userPage.getByRole('menuitem', { name: '我的通知', exact: true }).click()
    await expect(userPage.getByRole('heading', { name: '通知中心', exact: true })).toBeVisible()
    await userPage.getByRole('radio', { name: '未读' }).click()
    const unreadRows = userPage.locator('.notif-row[data-read="unread"]')
    await expect(unreadRows.first()).toBeVisible()
    const unreadCountLabel = userPage.locator('.notif-overview__count strong')
    await expect.poll(async () => Number(await unreadCountLabel.innerText())).toBeGreaterThan(0)
    let lastUnreadCount = -1
    let stableUnreadSamples = 0
    await expect.poll(async () => {
      const currentCount = Number(await unreadCountLabel.innerText())
      if (currentCount === lastUnreadCount) stableUnreadSamples += 1
      else {
        lastUnreadCount = currentCount
        stableUnreadSamples = 0
      }
      return stableUnreadSamples
    }, { interval: 500, timeout: 15_000 }).toBeGreaterThanOrEqual(8)
    const unreadBefore = await userPage.evaluate(async () => {
      const auth = JSON.parse(sessionStorage.getItem('lab-user') || '{}') as { accessToken?: string }
      const response = await fetch('/api/v2/notifications/mine?onlyUnread=true&size=1', {
        headers: { Authorization: `Bearer ${auth.accessToken || ''}` },
      })
      const body = await response.json() as { data?: { total?: number } }
      return Number(body.data?.total ?? -1)
    })
    expect(Number(await unreadCountLabel.innerText()), '读取前页面未读徽标应与服务端一致').toBe(unreadBefore)
    const targetNotification = userPage.locator('.notif-row').first()
    const targetTitle = await targetNotification.locator('.notif-row__title').innerText()
    const unreadRefreshPromise = userPage.waitForResponse((response) => {
      const url = new URL(response.url())
      return response.request().method() === 'GET'
        && url.pathname.endsWith('/api/v2/notifications/mine')
        && url.searchParams.get('onlyUnread') === 'true'
        && url.searchParams.get('size') === '1'
    })
    await targetNotification.click()
    await expect(targetNotification).toHaveAttribute('data-read', 'read')
    const unreadRefresh = await unreadRefreshPromise
    const unreadRefreshBody = await unreadRefresh.json() as { data?: { total?: number } }
    const unreadAfterRead = Number(unreadRefreshBody.data?.total ?? -1)
    await expect.poll(async () => Number(await unreadCountLabel.innerText())).toBe(unreadAfterRead)
    expect(unreadAfterRead, '单条已读后未读总数应减少').toBeLessThan(unreadBefore)

    await userPage.getByRole('radio', { name: '全部' }).click()
    const readNotification = userPage.locator('.notif-row').filter({ hasText: targetTitle }).first()
    await expect(readNotification).toBeVisible()
    await expect(readNotification).toHaveAttribute('data-read', 'read')
    await userPage.screenshot({ path: testInfo.outputPath('notification-read-user.png'), fullPage: true })
    await userPage.getByRole('radio', { name: '未读' }).click()
    await expect(userPage.locator('.notif-row').filter({ hasText: targetTitle })).toHaveCount(0)
    await userPage.reload()
    await expect(userPage.getByRole('heading', { name: '通知中心', exact: true })).toBeVisible()
    const persistedReadNotification = userPage.locator('.notif-row').filter({ hasText: targetTitle }).first()
    await expect(persistedReadNotification).toBeVisible()
    await expect(persistedReadNotification).toHaveAttribute('data-read', 'read')
    await userPage.getByRole('radio', { name: '未读' }).click()
    await expect(userPage.locator('.notif-row').filter({ hasText: targetTitle })).toHaveCount(0)

    // 管理员端可以打开设备文档区域和预约规则入口。
    await adminPage.getByRole('menuitem', { name: '设备', exact: true }).click()
    await adminPage.getByText(fixture.device_name, { exact: true }).click()
    await adminPage.getByText('查看完整详情').click()
    await expect(adminPage.getByText('设备文档与安全须知')).toBeVisible()
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
    await userPage.getByRole('option', { name: new RegExp(`${fixture.device_name} ·`) }).click()
    await userPage.getByPlaceholder('一句话描述故障').fill('E2E 设备故障')
    await userPage.getByPlaceholder('故障现象、复现步骤等').fill('用于验证普通用户提交、管理员处理和状态同步。')
    await userPage.getByRole('button', { name: '提交报修' }).click()
    await expect(userPage).toHaveURL(/repairs\/mine/)
    await expect(userPage.getByText('E2E 设备故障')).toBeVisible()

    await adminPage.getByRole('menuitem', { name: '报修处理', exact: true }).click()
    await expect(adminPage.locator('.segmented--vertical').first()).toBeVisible()
    await expect(adminPage.getByText('E2E 设备故障')).toBeVisible()
    const repairRow = adminPage.locator('.el-table__row').filter({ hasText: 'E2E 设备故障' })
    await repairRow.getByRole('button', { name: '受理' }).click()
    await expect(repairRow.getByRole('button', { name: '解决' })).toBeVisible()
    await repairRow.getByRole('button', { name: '解决' }).click()
    await adminPage.getByPlaceholder('说明处理方式与结果(必填)').fill('E2E 页面链路处理完成。')
    await adminPage.locator('.radmin__drawer-actions').getByRole('button', { name: '确认处理', exact: true }).click()
    await expect(repairRow.getByText('待用户确认')).toBeVisible()

    await userPage.reload()
    const userRepairCard = userPage.locator('.rmine__card').filter({ hasText: 'E2E 设备故障' })
    await expect(userRepairCard.locator('.rmine__card-head').getByText('待用户确认', { exact: true })).toBeVisible()
    const confirmRepairAction = userRepairCard.getByText('确认已修复', { exact: true })
    await expect(confirmRepairAction).toBeVisible()
    await confirmRepairAction.click()
    await userPage.getByRole('dialog').getByRole('button', { name: '确认已修复' }).click()
    await expect(userRepairCard.locator('.rmine__card-head').getByText('已完成', { exact: true })).toBeVisible()
    await userContext.close()
    await adminContext.close()
  })

  test('驳回、取消与候补递补都能通过实际页面闭环', async ({ browser }, testInfo) => {
    test.setTimeout(180_000)
    const userContext = await browser.newContext()
    const userPage = await userContext.newPage()
    const alternatePage = await userContext.newPage()
    const adminContext = await browser.newContext()
    const adminPage = await adminContext.newPage()
    await login(userPage, fixture.username, fixture.password)
    await login(alternatePage, fixture.alternate_username, fixture.password)
    await login(adminPage, 'admin', 'admin123')

    const cancelDate = dateAfter(2)
    const cancelPurpose = 'E2E 页面取消与候补递补'
    const cancelCard = await submitReservation(userPage, fixture.device_name, cancelDate, cancelPurpose)
    await adminPage.getByRole('menuitem', { name: '待审批', exact: true }).click()
    const approvalCard = adminPage.locator('.approval__card').filter({ hasText: cancelPurpose })
    await expect(approvalCard).toBeVisible()
    await approvalCard.getByRole('button', { name: '通过' }).click()
    await expect(approvalCard).toHaveCount(0)

    // 第二位普通用户从设备详情的自然日占用表加入候补队列。
    await alternatePage.getByRole('menuitem', { name: '设备', exact: true }).click()
    const deviceCard = alternatePage.locator('.device-card').filter({ has: alternatePage.getByText(fixture.device_name, { exact: true }) })
    await deviceCard.click()
    await alternatePage.getByRole('button', { name: '查看完整详情' }).click()
    await alternatePage.getByRole('tab', { name: '预约日历' }).click()
    const occupiedDay = alternatePage.locator('.device-detail__cal-panel .el-table__row').filter({ hasText: cancelDate })
    await expect(occupiedDay).toBeVisible()
    await occupiedDay.getByRole('button', { name: '排队' }).click()
    await alternatePage.getByPlaceholder('请输入候补用途').fill('E2E 候补释放后重新预约')
    await alternatePage.getByRole('button', { name: '提交候补' }).click()
    await alternatePage.getByRole('menuitem', { name: '我的预约', exact: true }).click()
    const waitlistRow = alternatePage.locator('.mine__waitlist-row').filter({ hasText: cancelDate })
    await expect(waitlistRow).toBeVisible()
    await expect(waitlistRow).toContainText('候补中')

    await userPage.reload()
    await expect(cancelCard.getByRole('button', { name: '取消' })).toBeVisible()
    await cancelCard.getByRole('button', { name: '取消' }).click()
    await expect(userPage.getByRole('dialog')).toContainText('确认取消预约')
    await userPage.getByRole('dialog').getByRole('button', { name: '确认取消' }).click()
    await expect(cancelCard.getByText('已取消', { exact: true })).toBeVisible()

    // Outbox 异步递补后，队首获得 24 小时独占保留；用户确认后继续执行设备原审批规则。
    await expect.poll(async () => {
      await alternatePage.reload()
      const row = alternatePage.locator('.mine__waitlist-row').filter({ hasText: cancelDate })
      return await row.innerText().catch(() => '')
    }, { interval: 1200, timeout: 30_000 }).toContain('待确认保留')
    const notifiedWaitlistRow = alternatePage.locator('.mine__waitlist-row').filter({ hasText: cancelDate })
    await notifiedWaitlistRow.getByRole('button', { name: '确认预约' }).click()
    const confirmedWaitlistReservation = alternatePage.locator('.mine__card').filter({ hasText: 'E2E 候补释放后重新预约' })
    await expect(confirmedWaitlistReservation.getByText('待审批')).toBeVisible()

    // 驳回分支使用独立设备，避免前序候补释放/撤销事件影响可用性断言。
    const rejectDate = dateAfter(4)
    const rejectPurpose = 'E2E 页面预约驳回分支'
    const rejectedCard = await submitReservation(userPage, fixture.second_device_name, rejectDate, rejectPurpose)
    await adminPage.reload()
    await expect(adminPage.getByRole('heading', { name: '待审批', exact: true })).toBeVisible()
    const rejectedApproval = adminPage.locator('.approval__card').filter({ hasText: rejectPurpose })
    await expect(rejectedApproval).toBeVisible()
    await rejectedApproval.getByRole('button', { name: '驳回' }).click()
    await adminPage.getByPlaceholder('请填写驳回理由，将通知申请人').fill('测试设备用途说明不完整')
    await adminPage.getByRole('button', { name: '确认驳回' }).click()
    await expect(rejectedApproval).toHaveCount(0)
    await userPage.reload()
    await expect(rejectedCard.getByText('已拒绝', { exact: true })).toBeVisible()

    await userPage.screenshot({ path: testInfo.outputPath('reservation-rejected-and-cancelled-user.png'), fullPage: true })
    await alternatePage.screenshot({ path: testInfo.outputPath('waitlist-notified-user.png'), fullPage: true })
    await userContext.close()
    await adminContext.close()
  })

  test('报修被退回后可重新处理，管理员驳回分支也可闭环', async ({ browser }) => {
    test.setTimeout(180_000)
    const userContext = await browser.newContext()
    const userPage = await userContext.newPage()
    const adminContext = await browser.newContext()
    const adminPage = await adminContext.newPage()
    await login(userPage, fixture.username, fixture.password)
    await login(adminPage, 'admin', 'admin123')

    const reworkTitle = 'E2E 报修退回后重新处理'
    await userPage.getByRole('menuitem', { name: '提交报修', exact: true }).click()
    await userPage.locator('.rsubmit__el-form .el-select').click()
    await userPage.getByRole('option', { name: new RegExp(fixture.second_device_name) }).click()
    await userPage.getByPlaceholder('一句话描述故障').fill(reworkTitle)
    await userPage.getByPlaceholder('故障现象、复现步骤等').fill('先模拟修复不完整，再退回管理员重新处理。')
    await userPage.getByRole('button', { name: '提交报修' }).click()
    await expect(userPage).toHaveURL(/repairs\/mine/)
    await expect(userPage.locator('.rmine__card').filter({ hasText: reworkTitle })).toBeVisible()

    await adminPage.getByRole('menuitem', { name: '报修处理', exact: true }).click()
    let repairRow = adminPage.locator('.el-table__row').filter({ hasText: reworkTitle })
    await expect(repairRow).toBeVisible()
    await repairRow.getByRole('button', { name: '受理' }).click()
    await repairRow.getByRole('button', { name: '解决' }).click()
    await adminPage.getByPlaceholder('说明处理方式与结果(必填)').fill('第一次处理，等待用户复核。')
    await adminPage.locator('.radmin__drawer-actions').getByRole('button', { name: '确认处理', exact: true }).click()
    await expect(adminPage.locator('.radmin__drawer')).toBeHidden()

    await userPage.reload()
    let userRepairCard = userPage.locator('.rmine__card').filter({ hasText: reworkTitle })
    await userRepairCard.getByText('退回处理', { exact: true }).click()
    const returnRepairDialog = userPage.getByRole('dialog')
    await returnRepairDialog.getByPlaceholder('例如：设备仍然无法开机').fill('复测后发现故障仍然存在')
    await returnRepairDialog.getByRole('button', { name: '退回处理' }).click()
    await expect(userRepairCard.locator('.rmine__card-head').getByText('处理中', { exact: true })).toBeVisible()

    await adminPage.reload()
    repairRow = adminPage.locator('.el-table__row').filter({ hasText: reworkTitle })
    await expect(repairRow.getByRole('button', { name: '解决' })).toBeVisible()
    await repairRow.getByRole('button', { name: '解决' }).click()
    await adminPage.getByPlaceholder('说明处理方式与结果(必填)').fill('第二次处理完成并复测通过。')
    const secondResolveResponsePromise = adminPage.waitForResponse((response) =>
      response.request().method() === 'POST'
      && /\/api\/v2\/repair-reports\/\d+\/resolve$/.test(new URL(response.url()).pathname),
    )
    await adminPage.locator('.radmin__drawer-actions').getByRole('button', { name: '确认处理', exact: true }).click()
    const secondResolveResponse = await secondResolveResponsePromise
    expect(secondResolveResponse.status(), await secondResolveResponse.text()).toBe(200)
    await expect(adminPage.locator('.radmin__drawer')).toBeHidden()
    await expect(repairRow).toContainText('待用户确认')
    await userPage.reload()
    userRepairCard = userPage.locator('.rmine__card').filter({ hasText: reworkTitle })
    await expect(userRepairCard.getByText('确认已修复', { exact: true })).toBeVisible()
    await userRepairCard.getByText('确认已修复', { exact: true }).click()
    await userPage.getByRole('dialog').getByRole('button', { name: '确认已修复' }).click()
    await expect(userRepairCard.locator('.rmine__card-head').getByText('已完成', { exact: true })).toBeVisible()

    const rejectedTitle = 'E2E 报修驳回分支'
    await userPage.getByRole('menuitem', { name: '提交报修', exact: true }).click()
    await userPage.locator('.rsubmit__el-form .el-select').click()
    await userPage.getByRole('option', { name: new RegExp(`${fixture.device_name} ·`) }).click()
    await userPage.getByPlaceholder('一句话描述故障').fill(rejectedTitle)
    await userPage.getByRole('button', { name: '提交报修' }).click()
    await adminPage.reload()
    repairRow = adminPage.locator('.el-table__row').filter({ hasText: rejectedTitle })
    await expect(repairRow).toBeVisible()
    await repairRow.getByRole('button', { name: '驳回' }).click()
    await adminPage.getByPlaceholder('说明驳回原因(必填)').fill('未能复现该故障，请补充信息')
    await adminPage.locator('.radmin__drawer-actions').getByRole('button', { name: '确认处理', exact: true }).click()
    await userPage.reload()
    const rejectedRepair = userPage.locator('.rmine__card').filter({ hasText: rejectedTitle })
    await expect(rejectedRepair.locator('.rmine__card-head').getByText('已驳回', { exact: true })).toBeVisible()

    await userContext.close()
    await adminContext.close()
  })

  test('管理员可驳回待受理报修，用户端可查看驳回状态', async ({ browser }, testInfo) => {
    const userContext = await browser.newContext()
    const userPage = await userContext.newPage()
    const adminContext = await browser.newContext()
    const adminPage = await adminContext.newPage()
    await login(userPage, fixture.username, fixture.password)
    await login(adminPage, 'admin', 'admin123')

    const rejectedTitle = 'E2E 管理员驳回报修'
    await userPage.getByRole('menuitem', { name: '提交报修', exact: true }).click()
    await userPage.locator('.rsubmit__el-form .el-select').click()
    await userPage.getByRole('option', { name: new RegExp(`${fixture.device_name} ·`) }).click()
    await userPage.getByPlaceholder('一句话描述故障').fill(rejectedTitle)
    await userPage.getByPlaceholder('故障现象、复现步骤等').fill('用于独立验证管理员驳回分支。')
    await userPage.getByRole('button', { name: '提交报修' }).click()
    await expect(userPage).toHaveURL(/repairs\/mine/)
    await expect(userPage.locator('.rmine__card').filter({ hasText: rejectedTitle })).toBeVisible()

    await adminPage.getByRole('menuitem', { name: '报修处理', exact: true }).click()
    const repairRow = adminPage.locator('.el-table__row').filter({ hasText: rejectedTitle })
    await expect(repairRow).toBeVisible()
    await expect(repairRow.getByRole('button', { name: '驳回' })).toBeVisible()
    await repairRow.getByRole('button', { name: '驳回' }).click()
    await adminPage.getByPlaceholder('说明驳回原因(必填)').fill('未能复现故障，请补充现场信息。')
    const rejectResponsePromise = adminPage.waitForResponse((response) =>
      response.request().method() === 'POST'
      && /\/api\/v2\/repair-reports\/\d+\/reject$/.test(new URL(response.url()).pathname),
    )
    await adminPage.locator('.radmin__drawer-actions').getByRole('button', { name: '确认处理', exact: true }).click()
    const rejectResponse = await rejectResponsePromise
    expect(rejectResponse.status(), await rejectResponse.text()).toBe(200)
    await expect(adminPage.locator('.radmin__drawer')).toBeHidden()
    await expect(repairRow).toContainText('已驳回')

    await userPage.reload()
    const rejectedCard = userPage.locator('.rmine__card').filter({ hasText: rejectedTitle })
    await expect(rejectedCard.locator('.rmine__card-head').getByText('已驳回', { exact: true })).toBeVisible()
    await userPage.screenshot({ path: testInfo.outputPath('repair-rejected-user.png'), fullPage: true })
    await adminPage.screenshot({ path: testInfo.outputPath('repair-rejected-admin.png'), fullPage: true })
    await userContext.close()
    await adminContext.close()
  })

  test('损坏归还验收会完成预约并将设备转入维护状态', async ({ browser }, testInfo) => {
    test.setTimeout(150_000)
    const userContext = await browser.newContext()
    const userPage = await userContext.newPage()
    const adminContext = await browser.newContext()
    const adminPage = await adminContext.newPage()
    await login(userPage, fixture.username, fixture.password)
    await login(adminPage, 'admin', 'admin123')

    const purpose = 'E2E 损坏设备交接与验收'
    const reservationCard = await submitReservation(userPage, fixture.second_device_name, dateAfter(0), purpose)
    await adminPage.getByRole('menuitem', { name: '待审批', exact: true }).click()
    const approvalCard = adminPage.locator('.approval__card').filter({ hasText: fixture.second_device_name })
    await expect(approvalCard).toBeVisible()
    const approvalResponsePromise = adminPage.waitForResponse((response) =>
      response.request().method() === 'POST'
      && /\/api\/v2\/approvals\/\d+\/approve$/.test(new URL(response.url()).pathname),
    )
    await approvalCard.getByRole('button', { name: '通过' }).click()
    const approvalResponse = await approvalResponsePromise
    expect(approvalResponse.status(), await approvalResponse.text()).toBe(200)
    await expect(approvalCard).toHaveCount(0)

    await adminPage.getByRole('menuitem', { name: '设备交接', exact: true }).click()
    let handoverCard = adminPage.locator('.handover-card').filter({ hasText: fixture.second_device_name })
    await expect(handoverCard.getByRole('button', { name: '核对并完成交接' })).toBeEnabled()
    await handoverCard.getByRole('button', { name: '核对并完成交接' }).click()
    const normalHandoverDialog = adminPage.getByRole('dialog', { name: '完成设备交接' })
    await attachEvidence(normalHandoverDialog, 'handover-damaged-test.png')
    const handoverResponsePromise = adminPage.waitForResponse((response) =>
      response.request().method() === 'POST'
      && /\/api\/v2\/reservations\/\d+\/handover$/.test(new URL(response.url()).pathname),
    )
    await normalHandoverDialog.getByRole('button', { name: '确认' }).click()
    const handoverResponse = await handoverResponsePromise
    expect(handoverResponse.status(), await handoverResponse.text()).toBe(200)

    await userPage.reload()
    const inUseCard = userPage.locator('.mine__card').filter({ hasText: purpose })
    await expect(inUseCard.getByText('使用中', { exact: true })).toBeVisible()
    await inUseCard.getByRole('button', { name: '归还' }).click()
    const returnDialog = userPage.getByRole('dialog', { name: '提交归还' })
    await returnDialog.locator('label.el-radio').filter({ hasText: '发现损坏' }).click()
    await returnDialog.getByPlaceholder('补充验收备注（可选）').fill('E2E 检测到设备异常，需停用检修。')
    await attachEvidence(returnDialog, 'return-damaged.png')
    const damagedReturnResponsePromise = userPage.waitForResponse((response) =>
      response.request().method() === 'POST'
      && /\/api\/v2\/reservations\/\d+\/return$/.test(new URL(response.url()).pathname),
    )
    await returnDialog.getByRole('button', { name: '确认归还' }).click()
    const damagedReturnResponse = await damagedReturnResponsePromise
    const damagedReturn = await damagedReturnResponse.json()
    expect(damagedReturnResponse.status(), JSON.stringify(damagedReturn)).toBe(200)
    expect(damagedReturn.data.status, JSON.stringify(damagedReturn)).toBe('IN_USE')

    const damagedAcceptanceQueuePromise = adminPage.waitForResponse((response) =>
      new URL(response.url()).pathname === '/api/v2/reservations/handovers'
      && new URL(response.url()).searchParams.get('status') === 'RETURN_PENDING',
    )
    await adminPage.getByRole('radio', { name: '待验收' }).click()
    const damagedAcceptanceQueueResponse = await damagedAcceptanceQueuePromise
    const damagedAcceptanceQueue = await damagedAcceptanceQueueResponse.json()
    expect(damagedAcceptanceQueueResponse.status(), JSON.stringify(damagedAcceptanceQueue)).toBe(200)
    expect(
      damagedAcceptanceQueue.data.items.map((item: { purpose: string }) => item.purpose),
      JSON.stringify(damagedAcceptanceQueue),
    ).toContain(purpose)
    const acceptanceCard = adminPage.locator('.handover-card').filter({ hasText: fixture.second_device_name })
    await expect(acceptanceCard).toBeVisible()
    await acceptanceCard.getByRole('button', { name: '核对并确认验收' }).click()
    const acceptanceDialog = adminPage.getByRole('dialog', { name: '确认归还验收' })
    await acceptanceDialog.locator('label.el-radio').filter({ hasText: '发现损坏' }).click()
    await acceptanceDialog.getByPlaceholder('补充交接或验收说明').fill('确认外壳破损，设备进入维护。')
    await expect(acceptanceDialog.getByText('打开照片')).toBeVisible()
    await acceptanceDialog.getByRole('button', { name: '确认' }).click()
    await expect(acceptanceCard).toHaveCount(0)

    await userPage.reload()
    await expect(reservationCard.getByText('已完成', { exact: true })).toBeVisible()
    await adminPage.getByRole('menuitem', { name: '设备管理', exact: true }).click()
    const deviceSearch = adminPage.getByPlaceholder('按名称 / 品牌 / 型号检索')
    await deviceSearch.fill(fixture.second_device_name)
    await deviceSearch.press('Enter')
    const deviceRow = adminPage.locator('.el-table__row').filter({ hasText: fixture.second_device_name })
    await expect(deviceRow).toContainText('维护中')
    await userPage.screenshot({ path: testInfo.outputPath('damaged-return-completed-user.png'), fullPage: true })
    await adminPage.screenshot({ path: testInfo.outputPath('damaged-device-maintenance-admin.png'), fullPage: true })

    await userContext.close()
    await adminContext.close()
  })

  test('交接发现配件损坏会阻止启用、生成报修并等待负责人处置', async ({ browser }) => {
    test.setTimeout(150_000)
    const userContext = await browser.newContext()
    const userPage = await userContext.newPage()
    const adminContext = await browser.newContext()
    const adminPage = await adminContext.newPage()
    await login(userPage, fixture.username, fixture.password)
    await login(adminPage, 'admin', 'admin123')

    const purpose = 'E2E 交接配件异常处置'
    const reservationCard = await submitReservation(
      userPage,
      fixture.second_device_name,
      dateAfter(0),
      purpose,
    )
    await adminPage.getByRole('menuitem', { name: '待审批', exact: true }).click()
    const approvalCard = adminPage.locator('.approval__card').filter({ hasText: purpose })
    await expect(approvalCard).toBeVisible()
    const approvalResponsePromise = adminPage.waitForResponse((response) =>
      response.request().method() === 'POST'
      && /\/api\/v2\/approvals\/\d+\/approve$/.test(new URL(response.url()).pathname),
    )
    await approvalCard.getByRole('button', { name: '通过' }).click()
    const approvalResponse = await approvalResponsePromise
    expect(approvalResponse.status(), await approvalResponse.text()).toBe(200)
    await expect(approvalCard).toHaveCount(0)

    await adminPage.getByRole('menuitem', { name: '设备交接', exact: true }).click()
    const handoverCard = adminPage.locator('.handover-card').filter({ hasText: purpose })
    await handoverCard.getByRole('button', { name: '核对并完成交接' }).click()
    const dialog = adminPage.getByRole('dialog', { name: '完成设备交接' })
    await attachEvidence(dialog, 'accessory-damage.png')
    await dialog.locator('.handover-dialog__check .el-select').click()
    await adminPage.getByRole('option', { name: '损坏', exact: true }).click()
    const handoverResponsePromise = adminPage.waitForResponse((response) =>
      response.request().method() === 'POST'
      && /\/api\/v2\/reservations\/\d+\/handover$/.test(new URL(response.url()).pathname),
    )
    await dialog.getByRole('button', { name: '确认' }).click()
    const handoverResponse = await handoverResponsePromise
    expect(handoverResponse.status(), await handoverResponse.text()).toBe(200)
    await expect(adminPage.getByText('已记录交接异常，设备已转维修并生成关联工单')).toBeVisible()

    await adminPage.getByRole('radio', { name: '交接异常' }).click()
    const exceptionCard = adminPage.locator('.handover-card').filter({ hasText: purpose })
    await expect(exceptionCard).toContainText('关联报修单：#')
    await expect(exceptionCard.getByRole('button', { name: '取消预约并释放日期' })).toBeVisible()
    await exceptionCard.getByRole('button', { name: '取消预约并释放日期' }).click()
    await adminPage.getByRole('button', { name: '取消预约', exact: true }).click()
    await expect(exceptionCard).toHaveCount(0)

    await userPage.reload()
    await expect(reservationCard.getByText('已取消', { exact: true })).toBeVisible()
    await adminPage.getByRole('menuitem', { name: '设备管理', exact: true }).click()
    const deviceSearch = adminPage.getByPlaceholder('按名称 / 品牌 / 型号检索')
    await deviceSearch.fill(fixture.second_device_name)
    await deviceSearch.press('Enter')
    await expect(
      adminPage.locator('.el-table__row').filter({ hasText: fixture.second_device_name }),
    ).toContainText('维护中')

    await adminPage.getByRole('menuitem', { name: '报修处理', exact: true }).click()
    await expect(adminPage.getByText(/交接异常/)).toBeVisible()
    await userContext.close()
    await adminContext.close()
  })
})
