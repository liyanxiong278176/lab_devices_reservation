<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Bell, Expand, Fold, Moon, Sunny } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useAppStore } from '@/stores/app'
import { useNotificationStore } from '@/stores/notification'
import { useThemeStore } from '@/stores/theme'
import { connectWs, disconnectWs } from '@/composables/useWebSocket'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const appStore = useAppStore()
const notifStore = useNotificationStore()
const themeStore = useThemeStore()

let notifTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  notifStore.loadUnread()
  connectWs()
  notifTimer = setInterval(() => notifStore.loadUnread(), 30000)
})
onUnmounted(() => {
  if (notifTimer) clearInterval(notifTimer)
  disconnectWs()
})

interface MenuItem {
  path: string
  title: string
  icon?: string
}

const menuItems = computed<MenuItem[]>(() => {
  const root = router.options.routes.find((r) => r.path === '/')
  const children = root?.children || []
  return children
    .filter((c) => c.meta?.title)
    .filter((c) => !(c.meta as Record<string, unknown>)?.hidden)
    .filter((c) => {
      const need = c.meta?.roles as string[] | undefined
      if (!need || need.length === 0) return true
      return need.some((r) => userStore.roles.includes(r))
    })
    .map((c) => ({
      path: `/${c.path}`,
      title: c.meta!.title as string,
      icon: c.meta?.icon as string | undefined,
    }))
})

const activeMenu = computed(() => route.path)
const displayName = computed(() => userStore.realName || userStore.username || '用户')
const themeLabel = computed(() => (themeStore.isDark ? '切换浅色' : '切换深色'))

function onLogout() {
  userStore.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}

function toggleTheme() {
  themeStore.toggle()
}
</script>

<template>
  <el-container
    class="layout"
    :class="{ 'layout--rail': appStore.sidebarCollapsed, 'layout--expanded': !appStore.sidebarCollapsed }"
  >
    <el-aside
      :width="appStore.sidebarCollapsed ? '88px' : '248px'"
      class="layout__aside"
    >
      <div class="layout__brand">
        <span class="layout__brand-mark" aria-hidden="true">
          <span class="layout__brand-ring"></span>
          <span class="layout__brand-signal"></span>
        </span>
        <span v-if="!appStore.sidebarCollapsed" class="layout__brand-copy">
          <strong>LABFLOW</strong>
          <small>实验室预约</small>
        </span>
      </div>

      <div v-if="!appStore.sidebarCollapsed" class="layout__nav-caption">WORKSPACE</div>
      <el-menu
        :default-active="activeMenu"
        :collapse="appStore.sidebarCollapsed"
        router
        class="layout__menu"
      >
        <el-menu-item
          v-for="item in menuItems"
          :key="item.path"
          :index="item.path"
          :aria-label="item.title"
        >
          <el-icon v-if="item.icon"><component :is="item.icon" /></el-icon>
          <template v-if="!appStore.sidebarCollapsed" #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>

      <div class="layout__aside-note" :title="appStore.sidebarCollapsed ? '实验室运营空间' : undefined">
        <span class="layout__aside-note-dot"></span>
        <span v-if="!appStore.sidebarCollapsed">实验室运营空间</span>
      </div>
    </el-aside>

    <el-container class="layout__body">
      <el-header class="layout__header">
        <div class="layout__header-left">
          <button
            type="button"
            class="layout__collapse"
            :aria-label="appStore.sidebarCollapsed ? '展开导航' : '收起导航'"
            @click="appStore.toggleSidebar()"
          >
            <el-icon><Fold v-if="!appStore.sidebarCollapsed" /><Expand v-else /></el-icon>
          </button>
          <div class="layout__context">
            <span class="layout__eyebrow">LABFLOW / WORKSPACE</span>
            <span class="layout__title">实验室预约系统</span>
          </div>
        </div>

        <div class="layout__header-right">
          <button
            type="button"
            class="layout__theme-toggle"
            :aria-label="themeLabel"
            :title="themeLabel"
            @click="toggleTheme"
          >
            <el-icon><Sunny v-if="themeStore.isDark" /><Moon v-else /></el-icon>
            <span>{{ themeStore.isDark ? '浅色' : '深色' }}</span>
          </button>

          <button
            type="button"
            class="layout__icon-button"
            aria-label="打开通知"
            @click="router.push('/notifications')"
          >
            <el-badge
              :value="notifStore.unread"
              :hidden="notifStore.unread === 0"
              :max="99"
            >
              <el-icon><Bell /></el-icon>
            </el-badge>
          </button>

          <div class="layout__user" :title="displayName">
            <span class="layout__user-mark">{{ displayName.slice(0, 1) }}</span>
            <span class="layout__user-name">{{ displayName }}</span>
          </div>
          <el-button text @click="onLogout">退出登录</el-button>
        </div>
      </el-header>

      <el-main class="layout__main">
        <div class="layout__canvas">
          <router-view />
        </div>
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped lang="scss">
.layout {
  min-height: 100vh;
  background: transparent;
}

.layout__aside {
  position: relative;
  z-index: 20;
  display: flex;
  flex-direction: column;
  flex: none;
  min-height: 100vh;
  overflow: hidden;
  background: color-mix(in srgb, var(--bg-surface) 84%, transparent);
  border-right: 1px solid var(--border-subtle);
  box-shadow: 12px 0 38px color-mix(in srgb, var(--text-primary) 4%, transparent);
  backdrop-filter: blur(22px) saturate(120%);
  transition: width var(--d-med) var(--ease-out-expo), background-color var(--d-med) var(--ease-out-expo);
}

.layout__brand {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 86px;
  padding: 0 20px;
  border-bottom: 1px solid var(--border-subtle);
}

.layout__brand-mark {
  position: relative;
  display: inline-grid;
  width: 38px;
  height: 38px;
  flex: none;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--accent) 50%, transparent);
  border-radius: 14px;
  background: color-mix(in srgb, var(--accent) 7%, var(--bg-surface));
  box-shadow: 0 8px 24px color-mix(in srgb, var(--accent) 13%, transparent);
}

.layout__brand-ring {
  width: 17px;
  height: 17px;
  border: 1.5px solid var(--accent);
  border-radius: 50%;
}

.layout__brand-signal {
  position: absolute;
  right: 8px;
  bottom: 8px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 13%, transparent);
}

.layout__brand-copy {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.layout__brand-copy strong {
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: 13px;
  letter-spacing: 0.16em;
}

.layout__brand-copy small {
  color: var(--text-tertiary);
  font-size: 11px;
  letter-spacing: 0.06em;
}

.layout__nav-caption {
  padding: 26px 24px 10px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.16em;
}

.layout__menu {
  flex: 1;
  width: 100%;
  padding: 0 12px;
  border-right: 0;
}

:deep(.layout__menu .el-menu-item) {
  height: 46px;
  margin: 4px 0;
  padding: 0 13px !important;
  border-radius: 14px;
  color: var(--text-tertiary);
  transition: background-color var(--d-fast) var(--ease-out-expo), color var(--d-fast) var(--ease-out-expo), transform var(--d-fast) var(--ease-out-expo);
}

:deep(.layout__menu .el-menu-item:hover) {
  color: var(--text-primary);
  background: color-mix(in srgb, var(--accent) 7%, transparent);
  transform: translateX(2px);
}

:deep(.layout__menu .el-menu-item.is-active) {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 16%, transparent);
}

:deep(.layout__menu .el-menu-item.is-active::before) {
  position: absolute;
  left: 0;
  width: 3px;
  height: 22px;
  border-radius: 0 999px 999px 0;
  background: var(--accent);
  content: '';
}

:deep(.layout__menu .el-menu-item .el-icon) {
  margin-right: 12px;
  color: inherit;
  font-size: 18px;
}

.layout--rail .layout__menu {
  padding-inline: 12px;
}

.layout--rail :deep(.layout__menu .el-menu-item) {
  justify-content: center;
  padding-inline: 0 !important;
}

.layout--rail :deep(.layout__menu .el-menu-item .el-icon) {
  margin-right: 0;
}

.layout__aside-note {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 62px;
  padding: 0 24px;
  border-top: 1px solid var(--border-subtle);
  color: var(--text-tertiary);
  font-size: 11px;
  white-space: nowrap;
}

.layout--rail .layout__aside-note {
  justify-content: center;
  padding: 0;
}

.layout__aside-note-dot {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 50%;
  background: var(--status-success);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--status-success) 12%, transparent);
}

.layout__body {
  min-width: 0;
  min-height: 100vh;
  background: transparent;
}

.layout__header {
  position: sticky;
  top: 0;
  z-index: 15;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 86px;
  padding: 0 clamp(24px, 4vw, 64px);
  background: color-mix(in srgb, var(--bg-base) 78%, transparent);
  border-bottom: 1px solid var(--border-subtle);
  backdrop-filter: blur(20px) saturate(125%);
  -webkit-backdrop-filter: blur(20px) saturate(125%);
}

.layout__header-left,
.layout__header-right,
.layout__context,
.layout__user,
.layout__theme-toggle,
.layout__icon-button {
  display: flex;
  align-items: center;
}

.layout__header-left {
  gap: 16px;
  min-width: 0;
}

.layout__collapse,
.layout__theme-toggle,
.layout__icon-button {
  justify-content: center;
  border: 0;
  cursor: pointer;
}

.layout__collapse {
  width: 38px;
  height: 38px;
  flex: none;
  border-radius: 12px;
  color: var(--text-secondary);
  background: transparent;
  transition: color var(--d-fast) var(--ease-out-expo), background-color var(--d-fast) var(--ease-out-expo), transform var(--d-fast) var(--ease-out-expo);
}

.layout__collapse:hover {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  transform: translateY(-1px);
}

.layout__context {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.layout__eyebrow {
  overflow: hidden;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.13em;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}

.layout__title {
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.layout__header-right {
  gap: 10px;
  min-width: 0;
}

.layout__theme-toggle {
  gap: 7px;
  min-height: 36px;
  padding: 0 11px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  color: var(--text-secondary);
  background: color-mix(in srgb, var(--bg-surface) 75%, transparent);
  font-size: 12px;
  font-weight: 600;
  transition: color var(--d-fast) var(--ease-out-expo), border-color var(--d-fast) var(--ease-out-expo), background-color var(--d-fast) var(--ease-out-expo), transform var(--d-fast) var(--ease-out-expo);
}

.layout__theme-toggle:hover {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 32%, var(--border-default));
  background: color-mix(in srgb, var(--accent) 7%, var(--bg-surface));
  transform: translateY(-1px);
}

.layout__icon-button {
  width: 38px;
  height: 38px;
  color: var(--text-secondary);
  background: transparent;
  border-radius: 12px;
  transition: color var(--d-fast) var(--ease-out-expo), background-color var(--d-fast) var(--ease-out-expo);
}

.layout__icon-button:hover {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 7%, transparent);
}

:deep(.layout__icon-button .el-badge__content) {
  background: var(--accent);
  color: var(--text-on-accent);
  border: 2px solid var(--bg-base);
}

.layout__user {
  gap: 8px;
  max-width: 180px;
  padding: 4px 10px 4px 5px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  color: var(--text-secondary);
  background: color-mix(in srgb, var(--bg-surface) 72%, transparent);
}

.layout__user-mark {
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  flex: none;
  border-radius: 50%;
  color: var(--text-on-accent);
  background: var(--accent);
  font-size: 12px;
  font-weight: 700;
}

.layout__user-name {
  overflow: hidden;
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.layout__main {
  min-height: 0;
  padding: clamp(28px, 4vw, 60px) clamp(24px, 4vw, 64px) 64px;
  background: transparent;
}

.layout__canvas {
  width: min(100%, 1440px);
  margin: 0 auto;
}

@media (max-width: 1120px) {
  .layout__header {
    padding-inline: 28px;
  }

  .layout__main {
    padding-inline: 28px;
  }

  .layout__theme-toggle span,
  .layout__user-name {
    display: none;
  }

  .layout__theme-toggle {
    width: 38px;
    padding: 0;
  }
}

@media (max-width: 760px) {
  .layout__header {
    height: 72px;
    padding-inline: 18px;
  }

  .layout__main {
    padding: 24px 18px 48px;
  }

  .layout__title {
    font-size: 14px;
  }

  .layout__user,
  .layout__header-right > :deep(.el-button) {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .layout__aside,
  .layout__menu :deep(.el-menu-item),
  .layout__collapse,
  .layout__theme-toggle,
  .layout__icon-button {
    transition: none;
  }
}
</style>
