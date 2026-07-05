import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import Timeline from '../Timeline.vue'

/**
 * Timeline — 垂直时间轴(spec §5 + plan Task R1.5)
 * jsdom 不做真 layout,节点脉冲/连线只验类与 DOM 存在性,不断言像素。
 */

const ITEMS = [
  { title: '创建', status: 'done' as const, desc: '工单已建', time: '09:00' },
  { title: '审批', status: 'current' as const, desc: '主管审核中', time: '10:30' },
  { title: '签到', status: 'todo' as const, desc: '待签到', time: '——' },
]

describe('Timeline', () => {
  it('mount 渲染 items.length 项 + 含全部标题文本', () => {
    const wrapper = mount(Timeline, { props: { items: ITEMS } })
    const itemEls = wrapper.findAll('.timeline__item')
    expect(itemEls.length).toBe(3)
    expect(wrapper.text()).toContain('创建')
    expect(wrapper.text()).toContain('审批')
    expect(wrapper.text()).toContain('签到')
  })

  it('current 项(审批)带 current 状态类 + data-status="current"', () => {
    const wrapper = mount(Timeline, { props: { items: ITEMS } })
    const current = wrapper.find('.timeline__item--current')
    expect(current.exists()).toBe(true)
    expect(current.text()).toContain('审批')
    expect(current.attributes('data-status')).toBe('current')
  })

  it('desc/time 传入 → 渲染对应文本节点', () => {
    const wrapper = mount(Timeline, { props: { items: ITEMS } })
    expect(wrapper.find('.timeline__desc').exists()).toBe(true)
    expect(wrapper.find('.timeline__time').exists()).toBe(true)
    expect(wrapper.text()).toContain('工单已建')
    expect(wrapper.text()).toContain('10:30')
  })

  it('三项各自命中 done / current / todo 节点类(顺序对齐)', () => {
    const wrapper = mount(Timeline, { props: { items: ITEMS } })
    const items = wrapper.findAll('.timeline__item')
    expect(items[0].classes()).toContain('timeline__item--done')
    expect(items[1].classes()).toContain('timeline__item--current')
    expect(items[2].classes()).toContain('timeline__item--todo')
  })

  it('节点元素带状态类(done/current/todo)', () => {
    const wrapper = mount(Timeline, { props: { items: ITEMS } })
    expect(wrapper.find('.timeline__node--done').exists()).toBe(true)
    expect(wrapper.find('.timeline__node--current').exists()).toBe(true)
    expect(wrapper.find('.timeline__node--todo').exists()).toBe(true)
  })

  it('连接线只在非末项存在(末项无 .timeline__line)', () => {
    const wrapper = mount(Timeline, { props: { items: ITEMS } })
    const lines = wrapper.findAll('.timeline__line')
    expect(lines.length).toBe(2) // 3 项 → 2 条连线
    const items = wrapper.findAll('.timeline__item')
    // 末项不含连线
    expect(items[2].find('.timeline__line').exists()).toBe(false)
    // 首项含连线
    expect(items[0].find('.timeline__line').exists()).toBe(true)
  })

  it('desc/time 缺省(只给 title+status)时不渲染对应节点', () => {
    const wrapper = mount(Timeline, {
      props: {
        items: [
          { title: 'A', status: 'done' },
          { title: 'B', status: 'todo' },
        ],
      },
    })
    expect(wrapper.find('.timeline__desc').exists()).toBe(false)
    expect(wrapper.find('.timeline__time').exists()).toBe(false)
  })

  it('空 items 渲染 0 项(不抛)', () => {
    const wrapper = mount(Timeline, { props: { items: [] } })
    expect(wrapper.findAll('.timeline__item').length).toBe(0)
  })
})
