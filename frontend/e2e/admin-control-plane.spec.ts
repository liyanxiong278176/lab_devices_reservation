import { execFileSync } from 'node:child_process'
import { test, expect, type Page } from '@playwright/test'

type Fixture = {
  prefix: string
  username: string
  password: string
  admin_username: string
  manager_username: string
  device_name: string
  college_id: number
}

const prefix = `e2e-${Date.now().toString(36)}`
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

test.describe('管理员管理页与运营工具真实页面验收', () => {
  test.beforeAll(() => {
    fixture = JSON.parse(fixtureCommand('seed')) as Fixture
  })

  test.afterAll(() => {
    fixtureCommand('cleanup')
  })

  test('管理员菜单页面正常显示，设备、用户和实验室 CRUD 可闭环', async ({ browser }, testInfo) => {
    test.setTimeout(150_000)
    const context = await browser.newContext()
    const page = await context.newPage()
    await page.addInitScript(() => {
      const key = '__adminControlWindowErrors'
      window.addEventListener('error', (event) => {
        const error = event as ErrorEvent
        const previous = JSON.parse(sessionStorage.getItem(key) || '[]') as string[]
        previous.push(`${error.message} (${location.pathname})`)
        sessionStorage.setItem(key, JSON.stringify(previous))
      })
    })
    const invalidNumberProps: string[] = []
    page.on('console', (message) => {
      if (
        message.type() === 'warning'
        && /Invalid prop: type check failed for prop "modelValue"\. Expected Number \| Null, got String/.test(message.text())
      ) {
        invalidNumberProps.push(message.text())
      }
    })
    await login(page, fixture.admin_username, fixture.password)
    await expect(page.getByRole('heading', { name: '仪表盘', exact: true })).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('admin-dashboard.png'), fullPage: true })

    const pageChecks: Array<[string, string]> = [
      ['设备', '设备浏览'],
      ['待审批', '待审批'],
      ['我的通知', '通知中心'],
      ['报修处理', '报修管理'],
      ['设备交接', '设备交接'],
      ['运营报表', '运营报表'],
      ['用户管理', '用户管理'],
      ['组织管理', '组织管理'],
    ]
    for (const [menu, heading] of pageChecks) {
      await page.getByRole('menuitem', { name: menu, exact: true }).click()
      await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
    }

    await page.getByRole('menuitem', { name: '设备管理', exact: true }).click()
    await expect(page.getByRole('heading', { name: '设备管理', exact: true })).toBeVisible()
    const createdDeviceName = `${prefix}-crud-device`
    await page.getByRole('button', { name: '新增设备' }).click()
    const deviceDrawer = page.locator('.dmanage-drawer')
    await expect(deviceDrawer).toBeVisible()
    expect(invalidNumberProps, '数字输入框的 v-model 不能使用字符串占位').toEqual([])
    await deviceDrawer.getByRole('textbox', { name: /名称/ }).fill(createdDeviceName)
    await deviceDrawer.getByRole('combobox', { name: /分类/ }).click()
    const categoryNode = page.locator('.el-tree-node__content:visible').last()
    await expect(categoryNode).toBeVisible()
    await categoryNode.click()
    await deviceDrawer.getByRole('combobox', { name: /实验室/ }).click()
    await page.getByRole('option', { name: `${prefix}-lab`, exact: true }).click()
    await deviceDrawer.locator('.el-form-item').filter({ hasText: '型号' }).locator('input').fill('CRUD-E2E')
    await deviceDrawer.getByRole('button', { name: '保存' }).click()
    const deviceSearch = page.getByPlaceholder('按名称 / 品牌 / 型号检索')
    await deviceSearch.fill(createdDeviceName)
    await deviceSearch.press('Enter')
    let deviceRow = page.locator('.el-table__row').filter({ hasText: createdDeviceName })
    await expect(deviceRow).toBeVisible()
    await expect(deviceRow).toContainText('空闲')

    // 状态下拉经过页面请求更新，并恢复为空闲，保证测试数据后续可复用。
    await deviceRow.getByText('空闲').click()
    await page.getByRole('menuitem', { name: '维护中', exact: true }).click()
    await expect(deviceRow).toContainText('维护中')
    await deviceRow.getByText('维护中').click()
    await page.getByRole('menuitem', { name: '空闲', exact: true }).click()
    await expect(deviceRow).toContainText('空闲')

    const updatedDeviceName = `${createdDeviceName}-edited`
    await deviceRow.getByRole('button', { name: '编辑' }).click()
    await deviceDrawer.getByRole('textbox', { name: /名称/ }).fill(updatedDeviceName)
    const updateResponsePromise = page.waitForResponse((response) =>
      response.request().method() === 'PUT' && /\/api\/v2\/devices\/\d+$/.test(response.url()),
    )
    await deviceDrawer.getByRole('button', { name: '保存' }).click()
    const updateResponse = await updateResponsePromise
    expect(updateResponse.status()).toBe(200)
    expect(await updateResponse.text()).toContain(updatedDeviceName)
    await deviceSearch.fill(updatedDeviceName)
    const filteredListResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return response.request().method() === 'GET'
        && url.pathname.endsWith('/api/v2/devices')
        && url.searchParams.get('search') === updatedDeviceName
    })
    await deviceSearch.press('Enter')
    const filteredListResponse = await filteredListResponsePromise
    expect(filteredListResponse.status()).toBe(200)
    expect(await filteredListResponse.text()).toContain(updatedDeviceName)
    deviceRow = page.locator('.el-table__row').filter({ hasText: updatedDeviceName })
    await expect(deviceRow).toBeVisible()
    const deleteResponsePromise = page.waitForResponse((response) =>
      response.request().method() === 'DELETE' && /\/api\/v2\/devices\/\d+$/.test(response.url()),
    )
    await deviceRow.getByRole('button', { name: '删除' }).click()
    await page.locator('.el-message-box__btns').getByRole('button', { name: '删除' }).click()
    const deleteResponse = await deleteResponsePromise
    expect(deleteResponse.status()).toBe(200)
    await expect(deviceRow, '删除成功后列表应立即移除该设备').toHaveCount(0)
    await page.reload()
    await expect(page.getByRole('heading', { name: '设备管理', exact: true })).toBeVisible()
    await deviceSearch.fill(updatedDeviceName)
    const deletedListResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return response.request().method() === 'GET'
        && url.pathname.endsWith('/api/v2/devices')
        && url.searchParams.get('search') === updatedDeviceName
    })
    await deviceSearch.press('Enter')
    const deletedListResponse = await deletedListResponsePromise
    expect(deletedListResponse.status()).toBe(200)
    deviceRow = page.locator('.el-table__row').filter({ hasText: updatedDeviceName })
    await expect(deviceRow).toHaveCount(0)

    await page.getByRole('menuitem', { name: '用户管理', exact: true }).click()
    const newUsername = `${prefix}-crud-user`
    await page.getByRole('button', { name: '新增用户' }).click()
    const userDrawer = page.locator('.umanage-drawer')
    const userField = (label: string) => userDrawer.locator('.el-form-item').filter({ hasText: label }).locator('input').first()
    await userField('用户名').fill(newUsername)
    await userField('密码').fill('E2e-User-123')
    await userField('姓名').fill('E2E CRUD 用户')
    const collegeSelect = userDrawer.locator('.el-form-item').filter({ hasText: '所属学院' }).locator('.el-select')
    await collegeSelect.click()
    await page.getByRole('option', { name: new RegExp(`E2E 测试学院 ${prefix}`) }).click()
    const rolesSelect = userDrawer.locator('.el-form-item').filter({ hasText: '角色' }).locator('.el-select')
    await rolesSelect.click()
    await page.getByRole('option', { name: '学生', exact: true }).click()
    await rolesSelect.click()
    await userDrawer.getByRole('button', { name: '保存' }).click()

    const usernameSearch = page.getByPlaceholder('用户名')
    await usernameSearch.fill(newUsername)
    await page.getByRole('button', { name: '查询' }).click()
    let userRow = page.locator('.el-table__row').filter({ hasText: newUsername })
    await expect(userRow).toBeVisible()
    await expect(userRow).toContainText('学生')
    await userRow.getByRole('button', { name: '编辑' }).click()
    await userField('姓名').fill('E2E CRUD 用户已更新')
    await userDrawer.getByRole('button', { name: '保存' }).click()
    userRow = page.locator('.el-table__row').filter({ hasText: newUsername })
    await expect(userRow, '用户资料更新后列表应立即显示新姓名').toContainText('E2E CRUD 用户已更新')
    await page.reload()
    await expect(page.getByRole('heading', { name: '用户管理', exact: true })).toBeVisible()
    await usernameSearch.fill(newUsername)
    await page.getByRole('button', { name: '查询' }).click()
    userRow = page.locator('.el-table__row').filter({ hasText: newUsername })
    await expect(userRow).toContainText('E2E CRUD 用户已更新')

    await userRow.getByRole('button', { name: '停用账号' }).click()
    await page.locator('.el-message-box__btns').getByRole('button', { name: '停用' }).click()
    await expect(userRow.locator('td').nth(2)).toContainText('禁用')
    await expect(userRow.getByRole('button', { name: '启用账号' })).toBeVisible()
    await userRow.getByRole('button', { name: '启用账号' }).click()
    await page.locator('.el-message-box__btns').getByRole('button', { name: '确认' }).click()
    await expect(userRow.getByRole('button', { name: '停用账号' })).toBeVisible()
    const deleteUserResponsePromise = page.waitForResponse((response) =>
      response.request().method() === 'DELETE' && /\/api\/v2\/users\/\d+$/.test(response.url()),
    )
    await userRow.getByRole('button', { name: '停用账号' }).click()
    await page.locator('.el-message-box__btns').getByRole('button', { name: '停用' }).click()
    expect((await deleteUserResponsePromise).status()).toBe(200)
    await expect(userRow.locator('td').nth(2), '删除操作后列表应立即反映账号状态').toContainText('禁用')
    await page.reload()
    await expect(page.getByRole('heading', { name: '用户管理', exact: true })).toBeVisible()
    await usernameSearch.fill(newUsername)
    await page.getByRole('button', { name: '查询' }).click()
    await expect(userRow.locator('td').nth(2)).toContainText('禁用')

    // 组织管理创建并更新该测试学院下的实验室；fixture 清理会按学院级联清除。
    await page.getByRole('menuitem', { name: '组织管理', exact: true }).click()
    await page.getByRole('tab', { name: '实验室配置' }).click()
    await page.getByRole('button', { name: '新增实验室' }).click()
    const labDrawer = page.locator('.organization-drawer')
    const labCollege = labDrawer.locator('.el-form-item').filter({ hasText: '所属学院' }).locator('.el-select')
    await labCollege.click()
    await page.getByRole('option', { name: `E2E 测试学院 ${prefix}`, exact: true }).click()
    const createdLabName = `${prefix}-crud-lab`
    await labDrawer.locator('.el-form-item').filter({ hasText: '实验室名称' }).locator('input').fill(createdLabName)
    await labDrawer.locator('.el-form-item').filter({ hasText: '位置' }).locator('input').fill('E2E 旧位置')
    await labDrawer.getByRole('button', { name: '保存配置' }).click()
    let labRow = page.locator('.el-table__row').filter({ hasText: createdLabName })
    await expect(labRow).toBeVisible()
    await expect(labRow).toContainText('E2E 旧位置')
    await labRow.getByRole('button', { name: '编辑' }).click()
    await labDrawer.locator('.el-form-item').filter({ hasText: '位置' }).locator('input').fill('E2E 新位置')
    await labDrawer.getByRole('button', { name: '保存配置' }).click()
    labRow = page.locator('.el-table__row').filter({ hasText: createdLabName })
    await expect(labRow).toContainText('E2E 新位置')
    await expect(labDrawer).toBeHidden()
    await expect(page.locator('.el-message')).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('organization-lab-management.png'), fullPage: true })
    const windowErrors = await page.evaluate(() =>
      JSON.parse(sessionStorage.getItem('__adminControlWindowErrors') || '[]') as string[],
    )
    expect(windowErrors, '管理员组织管理的保存与刷新过程中不能产生浏览器全局错误').toEqual([])
    await context.close()
  })

  test('不可预约日期会阻止用户提交，解除后恢复预约；同步与异步报表可下载', async ({ browser }, testInfo) => {
    test.setTimeout(180_000)
    const adminContext = await browser.newContext()
    const adminPage = await adminContext.newPage()
    const userContext = await browser.newContext()
    const userPage = await userContext.newPage()
    await login(adminPage, fixture.admin_username, fixture.password)
    await login(userPage, fixture.username, fixture.password)

    await adminPage.getByRole('menuitem', { name: '设备管理', exact: true }).click()
    await adminPage.getByRole('button', { name: '预约规则' }).click()
    await expect(adminPage.getByRole('heading', { name: '预约规则中心', exact: true })).toBeVisible()
    await adminPage.getByRole('tab', { name: '不可预约日', exact: true }).click()
    const ruleForm = adminPage.locator('.schedule-page__form')
    await ruleForm.locator('.el-form-item').filter({ hasText: '作用范围' }).locator('.el-select').click()
    await adminPage.getByRole('option', { name: '设备', exact: true }).click()
    await ruleForm.locator('.el-form-item').filter({ hasText: '范围对象' }).locator('.el-select').click()
    await adminPage.getByRole('option', { name: fixture.device_name, exact: true }).click()
    const blockedDate = dateAfter(1)
    await ruleForm.getByPlaceholder('选择自然日').fill(blockedDate)
    const reason = `E2E 维护日 ${prefix}`
    await ruleForm.getByPlaceholder('例如：国庆假期 / 设备年度检修').fill(reason)
    await ruleForm.getByRole('button', { name: '保存规则' }).click()
    let ruleRow = adminPage.locator('.el-table__row').filter({ hasText: reason })
    await expect(ruleRow).toBeVisible()
    await expect(ruleRow).toContainText(blockedDate)

    await userPage.getByRole('menuitem', { name: '设备', exact: true }).click()
    const userDevice = userPage.locator('.device-card').filter({ has: userPage.getByText(fixture.device_name, { exact: true }) })
    await userDevice.getByRole('button', { name: '预约' }).click()
    const start = userPage.getByPlaceholder('开始日期')
    await start.fill(blockedDate)
    await start.press('Enter')
    const end = userPage.getByPlaceholder('结束日期')
    await end.fill(blockedDate)
    await end.press('Enter')
    await userPage.getByPlaceholder('例如：完成材料拉伸实验并采集三组数据').fill('E2E 检查预约规则')
    await expect(userPage.getByRole('button', { name: '提交预约' })).toBeDisabled()

    await ruleRow.getByRole('button', { name: '解除' }).click()
    await adminPage.locator('.el-message-box__btns').getByRole('button', { name: '解除' }).click()
    await expect(ruleRow).toHaveCount(0)
    await userPage.reload()
    await userPage.getByPlaceholder('开始日期').fill(blockedDate)
    await userPage.getByPlaceholder('开始日期').press('Enter')
    await userPage.getByPlaceholder('结束日期').fill(blockedDate)
    await userPage.getByPlaceholder('结束日期').press('Enter')
    await userPage.getByPlaceholder('例如：完成材料拉伸实验并采集三组数据').fill('E2E 规则解除后可预约')
    await expect(userPage.getByRole('button', { name: '提交预约' })).toBeEnabled()
    await userPage.screenshot({ path: testInfo.outputPath('reservation-rules-released-user.png'), fullPage: true })

    await adminPage.getByRole('menuitem', { name: '运营报表', exact: true }).click()
    await expect(adminPage.getByRole('heading', { name: '运营报表', exact: true })).toBeVisible()
    const metricCards = adminPage.locator('.reports-page__metrics')
    for (const metric of ['可管理设备', '预约记录', '报修工单', '预约占用率', '实际使用率']) {
      await expect(metricCards.getByText(metric, { exact: true })).toBeVisible()
    }
    await adminPage.screenshot({ path: testInfo.outputPath('operations-reports.png'), fullPage: true })

    const expectedFiles: Array<[string, string]> = [
      ['设备台账', 'lab-devices.csv'],
      ['预约记录', 'lab-reservations.csv'],
      ['报修记录', 'lab-repairs.csv'],
    ]
    for (const [label, fileName] of expectedFiles) {
      const exportRow = adminPage.locator('.reports-page__export-item').filter({ hasText: label })
      const downloadPromise = adminPage.waitForEvent('download')
      await exportRow.getByRole('button', { name: '直接下载' }).click()
      const download = await downloadPromise
      expect(download.suggestedFilename()).toBe(fileName)
    }

    const asyncExportRow = adminPage.locator('.reports-page__export-item').filter({ hasText: '预约记录' })
    await asyncExportRow.getByRole('button', { name: '异步生成' }).click()
    await expect(adminPage.locator('.reports-page__task')).toContainText('已完成', { timeout: 60_000 })
    const asyncDownload = adminPage.waitForEvent('download')
    await adminPage.locator('.reports-page__task').getByRole('button', { name: '下载文件' }).click()
    expect((await asyncDownload).suggestedFilename()).toBe('lab-reservations.csv')

    await adminContext.close()
    await userContext.close()
  })
})
