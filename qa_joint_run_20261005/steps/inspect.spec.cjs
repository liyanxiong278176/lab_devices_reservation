const fs = require('node:fs/promises')
const path = require('node:path')
const { test, expect } = require('../../frontend/node_modules/@playwright/test')

const ROOT = path.resolve(__dirname, '../..')
const SCREENSHOTS = path.join(ROOT, 'qa_joint_run_20261005', 'screenshots')
const PASSWORD = process.env.QA_JOINT_PASSWORD

async function snap(page, folder, name) {
  const dir = path.join(SCREENSHOTS, folder)
  await fs.mkdir(dir, { recursive: true })
  const file = path.join(dir, name)
  await page.screenshot({ path: file, fullPage: true, animations: 'disabled' })
  return file
}

async function signIn(page, username) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(PASSWORD)
  await snap(page, '00-preflight', `${username.endsWith('admin') ? 'admin' : 'user'}_login_before_ok.png`)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page).toHaveURL(/\/dashboard(?:\?.*)?$/)
  await expect(page.getByText('实验室预约系统', { exact: true })).toBeVisible()
  await snap(page, '00-preflight', `${username.endsWith('admin') ? 'admin' : 'user'}_login_result_ok.png`)
}

test('S0 real browser sessions load independently and enforce role menus', async ({ browser }) => {
  expect(PASSWORD, 'QA_JOINT_PASSWORD must be set in the local shell').toBeTruthy()
  const userContext = await browser.newContext()
  const adminContext = await browser.newContext()
  const userPage = await userContext.newPage()
  const adminPage = await adminContext.newPage()
  try {
    await signIn(userPage, 'e2e-joint09-user')
    await signIn(adminPage, 'e2e-joint09-admin')
    for (const label of ['仪表盘', 'AI 工作台', '设备', '我的预约', '我的通知', '提交报修', '我的报修']) {
      await expect(userPage.getByRole('menuitem', { name: label, exact: true })).toBeVisible()
    }
    for (const label of ['待审批', '设备管理', '用户管理', '报修处理', '设备交接']) {
      await expect(userPage.getByRole('menuitem', { name: label, exact: true })).toHaveCount(0)
    }
    await expect(userPage.getByRole('heading', { name: '我的仪表盘', exact: true })).toBeVisible()
    await snap(userPage, '00-preflight', 'user_role_menu_ok.png')
    for (const label of ['仪表盘', 'AI 工作台', '设备', '待审批', '我的通知', '报修处理', '设备管理', '设备交接', '运营报表', '用户管理', '组织管理']) {
      await expect(adminPage.getByRole('menuitem', { name: label, exact: true })).toBeVisible()
    }
    await snap(adminPage, '00-preflight', 'admin_role_menu_ok.png')
  } finally {
    await userContext.close()
    await adminContext.close()
  }
})
