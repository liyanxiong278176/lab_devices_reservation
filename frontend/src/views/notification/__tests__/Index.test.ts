import { defineComponent, h } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const notificationApi = vi.hoisted(() => ({
  markAllRead: vi.fn(),
  markRead: vi.fn(),
  myNotifications: vi.fn(),
}))

const notificationStore = vi.hoisted(() => ({
  decreaseUnread: vi.fn(),
  clearUnread: vi.fn(),
  loadUnread: vi.fn(),
}))

vi.mock('@/api/notification', () => notificationApi)
vi.mock('@/stores/notification', () => ({
  useNotificationStore: () => notificationStore,
}))
vi.mock('@/composables/useStagger', () => ({
  useStagger: () => ({ reveal: vi.fn() }),
}))

import NotificationIndex from '../Index.vue'

const FilterStub = defineComponent({
  emits: ['update:modelValue'],
  setup(_, { emit }) {
    return () =>
      h(
        'button',
        {
          'data-testid': 'unread-filter',
          onClick: () => emit('update:modelValue', 'unread'),
        },
        '未读',
      )
  },
})

const DrawerStub = defineComponent({
  props: { modelValue: { type: Boolean, default: false } },
  emits: ['update:modelValue'],
  setup(props, { slots }) {
    return () =>
      h(
        'aside',
        { 'data-testid': 'notification-detail', hidden: !props.modelValue },
        props.modelValue ? slots.default?.() : [],
      )
  },
})

const allNotifications = [
  {
    id: 1,
    userId: 2,
    type: 'REPAIR_UPDATE',
    title: '报修工单状态已更新',
    content: '设备维修已完成。',
    isRead: 0,
    createdAt: '2026-09-19T20:33:00',
  },
]

const page = (records: typeof allNotifications) => ({
  records,
  total: records.length,
  size: 10,
  current: 1,
})

const unreadRecords = () => allNotifications.map((record) => ({ ...record, isRead: 0 }))

describe('notification list read behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    let read = false
    notificationApi.markRead.mockImplementation(async () => {
      read = true
    })
    notificationApi.markAllRead.mockResolvedValue(undefined)
    notificationStore.loadUnread.mockResolvedValue(undefined)
    notificationApi.myNotifications.mockImplementation(async (params?: { onlyUnread?: boolean }) => {
      if (params?.onlyUnread) return read ? page([]) : page(unreadRecords())
      return page(unreadRecords())
    })
  })

  it('keeps a notification visible after clicking it in the unread filter', async () => {
    const wrapper = mount(NotificationIndex, {
      global: {
        stubs: {
          PageHeader: defineComponent({ template: '<header><slot name="actions" /></header>' }),
          GhostButton: defineComponent({ template: '<button><slot /></button>' }),
          Tag: defineComponent({ template: '<span><slot /></span>' }),
          EmptyState: defineComponent({ template: '<div />' }),
          SegmentedControl: FilterStub,
          'el-drawer': DrawerStub,
          'el-pagination': true,
        },
        directives: { loading: () => undefined },
      },
    })

    await flushPromises()
    expect(notificationStore.loadUnread).toHaveBeenCalledTimes(1)
    await wrapper.get('[data-testid="unread-filter"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.notif-row')).toHaveLength(1)

    await wrapper.get('.notif-row').trigger('click')
    await flushPromises()

    expect(notificationApi.markRead).toHaveBeenCalledWith(1)
    expect(notificationStore.decreaseUnread).toHaveBeenCalledTimes(1)
    expect(notificationStore.loadUnread).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('.notif-row')).toHaveLength(1)
    expect(wrapper.get('.notif-row').attributes('data-read')).toBe('read')
    expect(wrapper.get('[data-testid="notification-detail"]').attributes('hidden')).toBeUndefined()
    expect(wrapper.get('.notif-detail__message').text()).toBe('设备维修已完成。')
    expect(wrapper.get('.notif-detail__facts').text()).toContain('通知时间')
  })

  it('opens details for an already-read notification without marking it again', async () => {
    notificationApi.myNotifications.mockImplementation(async () => page([{ ...allNotifications[0], isRead: 1 }]))
    const wrapper = mount(NotificationIndex, {
      global: {
        stubs: {
          PageHeader: defineComponent({ template: '<header><slot name="actions" /></header>' }),
          GhostButton: defineComponent({ template: '<button><slot /></button>' }),
          Tag: defineComponent({ template: '<span><slot /></span>' }),
          EmptyState: defineComponent({ template: '<div />' }),
          SegmentedControl: FilterStub,
          'el-drawer': DrawerStub,
          'el-pagination': true,
        },
        directives: { loading: () => undefined },
      },
    })

    await flushPromises()
    await wrapper.get('.notif-row').trigger('click')
    await flushPromises()

    expect(notificationApi.markRead).not.toHaveBeenCalled()
    expect(wrapper.get('.notif-detail__message').text()).toBe('设备维修已完成。')
  })
})
