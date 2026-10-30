import { readFile } from 'node:fs/promises'
import { javaCommand } from './java-command'
import { test, expect, type Page } from './flow-test'

let prefix: string
let fixture: { username: string; admin_username: string; password: string; device_name: string }

async function login(page: Page, username: string) {
  await page.goto('/login')
  await page.getByLabel('用户名', { exact: true }).fill(username)
  await page.getByLabel('密码', { exact: true }).fill(fixture.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/dashboard/)
}

async function openDetail(page: Page, name: string) {
  await page.getByRole('menuitem', { name: '设备', exact: true }).click()
  const search = page.getByPlaceholder('搜索设备名称 / 型号')
  await search.fill(name)
  await search.press('Enter')
  await page.locator('.device-card').filter({ has: page.getByText(name, { exact: true }) }).click()
  await page.getByRole('button', { name: '查看完整详情' }).click()
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
}

test.beforeEach(() => {
  prefix = `e2e-share-${Date.now().toString(36)}`
  fixture = JSON.parse(javaCommand('seed', prefix))
})
test.afterEach(() => { javaCommand('cleanup', prefix) })

test('管理员发布文档后普通用户可下载，归档后不再公开显示', async ({ browser }, testInfo) => {
  test.setTimeout(120_000)
  const adminContext = await browser.newContext()
  const userContext = await browser.newContext()
  const admin = await adminContext.newPage()
  const user = await userContext.newPage()
  try {
    await login(admin, fixture.admin_username)
    await openDetail(admin, fixture.device_name)
    await admin.getByRole('button', { name: '上传文档', exact: true }).click()
    const dialog = admin.getByRole('dialog', { name: '上传设备文档' })
    await dialog.getByLabel('标题').fill('同学院共享文档回归')
    const content = 'Device document shared by the system administrator.'
    await dialog.locator('input[type="file"]').setInputFiles({
      name: 'shared-device-guide.txt', mimeType: 'text/plain', buffer: Buffer.from(content),
    })
    await dialog.getByRole('button', { name: '上传', exact: true }).click()
    await expect(admin.locator('.device-document').filter({ hasText: '同学院共享文档回归' })).toBeVisible()

    await login(user, fixture.username)
    await openDetail(user, fixture.device_name)
    const doc = user.locator('.device-document').filter({ hasText: '同学院共享文档回归' })
    const responsePromise = user.waitForResponse((response) => new URL(response.url()).pathname.startsWith('/api/v2/device-documents/'))
    const downloadPromise = user.waitForEvent('download')
    await doc.getByRole('button', { name: '查看', exact: true }).click()
    expect((await responsePromise).status()).toBe(200)
    const download = await downloadPromise
    expect(await download.failure()).toBeNull()
    expect(await readFile((await download.path())!, 'utf8')).toBe(content)
    await user.screenshot({ path: testInfo.outputPath('student-document-download.png'), fullPage: true })

    await admin.locator('.device-document').filter({ hasText: '同学院共享文档回归' }).getByRole('button', { name: '归档', exact: true }).click()
    await admin.locator('.el-message-box').getByRole('button', { name: '归档', exact: true }).click()
    await expect(admin.locator('.device-document').filter({ hasText: '同学院共享文档回归' })).toHaveCount(0)
    await user.reload()
    await expect(user.locator('.device-document').filter({ hasText: '同学院共享文档回归' })).toHaveCount(0)
  } finally {
    await adminContext.close()
    await userContext.close()
  }
})

test('同页面新建资源池后无需刷新即可加入第二台实物', async ({ browser }, testInfo) => {
  test.setTimeout(120_000)
  const context = await browser.newContext()
  const page = await context.newPage()
  try {
    await login(page, fixture.admin_username)
    await page.getByRole('menuitem', { name: '设备管理', exact: true }).click()
    const name = `${prefix}-pooled`
    for (let index = 0; index < 2; index++) {
      await page.getByRole('button', { name: '新增设备', exact: true }).click()
      const drawer = page.locator('.dmanage-drawer')
      await drawer.getByRole('textbox', { name: /名称/ }).fill(name)
      await drawer.locator('.el-form-item').filter({ hasText: '分类' }).locator('.el-select').click()
      await page.locator('.el-tree-node__content:visible').filter({ hasText: `${prefix}-category` }).click()
      await drawer.locator('.el-form-item').filter({ hasText: '实验室' }).locator('.el-select').click()
      await page.getByRole('option', { name: `${prefix}-lab`, exact: true }).click()
      await drawer.getByRole('spinbutton').fill('8')
      if (index === 1) {
        await drawer.locator('.el-form-item').filter({ hasText: '资源池' }).locator('.el-select').click()
        await page.getByRole('option', { name: `${name}（1 台，${prefix}-lab）`, exact: true }).click()
      }
      await drawer.getByRole('button', { name: '保存', exact: true }).click()
      await expect(drawer).toBeHidden()
    }
    await page.getByRole('menuitem', { name: '设备', exact: true }).click()
    await page.getByPlaceholder('搜索设备名称 / 型号').fill(name)
    await page.getByPlaceholder('搜索设备名称 / 型号').press('Enter')
    const pool = page.locator('.device-card').filter({ has: page.getByText(name, { exact: true }) })
    await expect(pool).toHaveCount(1)
    await expect(pool).toContainText('实物 2 台')
    await page.screenshot({ path: testInfo.outputPath('new-pool-two-units.png'), fullPage: true })
  } finally {
    await context.close()
  }
})
