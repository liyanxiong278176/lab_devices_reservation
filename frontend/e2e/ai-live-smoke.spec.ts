import { test, expect } from '@playwright/test'

test.skip(process.env.LAB_RUN_LIVE_AI !== '1', 'set LAB_RUN_LIVE_AI=1 to call configured external AI providers')

function makeTextPdf(text: string): number[] {
  const escaped = text.replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)')
  const stream = `BT\n/F1 24 Tf\n72 720 Td\n(${escaped}) Tj\nET`
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${Buffer.byteLength(stream, 'ascii')} >>\nstream\n${stream}\nendstream`,
  ]
  let pdf = '%PDF-1.4\n'
  const offsets: number[] = []
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(pdf, 'ascii'))
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`
  }
  const xrefOffset = Buffer.byteLength(pdf, 'ascii')
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  pdf += offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`
  return Array.from(Buffer.from(pdf, 'ascii'))
}

test('真实验证连续工具规划、模型配置与脱敏后对话', async ({ page }, testInfo) => {
  test.setTimeout(180_000)
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))

  await page.setViewportSize({ width: 1440, height: 960 })
  await page.goto('/login?redirect=%2Fai')
  await page.getByLabel('用户名').fill('admin')
  await page.getByLabel('密码').fill('admin123')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/ai(?:\?|$)/)
  await expect(page.locator('.ai-config-required')).toHaveCount(0)

  await page.getByRole('button', { name: '模型配置' }).click()
  const configDialog = page.getByRole('dialog', { name: '全局模型配置' })
  await expect(configDialog).toBeVisible()
  const serviceTabs = [
    { component: 'chat', label: '聊天模型' },
    { component: 'embedding', label: '向量 Embedding' },
    { component: 'mineru', label: '文档解析' },
  ] as const

  for (const service of serviceTabs) {
    await configDialog.getByRole('tab', { name: service.label }).click()
    const responsePromise = page.waitForResponse((response) =>
      new URL(response.url()).pathname === `/api/v2/ai/config/${service.component}/test`,
    )
    await configDialog.getByRole('button', { name: '测试连接' }).click()
    const response = await responsePromise
    expect(response.status(), `${service.component} provider HTTP status`).toBe(200)
    const result = (await response.json()).data as { success: boolean; model: string }
    expect(result.success, `${service.component} provider connectivity`).toBe(true)
    expect(result.model).toBeTruthy()
    await expect(configDialog.locator('.el-alert')).toContainText('连接成功')
  }
  await page.screenshot({ path: testInfo.outputPath('ai-live-provider-checks.png'), animations: 'disabled' })
  await configDialog.getByRole('button', { name: '关闭' }).click()

  await page.getByRole('button', { name: '对话记录' }).click()
  await expect(page.getByRole('button', { name: '发起新任务' })).toBeVisible()
  const createPromise = page.waitForResponse((response) =>
    response.request().method() === 'POST'
      && new URL(response.url()).pathname === '/api/v2/ai/conversations',
  )
  await page.getByRole('button', { name: '发起新任务' }).click()
  const createResponse = await createPromise
  expect(createResponse.status()).toBe(201)
  const conversation = (await createResponse.json()).data as { id: number }
  await page.getByRole('button', { name: '对话记录' }).click()
  let conversationNeedsCleanup = true

  try {
    const deviceResponse = await page.evaluate(async () => {
      const response = await fetch('/api/v2/devices?page=1&page_size=5&status=IDLE&search=%E6%98%BE%E5%BE%AE%E9%95%9C')
      return { status: response.status, body: await response.json() }
    })
    expect(deviceResponse.status).toBe(200)
    const devicePage = deviceResponse.body.data as { items: Array<{ id: number }> }
    expect(devicePage.items.length, 'live test needs one visible idle microscope').toBeGreaterThan(0)
    const targetDate = await page.evaluate(() => {
      const value = new Date()
      value.setDate(value.getDate() + 7)
      return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
    })

    const input = page.locator('.ai-composer textarea')
    await expect(input).toBeEnabled()
    await input.fill(
      `请先搜索名称包含“显微镜”的设备，再选择搜索结果中的第一台设备，查询它在${targetDate}是否可用。安全测试手机号 13800138000`,
    )
    const streamPromise = page.waitForResponse((response) =>
      response.request().method() === 'POST'
        && new URL(response.url()).pathname === `/api/v2/ai/conversations/${conversation.id}/stream`,
    )
    await page.getByRole('button', { name: '发送' }).click()
    const streamResponse = await streamPromise
    expect(streamResponse.status()).toBe(200)

    await expect(page.locator('.dlp-notice')).toContainText('手机号', { timeout: 30_000 })
    const userBubble = page.locator('.chat-message--user .chat-message__bubble').last()
    await expect(userBubble).toContainText('[已脱敏]')
    await expect(userBubble).not.toContainText('13800138000')
    const assistantBubble = page.locator('.chat-message--assistant .chat-message__bubble').last()
    await expect(assistantBubble).toContainText('可用日期：', { timeout: 120_000 })
    await expect(assistantBubble).toContainText(targetDate)
    await expect(assistantBubble).toContainText('显微镜')
    await expect(assistantBubble).not.toContainText('13800138000')
    await expect(assistantBubble).not.toContainText('[citation:')
    await expect(page.locator('.workbench-alert')).toHaveCount(0)
    expect(await page.locator('.trace-step').filter({ hasText: 'policy_planner' }).count()).toBeGreaterThanOrEqual(3)
    expect(await page.locator('.trace-step').filter({ hasText: 'search_devices' }).count()).toBeGreaterThan(0)
    await expect(page.locator('.trace-step').filter({ hasText: 'check_availability' })).toHaveCount(1)
    const inlineCitation = page.locator('.message-citation').filter({ hasText: '可用性' }).first()
    await expect(inlineCitation).toBeVisible()
    const citationPromise = page.waitForResponse((response) =>
      new URL(response.url()).pathname.startsWith('/api/v2/ai/citations/business/'),
    )
    await inlineCitation.click()
    const citationResponse = await citationPromise
    expect(citationResponse.status()).toBe(200)
    await expect(page.locator('.citation-detail')).toContainText(targetDate)
    await expect(page.locator('.citation-detail .el-loading-mask')).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath('ai-live-chat-dlp-citation.png'), animations: 'disabled' })
    await page.locator('.citation-drawer .el-drawer__close-btn').click()
    await expect(page.locator('.citation-drawer')).not.toBeVisible()
    await page.screenshot({ path: testInfo.outputPath('ai-live-chat-answer.png'), animations: 'disabled' })

    await page.getByRole('button', { name: '运行详情' }).click()
    const citation = page.locator('.citation__button').filter({ hasText: '可用性' }).first()
    await expect(citation).toBeVisible()
    await expect(citation).toContainText('可用性')

    const messagesResponse = await page.evaluate(async (conversationId) => {
      const response = await fetch(`/api/v2/ai/conversations/${conversationId}/messages`)
      return { status: response.status, body: await response.json() }
    }, conversation.id)
    expect(messagesResponse.status).toBe(200)
    const messages = messagesResponse.body.data as Array<{
      role: string
      content: string
      metadata?: { tool_name?: string }
    }>
    const persistedUserMessage = [...messages].reverse().find((message) => message.role === 'user')
    expect(persistedUserMessage).toBeTruthy()
    expect(persistedUserMessage!.content).toContain('[已脱敏]')
    expect(persistedUserMessage!.content).not.toContain('13800138000')
    const toolNames = messages
      .filter((message) => message.role === 'tool')
      .map((message) => message.metadata?.tool_name)
    expect(toolNames).toContain('search_devices')
    expect(toolNames.at(-1)).toBe('check_availability')

    const deleteResult = await page.evaluate(async (conversationId) => {
      const csrf = localStorage.getItem('lab-auth-csrf-token') || ''
      const response = await fetch(`/api/v2/ai/conversations/${conversationId}`, {
        method: 'DELETE',
        headers: { 'X-CSRF-Token': csrf },
      })
      return { status: response.status }
    }, conversation.id)
    expect(deleteResult.status).toBe(200)
    conversationNeedsCleanup = false
    expect(pageErrors).toEqual([])
  } finally {
    if (conversationNeedsCleanup) {
      try {
        await page.evaluate(async (conversationId) => {
          const csrf = localStorage.getItem('lab-auth-csrf-token') || ''
          await fetch(`/api/v2/ai/conversations/${conversationId}`, {
            method: 'DELETE',
            headers: { 'X-CSRF-Token': csrf },
          })
        }, conversation.id)
      } catch {
        // Playwright can close the page when the test-level timeout fires.
        // The original failure remains actionable; test conversations are
        // cleaned up separately if that happens.
      }
    }
  }
})

test('真实验证 MinerU 解析、RAG 检索、引用打开与清理', async ({ page }, testInfo) => {
  test.setTimeout(180_000)
  const marker = `RAG-LIVE-${Date.now()}`
  const title = `临时 RAG 验收 ${marker}`
  const sourceText = `Safety training reference code: ${marker}.`
  let documentId: number | null = null
  let conversationId: number | null = null

  await page.setViewportSize({ width: 1440, height: 960 })
  await page.goto('/login?redirect=%2Fai')
  await page.getByLabel('用户名').fill('admin')
  await page.getByLabel('密码').fill('admin123')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/ai(?:\?|$)/)
  await expect(page.locator('.ai-config-required')).toHaveCount(0)

  try {
    const createDocument = await page.evaluate(async ({ title, marker, pdfBytes }) => {
      const csrf = localStorage.getItem('lab-auth-csrf-token') || ''
      const form = new FormData()
      form.append('title', title)
      form.append('source_type', 'FAQ')
      form.append('file', new File([new Uint8Array(pdfBytes)], `${marker}.pdf`, { type: 'application/pdf' }))
      const response = await fetch('/api/v2/ai/knowledge/upload', {
        method: 'POST',
        headers: { 'X-CSRF-Token': csrf },
        body: form,
      })
      return { status: response.status, body: await response.json() }
    }, { title, marker, pdfBytes: makeTextPdf(sourceText) })
    expect(createDocument.status).toBe(201)
    documentId = createDocument.body.data.id as number

    const parse = await page.evaluate(async (id) => {
      const csrf = localStorage.getItem('lab-auth-csrf-token') || ''
      const response = await fetch(`/api/v2/ai/knowledge/${id}/parse`, {
        method: 'POST',
        headers: { 'X-CSRF-Token': csrf },
      })
      return { status: response.status, body: await response.json() }
    }, documentId)
    expect(parse.status).toBe(200)
    expect(parse.body.data.parse_status).toBe('QUEUED')

    const parsed = await page.evaluate(async (id) => {
      const csrf = localStorage.getItem('lab-auth-csrf-token') || ''
      for (let attempt = 0; attempt < 70; attempt += 1) {
        const response = await fetch(`/api/v2/ai/knowledge/${id}`)
        const result = await response.json()
        const document = result.data
        if (document.parse_status === 'PARSED' || document.parse_status === 'FAILED') {
          return { status: response.status, body: result }
        }
        await new Promise((resolve) => window.setTimeout(resolve, 2_000))
      }
      return { status: 408, body: { data: null } }
    }, documentId)
    expect(parsed.status).toBe(200)
    expect(parsed.body.data.parse_status, parsed.body.data.parse_error || 'MinerU parse timeout').toBe('PARSED')
    expect(parsed.body.data.extracted_text).toContain(marker)

    const review = await page.evaluate(async ({ documentId, body }) => {
      const csrf = localStorage.getItem('lab-auth-csrf-token') || ''
      const response = await fetch(`/api/v2/ai/knowledge/${documentId}/review`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ reviewed_text: body }),
      })
      return { status: response.status, body: await response.json() }
    }, { documentId, body: parsed.body.data.extracted_text as string })
    expect(review.status).toBe(200)
    expect(review.body.data.parse_status).toBe('REVIEWED')

    const publish = await page.evaluate(async (id) => {
      const csrf = localStorage.getItem('lab-auth-csrf-token') || ''
      const response = await fetch(`/api/v2/ai/knowledge/${id}/publish`, {
        method: 'POST',
        headers: { 'X-CSRF-Token': csrf },
      })
      return { status: response.status, body: await response.json() }
    }, documentId)
    expect(publish.status).toBe(200)
    expect(publish.body.data.status).toBe('PUBLISHED')
    expect(publish.body.data.chunk_count).toBeGreaterThan(0)

    await page.getByRole('button', { name: '对话记录' }).click()
    const createConversation = page.waitForResponse((response) =>
      response.request().method() === 'POST'
        && new URL(response.url()).pathname === '/api/v2/ai/conversations',
    )
    await page.getByRole('button', { name: '发起新任务' }).click()
    const conversationResponse = await createConversation
    expect(conversationResponse.status()).toBe(201)
    conversationId = ((await conversationResponse.json()).data.id as number)
    await page.getByRole('button', { name: '对话记录' }).click()

    const input = page.locator('.ai-composer textarea')
    await input.fill(`请根据知识库中 ${marker} 的资料，回答 safety training reference code，并引用来源。`)
    const stream = page.waitForResponse((response) =>
      response.request().method() === 'POST'
        && new URL(response.url()).pathname === `/api/v2/ai/conversations/${conversationId}/stream`,
    )
    await page.getByRole('button', { name: '发送' }).click()
    expect((await stream).status()).toBe(200)

    const answer = page.locator('.chat-message--assistant .chat-message__bubble').last()
    await expect(answer).toContainText(marker, { timeout: 120_000 })
    const citation = page.locator('.chat-message--assistant').last().locator('.message-citation').first()
    await expect(citation).toBeVisible()
    await expect(citation).toContainText(title)
    const citationResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname.startsWith('/api/v2/ai/citations/knowledge/'),
    )
    await citation.click()
    expect((await citationResponse).status()).toBe(200)
    await expect(page.locator('.citation-detail')).toContainText(marker)
    await page.screenshot({ path: testInfo.outputPath('ai-live-rag-answer-citation.png'), animations: 'disabled' })
    await expect(page.locator('.citation-detail .el-loading-mask')).toHaveCount(0)
  } finally {
    if (conversationId !== null) {
      await page.evaluate(async (id) => {
        const csrf = localStorage.getItem('lab-auth-csrf-token') || ''
        await fetch(`/api/v2/ai/conversations/${id}`, {
          method: 'DELETE',
          headers: { 'X-CSRF-Token': csrf },
        })
      }, conversationId).catch(() => undefined)
    }
    if (documentId !== null) {
      const cleanup = await page.evaluate(async (id) => {
        const csrf = localStorage.getItem('lab-auth-csrf-token') || ''
        const response = await fetch(`/api/v2/ai/knowledge/${id}`, {
          method: 'DELETE',
          headers: { 'X-CSRF-Token': csrf },
        })
        return response.status
      }, documentId).catch(() => 0)
      expect(cleanup, 'temporary knowledge document must be removed').toBe(200)
    }
  }
})
