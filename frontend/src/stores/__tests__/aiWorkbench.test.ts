import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const aiApi = vi.hoisted(() => ({
  cancelAiAction: vi.fn(),
  confirmAiAction: vi.fn(),
  createAiConversation: vi.fn(),
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
})
