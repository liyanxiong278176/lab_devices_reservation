import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const api = vi.hoisted(() => ({ getRecommendations: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn() }))
const reveal = vi.hoisted(() => vi.fn())
vi.mock('@/api/recommendation', () => api)
vi.mock('vue-router', () => ({ useRouter: () => router }))
vi.mock('@/router', () => ({ readSpaDepth: () => 0 }))
vi.mock('@/composables/useStagger', () => ({ useStagger: () => ({ reveal }) }))

import RecommendationPage from '../Index.vue'

const stubs = {
  PageHeader: { props: ['title', 'subtitle'], template: '<header :data-subtitle="subtitle">{{ title }}</header>' },
  GlowCard: {
    inheritAttrs: false,
    template: '<article class="rec-card" @click="$emit(\'click\')"><slot /></article>',
  },
  StatusDot: { props: ['status', 'label'], template: '<span class="status-dot" :data-status="status" />' },
  Tag: { props: ['variant'], template: '<span class="tag" :data-variant="variant"><slot /></span>' },
  TextButton: {
    inheritAttrs: false,
    template: '<button class="reserve" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  EmptyState: { props: ['title'], template: '<div class="empty-state">{{ title }}</div>' },
}

describe('recommendation page decisions and actions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    router.push.mockResolvedValue(undefined)
  })

  it('renders cold-start suggestions, optional card fields and both navigation actions', async () => {
    api.getRecommendations.mockResolvedValue([
      {
        deviceId: 4, name: 'Microscope', brand: 'Acme', model: 'M-4', status: undefined,
        score: 0.75, reason: '近30天热门设备', categoryName: 'Optics', labName: 'North Lab', pricePerHour: 8,
      },
      {
        deviceId: 5, name: 'Centrifuge', brand: '', model: '', status: 'IN_USE',
        score: 0, reason: '', categoryName: undefined, labName: undefined, pricePerHour: null,
      },
    ])
    const wrapper = mount(RecommendationPage, { global: { stubs, directives: { loading: () => {} } } })
    await flushPromises()

    expect(api.getRecommendations).toHaveBeenCalledWith(10)
    expect(reveal).toHaveBeenCalledOnce()
    expect(wrapper.find('.rec-page__hint').exists()).toBe(true)
    expect(wrapper.find('header').attributes('data-subtitle')).toContain('热门为你推荐')
    expect(wrapper.findAll('.rec-card')).toHaveLength(2)
    expect(wrapper.findAll('.status-dot').map((node) => node.attributes('data-status'))).toEqual(['IDLE', 'IN_USE'])
    expect(wrapper.findAll('.rec-card__score-num').map((node) => node.text())).toEqual(['75%'])
    expect(wrapper.findAll('.rec-card__brand').map((node) => node.text())).toEqual(['Acme'])
    expect(wrapper.findAll('.rec-card__model').map((node) => node.text())).toEqual(['M-4', 'Centrifuge'])
    expect(wrapper.findAll('.tag')).toHaveLength(3)
    expect(wrapper.findAll('.rec-card__price')).toHaveLength(1)

    await wrapper.findAll('.rec-card').at(0)!.trigger('click')
    expect(router.push).toHaveBeenCalledWith({ name: 'device-detail', params: { id: 4 } })
    await wrapper.findAll('.reserve').at(1)!.trigger('click')
    expect(router.push).toHaveBeenLastCalledWith({ name: 'reservation-create', query: { deviceId: '5' } })
  })

  it('uses personalized copy when at least one recommendation has a concrete reason', async () => {
    api.getRecommendations.mockResolvedValue([{
      deviceId: 8, name: 'Spectrometer', status: 'IDLE', score: 0.25,
      reason: '与你常用设备相似', categoryName: 'Analysis', labName: 'Lab A',
    }])
    const wrapper = mount(RecommendationPage, { global: { stubs, directives: { loading: () => {} } } })
    await flushPromises()
    expect(wrapper.find('.rec-page__hint').exists()).toBe(false)
    expect(wrapper.find('header').attributes('data-subtitle')).toContain('使用偏好')
    expect(wrapper.findAll('.tag')).toHaveLength(3)
    expect(wrapper.find('.rec-card__score-num').text()).toBe('25%')
  })

  it('shows the empty state after an empty response or a failed request', async () => {
    api.getRecommendations.mockResolvedValueOnce([])
    const empty = mount(RecommendationPage, { global: { stubs, directives: { loading: () => {} } } })
    await flushPromises()
    expect(empty.find('.empty-state').text()).toBe('暂无推荐')
    expect(reveal).toHaveBeenCalledOnce()

    vi.clearAllMocks()
    api.getRecommendations.mockRejectedValue(new Error('offline'))
    const failed = mount(RecommendationPage, { global: { stubs, directives: { loading: () => {} } } })
    await flushPromises()
    expect(failed.find('.empty-state').exists()).toBe(true)
    expect(reveal).not.toHaveBeenCalled()
  })
})
