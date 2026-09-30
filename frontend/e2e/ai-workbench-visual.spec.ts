import { test, expect } from '@playwright/test'

test('管理员实际浏览 AI 对话、环境配置状态、知识库与用量页面', async ({ page }, testInfo) => {
  const uncaughtErrors: string[] = []
  page.on('pageerror', (error) => uncaughtErrors.push(error.message))
  const readinessResponsePromise = page.waitForResponse((response) => {
    return new URL(response.url()).pathname === '/api/v2/ai/status'
  })

  await page.setViewportSize({ width: 1440, height: 960 })
  await page.goto('/login?redirect=%2Fai')
  await page.getByLabel('用户名').fill('admin')
  await page.getByLabel('密码').fill('admin123')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/ai(?:\?|$)/)
  await expect(page.getByRole('heading', { name: 'AI 工作台', exact: true })).toBeVisible()
  await expect(page.locator('.login-page')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '对话工作区' })).toBeVisible()
  await expect(page.getByRole('button', { name: '知识库' })).toBeVisible()
  await expect(page.getByRole('button', { name: '用量与额度' })).toBeVisible()
  await expect(page.locator('.el-message')).toHaveCount(0)

  const readinessResponse = await readinessResponsePromise
  expect(readinessResponse.status()).toBe(200)
  const readinessBody = await readinessResponse.json()
  const readiness = readinessBody.data as { available: boolean }
  expect(readiness).toBeTruthy()
  if (readiness.available) {
    await expect(page.locator('.ai-config-required')).toHaveCount(0)
    await expect(page.locator('.ai-composer textarea')).toBeEnabled()
  } else {
    await expect(page.locator('.ai-config-required')).toBeVisible()
    await expect(page.locator('.ai-composer textarea')).toBeDisabled()
  }
  const chatBody = page.locator('.ai-chat__body')
  await expect.poll(async () => chatBody.evaluate((element) => {
    const chat = element as HTMLElement
    return chat.scrollHeight - chat.scrollTop - chat.clientHeight
  })).toBeLessThan(100)
  const promptButtons = page.locator('.prompt-grid button')
  if (await promptButtons.count()) {
    await expect(promptButtons.last()).toBeInViewport({ ratio: 1 })
  } else {
    await expect(page.locator('.chat-message__bubble').last()).toBeVisible()
  }
  await page.screenshot({ path: testInfo.outputPath('ai-workbench-chat.png'), animations: 'disabled' })

  const configsResponsePromise = page.waitForResponse((response) => {
    return new URL(response.url()).pathname === '/api/v2/ai/config/components'
  })
  const rebuildResponsePromise = page.waitForResponse((response) => {
    return new URL(response.url()).pathname === '/api/v2/ai/embedding/rebuild/latest'
  })
  await page.getByRole('button', { name: '模型配置' }).click()
  const [configsResponse, rebuildResponse] = await Promise.all([
    configsResponsePromise,
    rebuildResponsePromise,
  ])
  expect(configsResponse.status()).toBe(200)
  expect(rebuildResponse.status()).toBe(200)
  const configuredServices = (await configsResponse.json()).data as Array<{
    component: string
    source: string
    configured: boolean
    api_key?: string
  }>
  expect(configuredServices.map((item) => item.component).sort()).toEqual(['chat', 'embedding', 'mineru'])
  expect(configuredServices.every((item) => !('api_key' in item))).toBe(true)
  const dialog = page.getByRole('dialog', { name: '全局模型配置' })
  await expect(dialog).toBeVisible()
  await expect(dialog.locator('.el-loading-mask')).toHaveCount(0)
  await expect(dialog.getByRole('tab', { name: '聊天模型' })).toBeVisible()
  await expect(dialog.getByText('LAB_AI_API_KEY')).toBeVisible()
  await expect(dialog.getByRole('button', { name: '保存并应用' })).toHaveCount(0)
  await page.screenshot({ path: testInfo.outputPath('ai-workbench-model-chat.png'), animations: 'disabled' })

  await dialog.getByRole('tab', { name: '向量 Embedding' }).click()
  await expect(dialog.locator('.el-loading-mask')).toHaveCount(0)
  await expect(dialog.getByText('蓝绿索引重建')).toBeVisible()
  await expect(dialog.getByRole('button', { name: '重建索引' })).toBeVisible()
  await expect(dialog.locator('.el-dialog__footer')).toBeInViewport({ ratio: 1 })
  await page.screenshot({ path: testInfo.outputPath('ai-workbench-model-embedding.png'), animations: 'disabled' })
  await dialog.getByRole('button', { name: '关闭' }).click()

  await page.getByRole('button', { name: '知识库' }).click()
  await expect(page.getByRole('heading', { name: '知识库', exact: true })).toBeVisible()
  const scopeRolesResponsePromise = page.waitForResponse((response) =>
    new URL(response.url()).pathname === '/api/v2/ai/knowledge/scope-roles',
  )
  await page.getByRole('button', { name: '新建文本' }).click()
  const scopeRolesResponse = await scopeRolesResponsePromise
  expect(scopeRolesResponse.status()).toBe(200)
  const scopeRoles = (await scopeRolesResponse.json()).data as Array<{ code: string; name: string }>
  const labAdminRole = scopeRoles.find((role) => role.code === 'LAB_ADMIN')
  expect(labAdminRole).toBeTruthy()
  const knowledgeDialog = page.getByRole('dialog', { name: '新建文本知识' })
  await expect(knowledgeDialog).toBeVisible()
  await expect(knowledgeDialog.getByText('实验室范围')).toBeVisible()
  await expect(knowledgeDialog.getByText('设备范围')).toBeVisible()
  await expect(knowledgeDialog.getByText(/可见角色/)).toBeVisible()
  const roleSelect = knowledgeDialog.locator('.el-select').last()
  await roleSelect.click()
  const labAdminOption = page.getByRole('option', { name: labAdminRole!.name })
  await expect(labAdminOption).toBeVisible()
  await labAdminOption.click()
  await expect(roleSelect).toContainText(labAdminRole!.name)
  await page.screenshot({ path: testInfo.outputPath('ai-workbench-knowledge-scope.png'), animations: 'disabled' })
  await knowledgeDialog.getByRole('button', { name: '取消' }).click()
  await page.screenshot({ path: testInfo.outputPath('ai-workbench-knowledge.png'), animations: 'disabled' })

  await page.getByRole('button', { name: '用量与额度' }).click()
  await expect(page.getByRole('heading', { name: '用量与额度', exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('ai-workbench-usage.png'), animations: 'disabled' })

  expect(uncaughtErrors).toEqual([])
})
