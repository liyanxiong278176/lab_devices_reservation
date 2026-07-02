<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { useAppStore } from '@/stores/app'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const appStore = useAppStore()

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
  userStore.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}
</script>

<template>
  <el-container class="layout">
    <el-aside :width="appStore.sidebarCollapsed ? '64px' : '220px'" class="layout__aside">
      <div class="layout__brand">
        <span v-if="!appStore.sidebarCollapsed">实验室预约</span>
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

    <el-container>
      <el-header class="layout__header">
        <div class="layout__header-left">
          <el-icon class="layout__collapse" @click="appStore.toggleSidebar()">
            <Fold v-if="!appStore.sidebarCollapsed" />
            <Expand v-else />
          </el-icon>
          <span class="layout__title">实验室预约系统</span>
        </div>
        <div class="layout__header-right">
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
.layout {
  height: 100vh;
}

.layout__aside {
  border-right: 1px solid var(--el-border-color); // hairline #e5e7eb
  background: var(--el-bg-color); // #ffffff
  transition: width 0.2s ease;
  overflow: hidden;
}

.layout__brand {
  height: 60px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary); // #111111
  border-bottom: 1px solid var(--el-border-color-light); // hairline-soft
  white-space: nowrap;
}

.layout__menu {
  border-right: none;
}

.layout__header {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: var(--el-bg-color);
  border-bottom: 1px solid var(--el-border-color); // hairline
}

.layout__header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.layout__collapse {
  font-size: 20px;
  cursor: pointer;
  color: var(--el-text-color-regular);
}

.layout__title {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.layout__header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.layout__user {
  font-size: 14px;
  color: var(--el-text-color-secondary); // muted #6b7280
}

.layout__main {
  padding: 24px;
  background: var(--el-bg-color-page); // surface-soft #f8f9fa
}
</style>
