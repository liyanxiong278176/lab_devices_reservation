<script setup lang="ts">
// PageHeader — 页头:可选返回按钮 + 展示标题 + 副标题 + 右侧 actions + 可选面包屑
// 标题用 Space Grotesk(--font-display),底部 1px hairline(--border-subtle)
// back=true 时标题左侧渲染返回箭头(返回上一级 router.back),用于钻取详情/表单页。
import { useRouter } from 'vue-router'
import { readSpaDepth } from '@/router'

defineProps<{
  title: string
  subtitle?: string
  /** 是否在标题左侧显示返回按钮(钻取详情/表单页用)。点击调 router.back()。 */
  back?: boolean
}>()

const router = useRouter()
function goBack() {
  // 应用内导航深度由 router.afterEach 写入 sessionStorage 来追踪,
  // 跨刷新保留(同会话内),并避免使用 window.history.length(含外部来源页)误把用户退出 SPA。
  // 直达 URL / 外部来源点进:深度 0 → 回首页;应用内 push:深度 >=1 → router.back()。
  if (readSpaDepth() > 0) router.back()
  else router.push('/')
}
</script>

<template>
  <header class="page-header">
    <div v-if="$slots.breadcrumb" class="page-header__breadcrumb">
      <slot name="breadcrumb" />
    </div>

    <div class="page-header__main">
      <div class="page-header__heading">
        <div class="page-header__title-group">
          <button
            v-if="back"
            type="button"
            class="page-header__back"
            aria-label="返回上一级"
            @click="goBack"
          >
            <el-icon><ArrowLeft /></el-icon>
          </button>
          <h1 class="page-header__title">{{ title }}</h1>
        </div>
        <div v-if="$slots.actions" class="page-header__actions">
          <slot name="actions" />
        </div>
      </div>
      <p v-if="subtitle" class="page-header__subtitle">{{ subtitle }}</p>
    </div>
  </header>
</template>

<style scoped lang="scss">
.page-header {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--border-subtle);

  &__breadcrumb {
    font-size: 13px;
    color: var(--text-tertiary);
  }

  &__main {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  &__heading {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
  }

  // 返回按钮 + 标题成组(返回箭头紧贴标题左侧)
  &__title-group {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
  }

  // 返回箭头:无底 icon 按钮,hover 青色;尺寸对齐标题基线视觉
  &__back {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    flex: none;
    padding: 0;
    background: transparent;
    border: 1px solid var(--border-default);
    border-radius: var(--radius-control);
    color: var(--text-secondary);
    cursor: pointer;
    transition:
      color var(--d-fast) var(--ease-out-expo),
      border-color var(--d-fast) var(--ease-out-expo),
      background var(--d-fast) var(--ease-out-expo);

    .el-icon {
      font-size: 18px;
    }

    &:hover {
      color: var(--accent);
      border-color: var(--accent);
      background: color-mix(in srgb, var(--accent) 8%, transparent);
    }

    &:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }
  }

  &__title {
    margin: 0;
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 28px;
    line-height: 1.2;
    letter-spacing: -0.5px;
    color: var(--text-primary);
  }

  &__subtitle {
    margin: 0;
    font-size: 14px;
    line-height: 1.5;
    color: var(--text-secondary);
  }

  &__actions {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
}
</style>
