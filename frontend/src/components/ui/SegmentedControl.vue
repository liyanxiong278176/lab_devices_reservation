<script setup lang="ts">
// SegmentedControl — 段控件(设备筛选 / tab 切换)
// 视觉:底槽 pill(--bg-sunken 半透明) + 跟随选中项的青色滑块(Linear 风)。
// 滑块:CSS Grid 等宽列 + absolute 滑块,transform: translateX(calc(var(--i) * 100%)),
//   其中 --i = 选中 index;滑块宽 = calc(100% / 列数) 即一格。
//   jsdom 不做真 layout,--i 写在 inline style 上,测试可断言。
// reduced-motion:_motion.scss 全局守卫覆盖 transition:none,滑块瞬移。
import { computed, nextTick, ref } from 'vue'

type OptValue = string | number

interface Option {
  value: OptValue
  label?: string
  icon?: string
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    modelValue: OptValue
    options: Option[]
    size?: 'sm' | 'md'
    /** radiogroup 可访问名(屏幕阅读器朗读用,如"设备状态筛选") */
    label?: string
  }>(),
  { size: 'md' },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: OptValue): void
}>()

// 选项按钮 ref 数组(v-for ref 收集),键盘导航移动后聚焦目标
const optionEls = ref<HTMLButtonElement[]>([])

// 选中项 index(用于滑块定位与 active 标记)
const selectedIndex = computed(() => {
  const i = props.options.findIndex((o) => o.value === props.modelValue)
  return i < 0 ? 0 : i
})

const sliderStyle = computed(() => ({
  '--i': String(selectedIndex.value),
  '--n': String(props.options.length),
}))

function onSelect(opt: Option) {
  if (opt.disabled) return
  if (opt.value === props.modelValue) return
  emit('update:modelValue', opt.value)
}

// ---- 键盘导航(WAI-ARIA radiogroup 模式:Left/Up=前,Right/Down=后,Home/End=首尾)----
// 跳过 disabled,环形回绕;移动即 emit + 聚焦目标(roving tabindex)。
function nextEnabled(from: number, step: 1 | -1): number {
  const n = props.options.length
  for (let k = 1; k <= n; k++) {
    const idx = (((from + step * k) % n) + n) % n // 回绕
    if (!props.options[idx].disabled) return idx
  }
  return -1
}
function firstEnabled(): number {
  return props.options.findIndex((o) => !o.disabled)
}
function lastEnabled(): number {
  for (let i = props.options.length - 1; i >= 0; i--) {
    if (!props.options[i].disabled) return i
  }
  return -1
}
function onKeydown(e: KeyboardEvent, i: number) {
  let next = -1
  switch (e.key) {
    case 'ArrowRight':
    case 'ArrowDown':
      next = nextEnabled(i, 1); break
    case 'ArrowLeft':
    case 'ArrowUp':
      next = nextEnabled(i, -1); break
    case 'Home':
      next = firstEnabled(); break
    case 'End':
      next = lastEnabled(); break
    default:
      return
  }
  if (next >= 0 && next !== i) {
    e.preventDefault()
    emit('update:modelValue', props.options[next].value)
    void nextTick(() => optionEls.value[next]?.focus())
  }
}
</script>

<template>
  <div
    class="segmented"
    :class="[`segmented--${size}`]"
    role="radiogroup"
    :aria-label="label || '选项组'"
  >
    <span
      class="segmented__slider"
      :style="sliderStyle"
      aria-hidden="true"
    />
    <button
      v-for="(opt, i) in options"
      :key="String(opt.value)"
      :ref="(el) => { if (el) optionEls[i] = el as HTMLButtonElement }"
      type="button"
      role="radio"
      class="segmented__option"
      :class="{ 'segmented__option--active': i === selectedIndex }"
      :data-active="i === selectedIndex ? 'true' : 'false'"
      :data-value="opt.value"
      :disabled="opt.disabled"
      :aria-checked="i === selectedIndex ? 'true' : 'false'"
      :tabindex="i === selectedIndex && !opt.disabled ? 0 : -1"
      @click="onSelect(opt)"
      @keydown="onKeydown($event, i)"
    >
      <span v-if="opt.icon" class="segmented__icon" aria-hidden="true">{{ opt.icon }}</span>
      <span v-if="opt.label !== undefined" class="segmented__label">{{ opt.label }}</span>
    </button>
  </div>
</template>

<style scoped lang="scss">
// 底槽 pill:半透明下沉底 + 发丝线边 + pill 圆角
.segmented {
  position: relative;
  display: grid;
  grid-template-columns: repeat(var(--n, 1), 1fr);
  gap: 0;
  padding: 4px;
  background: var(--bg-sunken);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  // 滑块在按钮下层(z-index:-1 不可见,用 0 + 按钮透明底 + 滑块 1)
  isolation: isolate;

  // 滑块:绝对定位,translateX 跟随 --i,宽 = 一格(100% / N)
  // transform 的 100% 是滑块自身宽(= 一格),所以 i=1 → 平移 1 格
  &__slider {
    position: absolute;
    top: 4px;
    left: 4px;
    width: calc((100% - 8px) / var(--n, 1));
    height: calc(100% - 8px);
    background: var(--bg-elevated);
    border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
    border-radius: var(--radius-pill);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.04);
    transform: translateX(calc(var(--i, 0) * 100%));
    transition: transform var(--d-med) var(--ease-out-expo);
    pointer-events: none;
    z-index: 0;
  }

  &__option {
    position: relative;
    z-index: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 6px 14px;
    background: transparent;
    border: none;
    border-radius: var(--radius-pill);
    color: var(--text-secondary);
    font: inherit;
    font-weight: 500;
    cursor: pointer;
    user-select: none;
    transition: color var(--d-fast) var(--ease-out-expo);

    &:hover:not(:disabled) {
      color: var(--text-primary);
    }

    &:disabled {
      color: var(--text-tertiary);
      cursor: not-allowed;
      opacity: 0.5;
    }

    // 选中项:青字(滑块已在背后提供底)
    &--active,
    &[data-active='true'] {
      color: var(--accent);
    }
  }

  &__icon {
    font-size: 0.95em;
    line-height: 1;
  }

  // 尺寸:sm 紧凑(单行筛选条)
  &--sm &__option {
    padding: 4px 10px;
    font-size: 13px;
  }
}

// reduced-motion 守卫(spec §6.1 铁律 #3):_motion.scss 全局守卫只覆盖特定选择器,
// 滑块过渡在此 scoped 补一条,命中 reduce 时瞬移。
@media (prefers-reduced-motion: reduce) {
  .segmented__slider,
  .segmented__option {
    transition: none !important;
  }
}
</style>
