<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Bell } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useAppStore } from '@/stores/app'
import { useNotificationStore } from '@/stores/notification'
import { connectWs, disconnectWs } from '@/composables/useWebSocket'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const appStore = useAppStore()
const notifStore = useNotificationStore()

// 通知未读数轮询（S1 兜底）+ S3 STOMP 长连接
let notifTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  notifStore.loadUnread()
  notifTimer = setInterval(() => notifStore.loadUnread(), 30000)
  connectWs()
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

// Build the menu from routes that declare meta.title; filter by role intersection
// when meta.roles is set (no roles meta ⇒ show to everyone).
const menuItems = computed<MenuItem[]>(() => {
  const root = router.options.routes.find((r) => r.path === '/')
  const children = root?.children || []
  return children
    .filter((c) => c.meta?.title)
    // hidden 路由（设备详情/建预约/预约详情）不进侧边栏菜单
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

const displayName = computed(
  () => userStore.realName || userStore.username || '用户',
)

function onLogout() {
  disconnectWs()
  userStore.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}
</script>

<template>
  <el-container class="layout">
    <div class="layout__aura" aria-hidden="true"></div>
    <el-aside :width="appStore.sidebarCollapsed ? '64px' : '220px'" class="layout__aside">
      <div class="layout__brand">
        <span class="layout__pulse-dot" aria-hidden="true"></span>
        <span v-if="!appStore.sidebarCollapsed" class="layout__brand-text">实验室预约</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        :collapse="appStore.sidebarCollapsed"
        router
        class="layout__menu"
      >
        <el-menu-item v-for="item in menuItems" :key="item.path" :index="item.path">
          <el-icon v-if="item.icon">
            <component :is="item.icon" />
          </el-icon>
          <template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container class="layout__body">
      <el-header class="layout__header">
        <div class="layout__header-left">
          <el-icon class="layout__collapse" @click="appStore.toggleSidebar()">
            <Fold v-if="!appStore.sidebarCollapsed" />
            <Expand v-else />
          </el-icon>
          <span class="layout__title">实验室预约系统</span>
        </div>
        <div class="layout__header-right">
          <el-badge
            :value="notifStore.unread"
            :hidden="notifStore.unread === 0"
            :max="99"
            class="layout__notif"
          >
            <el-icon class="layout__bell" @click="router.push('/notifications')">
              <Bell />
            </el-icon>
          </el-badge>
          <span class="layout__user">{{ displayName }}</span>
          <el-button text @click="onLogout">退出登录</el-button>
        </div>
      </el-header>

      <el-main class="layout__main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped lang="scss">
// ============================================================================
// MainLayout 深色科技壳 (spec §4)
// 全部走 token(--bg-*/--border-*/--text-*/--accent/--font-display),
// 不留任何 Cal.com 浅色硬编码(#e5e7eb/#f8f9fa/#ffffff/#111111 已全部清除)。
// script setup 零改;仅 template 加脉冲点 span + 氛围光层,scoped style 全量重写。
// ============================================================================

// 品牌脉冲点(logo 替代):青色 + CSS 脉冲动画(GPU only:opacity/scale)
@keyframes layout-pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(34, 211, 238, 0.55);
    transform: scale(1);
  }
  70% {
    box-shadow: 0 0 0 6px rgba(34, 211, 238, 0);
    transform: scale(1.08);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(34, 211, 238, 0);
    transform: scale(1);
  }
}

.layout {
  height: 100vh;
  position: relative;
  // 给氛围光层一个独立栈,保证 sticky 顶栏 backdrop-filter 能透出底层辉光
  z-index: 0;
}

// ---- 全局氛围光(spec §4):fixed、极弱青色径向、所有页面底层共氛围 ----
.layout__aura {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background:
    radial-gradient(circle at 12% 8%, rgba(34, 211, 238, 0.06), transparent 45%),
    radial-gradient(circle at 88% 92%, rgba(59, 130, 246, 0.04), transparent 50%);
}

// ---- 侧栏:比主区更深的 sunken 底 + 右侧 hairline ----------------------------
.layout__aside {
  position: relative;
  z-index: 1;
  background: var(--bg-sunken);
  border-right: 1px solid var(--border-default);
  transition: width var(--d-med) var(--ease-out-expo);
  overflow: hidden;
}

// 品牌区:Space Grotesk 展示字 + 青色脉冲点 logo
.layout__brand {
  height: 60px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px;
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-subtle);
  white-space: nowrap;
}

.layout__brand-text {
  // 折叠时由父 aside width 收窄自然裁切,这里仅保证不换行
  overflow: hidden;
  text-overflow: ellipsis;
}

// 青色脉冲点(折叠态也保留作 logo)
.layout__pulse-dot {
  flex: none;
  width: 10px;
  height: 10px;
  border-radius: var(--radius-pill);
  background: var(--accent);
  animation: layout-pulse 2.4s var(--ease-out-expo) infinite;
  will-change: transform, box-shadow;
}

// ---- Element Plus 菜单:覆盖 --el-menu-* 暗色变量 ---------------------------
.layout__menu {
  // EP 菜单暗色变量覆盖(变量直接写在组件根,EP 内部 var() 自动继承)
  --el-menu-bg-color: transparent;
  --el-menu-text-color: var(--text-secondary);
  --el-menu-hover-bg-color: var(--bg-elevated);
  --el-menu-hover-text-color: var(--text-primary);
  --el-menu-active-color: var(--accent);
  border-right: none;
  background: transparent;
  padding: 8px;
}

// 菜单项:圆角 + hover 抬升面
:deep(.el-menu-item) {
  height: 44px;
  line-height: 44px;
  margin: 2px 0;
  border-radius: var(--radius-control);
  color: var(--text-secondary);
  transition:
    background var(--d-fast) var(--ease-out-expo),
    color var(--d-fast) var(--ease-out-expo);

  &:hover {
    background: var(--bg-elevated);
    color: var(--text-primary);
  }

  .el-icon {
    color: inherit;
  }
}

// active 项:左侧 2px 青色指示条(box-shadow inset) + 抬升面 + 青色图标
// (覆盖 EP 默认底部 border 指示,改为科技风左条)
:deep(.el-menu-item.is-active) {
  position: relative;
  background: var(--bg-elevated);
  color: var(--accent);

  // 左侧青色指示条(inset box-shadow 不占布局、不触发 layout)
  box-shadow: inset 2px 0 0 var(--accent);

  .el-icon {
    color: var(--accent);
  }
}

// ---- 主体列(让 sticky header 在此列内生效) --------------------------------
.layout__body {
  position: relative;
  z-index: 1;
  // 让 header sticky 有滚动容器可粘:el-main 自带 overflow:auto
  min-width: 0;
}

// ---- 顶栏:半透明毛玻璃 + sticky + 底 hairline ------------------------------
.layout__header {
  position: sticky;
  top: 0;
  z-index: 10;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  // 半透明底 + 毛玻璃:透出底层氛围光
  background: rgba(17, 23, 34, 0.72); // --bg-surface 透明化
  backdrop-filter: blur(12px) saturate(140%);
  -webkit-backdrop-filter: blur(12px) saturate(140%);
  border-bottom: 1px solid var(--border-default);
}

.layout__header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.layout__collapse {
  font-size: 20px;
  cursor: pointer;
  color: var(--text-secondary);
  transition: color var(--d-fast) var(--ease-out-expo);

  &:hover {
    color: var(--accent);
  }
}

.layout__title {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--text-primary);
}

.layout__header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.layout__notif {
  margin-right: 4px;
}

// 未读徽章走青色(token 已把 --el-color-primary 桥到 --accent,这里兜底锁字色)
:deep(.layout__notif .el-badge__content) {
  background: var(--accent);
  color: var(--text-on-accent);
  border: none;
}

.layout__bell {
  font-size: 20px;
  cursor: pointer;
  color: var(--text-secondary);
  transition: color var(--d-fast) var(--ease-out-expo);

  &:hover {
    color: var(--accent);
  }
}

// 用户名:作在线状态 pill(左侧青色点 = 在环暗示)
.layout__user {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);

  &::before {
    content: '';
    flex: none;
    width: 8px;
    height: 8px;
    border-radius: var(--radius-pill);
    background: var(--accent);
    box-shadow: 0 0 0 2px rgba(34, 211, 238, 0.25);
  }
}

// 退出按钮深色调(text 按钮走 EP,hover 由 token 自动变青)
:deep(.el-button.is-text) {
  color: var(--text-secondary);

  &:hover {
    color: var(--accent);
    background: transparent;
  }
}

// ---- 主区:bg-base + 24px 内边距(保留) -----------------------------------
.layout__main {
  padding: 24px;
  background: var(--bg-base);
  color: var(--text-primary);
}

// ============================================================================
// prefers-reduced-motion 兜底(spec §6.1 铁律):命中则关脉冲动画
// ============================================================================
@media (prefers-reduced-motion: reduce) {
  .layout__pulse-dot {
    animation: none;
  }
  .layout__aside,
  .layout__collapse,
  .layout__bell,
  :deep(.el-menu-item) {
    transition: none;
  }
}
</style>
