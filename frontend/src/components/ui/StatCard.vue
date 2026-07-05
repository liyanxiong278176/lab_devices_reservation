<script setup lang="ts">
// StatCard — 驾驶舱指标卡
// 设计 spec §5 + plan Task R1.3:
//   - 数字 count-up(useCountUp)+ inView 激活(useIntersectionObserver)
//   - label/unit/trend(up=success/down=danger)/icon(青色 tint chip)
//   - 全量走 token,scoped scss,JetBrains Mono 数字
import { computed, ref, toRef, type Component } from 'vue'
import { useIntersectionObserver } from '@vueuse/core'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import { useCountUp } from '@/composables/useCountUp'

interface Trend {
  delta: number
  dir: 'up' | 'down'
}

const props = withDefaults(
  defineProps<{
    /** 目标值,会 count-up */
    value: number
    /** 指标名,如 "设备总数" */
    label: string
    /** 单位,如 "台" / "%" */
    unit?: string
    /** 趋势:delta 数值,dir 决定绿(up)/红(down) */
    trend?: Trend
    /** EP icon 名,如 "Monitor",渲染在青色 tint chip */
    icon?: string
    /** 数字小数位,默认 0 */
    decimals?: number
  }>(),
  { decimals: 0 },
)

// 卡片根, IntersectionObserver 目标
const rootEl = ref<HTMLElement | null>(null)
const inView = ref(false)

useIntersectionObserver(rootEl, ([entry]) => {
  if (entry?.isIntersecting) inView.value = true
})

// 数字动画;active=inView(进入视口才激活;命中 reduced-motion 时 useCountUp 内部直跳)
// holdWhenInactive=true:卡片未滚入视口前 hold 在初值 0,滚入后才 count-up,
// 否则一挂载就跳 target,等 inView 翻 true 时 from===to 不会有入场滚动。
const display = useCountUp(toRef(props, 'value'), { active: inView, holdWhenInactive: true })

const formatted = computed(() => display.value.toFixed(props.decimals))

// 动态解析 EP icon 名 → 组件(名不存在时降级为 null,不渲染 chip)
const iconComp = computed<Component | null>(() => {
  if (!props.icon) return null
  return (ElementPlusIconsVue as Record<string, Component>)[props.icon] ?? null
})

// trend 文字:up 显示 +delta,down 显示 -delta(箭头另由 dir 决定)
const trendSign = computed(() => (props.trend?.dir === 'down' ? '-' : '+'))
</script>

<template>
  <div ref="rootEl" class="stat-card">
    <div v-if="iconComp" class="stat-card__icon">
      <component :is="iconComp" />
    </div>
    <div class="stat-card__body">
      <div class="stat-card__label">{{ label }}</div>
      <div class="stat-card__value-row">
        <span class="stat-card__value">{{ formatted }}</span>
        <span v-if="unit" class="stat-card__unit">{{ unit }}</span>
      </div>
      <div
        v-if="trend"
        class="stat-card__trend"
        :class="`stat-card__trend--${trend.dir}`"
      >
        <span class="stat-card__trend-arrow">{{ trend.dir === 'up' ? '↑' : '↓' }}</span>
        <span class="stat-card__trend-delta">{{ trendSign }}{{ trend.delta }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.stat-card {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 20px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-soft-light);
  transition:
    transform var(--d-med) var(--ease-out-expo),
    box-shadow var(--d-med) var(--ease-out-expo),
    border-color var(--d-med) var(--ease-out-expo);

  &:hover {
    transform: translateY(-2px);
    border-color: var(--border-strong);
    box-shadow: var(--shadow-soft);
  }

  // icon chip:青色 rgba(.12) 底 + 青色图标,圆角 8px,~36px
  &__icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    flex: 0 0 36px;
    border-radius: var(--radius-control);
    color: var(--accent);
    background: rgba(34, 211, 238, 0.12); // --accent @ .12(spec §5 青色 tint)
    font-size: 18px;
  }

  &__body {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  &__label {
    color: var(--text-secondary);
    font-size: 12px;
    line-height: 1.4;
    letter-spacing: 0.02em;
  }

  &__value-row {
    display: flex;
    align-items: baseline;
    gap: 6px;
  }

  // 数字:JetBrains Mono、大号、primary、weight 600
  &__value {
    color: var(--text-primary);
    font-family: var(--font-mono);
    font-size: 36px;
    font-weight: 600;
    line-height: 1.1;
    letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums;
  }

  &__unit {
    color: var(--text-secondary);
    font-size: 14px;
    font-family: var(--font-mono);
  }

  // trend:up=success(绿) / down=danger(红)
  &__trend {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: 4px;
    font-size: 13px;
    font-family: var(--font-mono);
    font-weight: 500;
    line-height: 1;

    &--up {
      color: var(--status-success);
    }
    &--down {
      color: var(--status-danger);
    }
  }

  &__trend-arrow {
    font-size: 14px;
    line-height: 1;
  }
}
</style>
