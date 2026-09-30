import { defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'

const notificationApi = vi.hoisted(() => ({
  markAllRead: vi.fn(), markRead: vi.fn(), myNotifications: vi.fn(),
}))
const notificationStore = vi.hoisted(() => ({
  decreaseUnread: vi.fn(), clearUnread: vi.fn(), loadUnread: vi.fn(),
}))
const messages = vi.hoisted(() => ({ success: vi.fn() }))
const reveal = vi.hoisted(() => vi.fn())
vi.mock('@/api/notification', () => notificationApi)
vi.mock('@/stores/notification', () => ({ useNotificationStore: () => notificationStore }))
vi.mock('@/composables/useStagger', () => ({ useStagger: () => ({ reveal }) }))
vi.mock('element-plus', () => ({ ElMessage: messages }))

import NotificationPage from '../Index.vue'

const FilterStub = defineComponent({
  props: ['modelValue', 'options'],
  emits: ['update:modelValue'],
  setup(_props, { emit }) {
    return () => h('div', { class: 'filter-stub' }, [
      h('button', { class: 'filter-unread', onClick: () => emit('update:modelValue', 'unread') }, '未读'),
      h('button', { class: 'filter-all', onClick: () => emit('update:modelValue', 'all') }, '全部'),
      h('button', { class: 'filter-invalid', onClick: () => emit('update:modelValue', 'other') }, '其它'),
    ])
  },
})

const DrawerStub = defineComponent({
  props: { modelValue: { type: Boolean, default: false }, title: String },
  emits: ['update:modelValue'],
  setup(props, { slots, emit }) {
    return () => h('aside', { class: 'drawer-stub', hidden: !props.modelValue, title: props.title }, [
      ...(props.modelValue ? slots.default?.() ?? [] : []),
      h('button', { class: 'drawer-close', onClick: () => emit('update:modelValue', false) }, 'close'),
    ])
  },
})

const PageSizeStub = defineComponent({
  props: ['modelValue', 'options', 'label'],
  emits: ['change'],
  setup(_props, { emit }) {
    return () => h('button', { class: 'size-stub', onClick: () => emit('change', 20) }, 'size')
  },
})

const PaginationStub = defineComponent({
  props: ['currentPage', 'pageSize', 'total', 'totalText'],
  emits: ['current-change', 'size-change'],
  setup(_props, { emit }) {
    return () => h('div', { class: 'pagination-stub' }, [
      h('button', { class: 'page-three', onClick: () => emit('current-change', 3) }, '3'),
      h('button', { class: 'page-size', onClick: () => emit('size-change', 50) }, '50'),
    ])
  },
})

const stubs = {
  PageHeader: { template: '<header><slot name="actions" /></header>' },
  GhostButton: {
    inheritAttrs: false,
    template: '<button class="mark-all" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  Tag: { props: ['variant'], template: '<span class="tag" :data-variant="variant"><slot /></span>' },
  EmptyState: { props: ['title'], template: '<div class="empty-state">{{ title }}</div>' },
  SegmentedControl: FilterStub,
  PageDepthNotice: { props: ['total'], template: '<div class="depth-notice" :data-total="total" />' },
  PageSizeControl: PageSizeStub,
  'el-drawer': DrawerStub,
  'el-pagination': PaginationStub,
}

type Row = {
  id: number; userId: number; type: string; title: string; content?: string | null;
  isRead: 0 | 1; createdAt?: string; relatedType?: string | null; relatedId?: number | null;
}
const row = (id: number, type = 'SYSTEM', extras: Partial<Row> = {}): Row => ({
  id, userId: 4, type, title: `Notice ${id}`, content: 'Details', isRead: 1,
  createdAt: '2026-09-28T10:15:00', ...extras,
})
const page = (records: Row[], extras: Record<string, unknown> = {}) => ({
  records, total: records.length, size: 10, current: 1, pages: 1, truncated: false, ...extras,
})
const mountPage = () => mount(NotificationPage, {
  global: { stubs, directives: { loading: () => undefined } },
})

enableAutoUnmount(afterEach)

beforeEach(() => {
  vi.resetAllMocks()
  notificationApi.myNotifications.mockResolvedValue(page([]))
  notificationApi.markRead.mockResolvedValue(undefined)
  notificationApi.markAllRead.mockResolvedValue(undefined)
  notificationStore.loadUnread.mockResolvedValue(undefined)
})

afterEach(() => vi.clearAllTimers())

describe('notification page branch and lifecycle scenarios', () => {
  it('maps every notification category and renders fallback detail fields', async () => {
    const rows = [
      row(1, 'APPROVAL'), row(2, 'RESERVATION_APPROVED'), row(3, 'RESERVATION_REJECTED'),
      row(4, 'RESERVATION'), row(5, 'RESERVATION_CREATED'), row(6, 'REPAIR'),
      row(7, 'REPAIR_UPDATE'), row(8, 'SYSTEM'),
      row(9, 'CUSTOM', { content: '', createdAt: undefined, relatedType: null, relatedId: null }),
    ]
    notificationApi.myNotifications.mockResolvedValue(page(rows))
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.findAll('.notif-row__head .tag').map((tag) => [tag.text(), tag.attributes('data-variant')]))
      .toEqual([
        ['审批', 'warning'], ['审批', 'warning'], ['审批', 'warning'],
        ['预约', 'accent'], ['预约', 'accent'], ['报修', 'danger'],
        ['报修', 'danger'], ['系统', 'info'], ['CUSTOM', 'default'],
      ])
    expect(wrapper.findAll('.notif-row__time')[8].text()).toBe('—')
    expect(wrapper.findAll('.notif-row__content')).toHaveLength(8)
    await wrapper.findAll('.notif-row')[8].trigger('click')
    expect(wrapper.find('.notif-detail__message').text()).toContain('暂无详细内容。')
    expect(wrapper.find('.notif-detail__facts').text()).not.toContain('关联业务')
    expect(notificationApi.markRead).not.toHaveBeenCalled()

    await wrapper.findAll('.notif-row')[0].trigger('keydown.enter')
    expect(wrapper.find('.notif-detail__message').text()).toContain('Details')
    await wrapper.findAll('.notif-row')[0].trigger('keydown.space')
    expect(wrapper.find('.notif-detail__facts').text()).toContain('2026-09-28 10:15')
    await wrapper.find('.drawer-close').trigger('click')
    expect(wrapper.get('.drawer-stub').attributes('hidden')).toBeDefined()
  })

  it('shows truncated-page guidance and applies filter, page and page-size changes', async () => {
    notificationApi.myNotifications.mockResolvedValue(page([row(1)], {
      total: 101, size: 10, current: 1, pages: 0, truncated: true,
    }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('.depth-notice').attributes('data-total')).toBe('101')

    await wrapper.find('.filter-unread').trigger('click')
    await flushPromises()
    expect(notificationApi.myNotifications).toHaveBeenLastCalledWith({ onlyUnread: true, page: 1, size: 10 })

    await wrapper.find('.page-three').trigger('click')
    await flushPromises()
    expect(notificationApi.myNotifications).toHaveBeenLastCalledWith({ onlyUnread: true, page: 3, size: 10 })

    await wrapper.find('.size-stub').trigger('click')
    await flushPromises()
    expect(notificationApi.myNotifications).toHaveBeenLastCalledWith({ onlyUnread: true, page: 1, size: 20 })

    await wrapper.find('.filter-all').trigger('click')
    await flushPromises()
    expect(notificationApi.myNotifications).toHaveBeenLastCalledWith({ onlyUnread: undefined, page: 1, size: 20 })
    expect(wrapper.find('.depth-notice').exists()).toBe(true)
  })

  it('marks all rows read, clears the unread badge, and recovers from a server failure', async () => {
    notificationApi.myNotifications.mockResolvedValue(page([row(1, 'SYSTEM', { isRead: 0 }), row(2)]))
    const wrapper = mountPage()
    await flushPromises()

    await wrapper.find('.mark-all').trigger('click')
    await flushPromises()
    expect(notificationApi.markAllRead).toHaveBeenCalledOnce()
    expect(wrapper.findAll('.notif-row').every((item) => item.attributes('data-read') === 'read')).toBe(true)
    expect(notificationStore.clearUnread).toHaveBeenCalledOnce()
    expect(notificationStore.loadUnread).toHaveBeenCalledTimes(2)
    expect(messages.success).toHaveBeenCalledWith('已全部标记为已读')

    notificationApi.markAllRead.mockRejectedValueOnce(new Error('offline'))
    await wrapper.find('.mark-all').trigger('click')
    await flushPromises()
    expect(notificationApi.markAllRead).toHaveBeenCalledTimes(2)
    expect(notificationStore.clearUnread).toHaveBeenCalledOnce()
    expect(messages.success).toHaveBeenCalledOnce()
  })

  it('prevents duplicate mark-read requests, updates unread state once and allows retry after failure', async () => {
    const records = [row(1, 'REPAIR', { isRead: 0, relatedType: null, relatedId: 22 })]
    notificationApi.myNotifications.mockResolvedValue(page(records))
    let resolveRead!: () => void
    notificationApi.markRead.mockReturnValueOnce(new Promise<void>((resolve) => { resolveRead = resolve }))
    const wrapper = mountPage()
    await flushPromises()

    const item = wrapper.find('.notif-row')
    await item.trigger('click')
    await item.trigger('click')
    expect(notificationApi.markRead).toHaveBeenCalledOnce()
    resolveRead()
    await flushPromises()
    expect(notificationStore.decreaseUnread).toHaveBeenCalledOnce()
    expect(notificationStore.loadUnread).toHaveBeenCalledTimes(2)
    expect(wrapper.find('.notif-detail__facts').text()).toContain('业务记录 #22')

    const retryRecord = row(2, 'APPROVAL', { isRead: 0 })
    notificationApi.myNotifications.mockResolvedValue(page([retryRecord]))
    notificationApi.markRead.mockRejectedValueOnce(new Error('write failed')).mockResolvedValueOnce(undefined)
    await wrapper.find('.filter-all').trigger('click')
    await flushPromises()
    await wrapper.find('.notif-row').trigger('click')
    await flushPromises()
    await wrapper.find('.notif-row').trigger('click')
    await flushPromises()
    expect(notificationApi.markRead).toHaveBeenCalledTimes(3)
    expect(notificationStore.decreaseUnread).toHaveBeenCalledTimes(2)
  })

  it('renders the empty notification state and handles list-load errors without a pager', async () => {
    notificationApi.myNotifications.mockResolvedValue(page([]))
    const empty = mountPage()
    await flushPromises()
    expect(empty.find('.empty-state').text()).toBe('暂无通知')
    expect(empty.find('.notif-page__pager').exists()).toBe(false)

    notificationApi.myNotifications.mockRejectedValue(new Error('offline'))
    const failed = mountPage()
    await flushPromises()
    expect(failed.find('.empty-state').exists()).toBe(true)
    expect(failed.find('.notif-page__pager').exists()).toBe(false)
    expect(reveal).toHaveBeenCalled()
  })
})
