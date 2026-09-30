import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const aiApi = vi.hoisted(() => ({
  cancelAiAction: vi.fn(),
  confirmAiAction: vi.fn(),
  createAiConversation: vi.fn(),
  getActiveAiRun: vi.fn(),
  listAiConversations: vi.fn(),
  listAiMessages: vi.fn(),
  streamAiMessage: vi.fn(),
}))

vi.mock('@/api/aiV2', () => aiApi)

import { useAiWorkbenchStore } from '../aiWorkbench'

const pending = {
  id: 99,
  tool_name: 'create_reservation',
  reason: '需要确认',
  risk_summary: '会修改预约数据',
  estimated_impact: '当前用户',
  preview: {},
  status: 'PENDING',
}

describe('aiWorkbench confirmation lifecycle', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    aiApi.listAiConversations.mockResolvedValue([])
    aiApi.getActiveAiRun.mockResolvedValue(null)
  })

  it('409 已处理确认会清除卡片，避免页面持续阻塞', async () => {
    const store = useAiWorkbenchStore()
    store.pendingConfirmation = pending
    aiApi.confirmAiAction.mockRejectedValue({ response: { status: 409 } })

    const result = await store.confirm()

    expect(result).toBe(false)
    expect(store.pendingConfirmation).toBeNull()
  })

  it('确认成功后清除卡片并返回成功', async () => {
    const store = useAiWorkbenchStore()
    store.pendingConfirmation = pending
    aiApi.confirmAiAction.mockResolvedValue({ status: 'EXECUTED' })

    const result = await store.confirm()

    expect(result).toBe(true)
    expect(store.pendingConfirmation).toBeNull()
    expect(store.messages.at(-1)?.content).toContain('执行完成')
  })

  it('快速切换会话时忽略较早返回的消息响应', async () => {
    const store = useAiWorkbenchStore()
    let resolveFirst!: (messages: Array<{ id: number; role: string; content: string }>) => void
    let resolveSecond!: (messages: Array<{ id: number; role: string; content: string }>) => void
    aiApi.listAiMessages.mockImplementation((id: number) => new Promise((resolve) => {
      if (id === 1) resolveFirst = resolve
      else resolveSecond = resolve
    }))

    const firstSelection = store.selectConversation(1)
    const secondSelection = store.selectConversation(2)
    resolveSecond([{ id: 2, role: 'user', content: '会话2' }])
    await secondSelection
    resolveFirst([{ id: 1, role: 'user', content: '会话1' }])
    await firstSelection

    expect(store.activeConversationId).toBe(2)
    expect(store.messages.map((message) => message.content)).toEqual(['会话2'])
  })

  it('读取较慢的旧运行状态时不附着到已切换的会话', async () => {
    const store = useAiWorkbenchStore()
    let resolveFirstRun!: (run: null | { run_id: number }) => void
    aiApi.listAiMessages.mockImplementation(async (id: number) => [
      { id, role: 'user', content: `会话${id}` },
    ])
    aiApi.getActiveAiRun.mockImplementation((id: number) => id === 1
      ? new Promise((resolve) => { resolveFirstRun = resolve })
      : Promise.resolve(null))

    const firstSelection = store.selectConversation(1)
    await Promise.resolve()
    await Promise.resolve()
    const secondSelection = store.selectConversation(2)
    await secondSelection
    resolveFirstRun({ run_id: 101 })
    await firstSelection

    expect(store.activeConversationId).toBe(2)
    expect(store.activeRunId).toBeNull()
    expect(store.messages.map((message) => message.content)).toEqual(['会话2'])
  })

  it('收到 DLP 事件后立即用脱敏内容替换乐观用户消息', async () => {
    const store = useAiWorkbenchStore()
    store.activeConversationId = 7
    const redactedText = '请帮我查询手机号 [已脱敏]'
    let visibleDuringStream = ''
    aiApi.listAiMessages.mockResolvedValue([
      { id: 1, role: 'user', content: redactedText },
      { id: 2, role: 'assistant', content: '已完成' },
    ])
    aiApi.streamAiMessage.mockImplementation(async (_id, _text, callbacks) => {
      callbacks.onEvent({
        type: 'dlp_notice',
        categories: ['手机号'],
        redacted_content: redactedText,
      })
      visibleDuringStream = store.messages[0].content
      callbacks.onEvent({ type: 'token', text: '已完成' })
    })

    await store.send('请帮我查询手机号 13800138000')

    expect(visibleDuringStream).toBe(redactedText)
    expect(store.messages[0].content).toBe(redactedText)
    expect(store.messages[0].content).not.toContain('13800138000')
  })
})
