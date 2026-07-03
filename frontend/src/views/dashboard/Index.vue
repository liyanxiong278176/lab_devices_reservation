<script setup lang="ts">
import { computed, defineAsyncComponent } from 'vue'
import { useUserStore } from '@/stores/user'

// 角色分派：STUDENT → 学生视角；LAB_ADMIN → 实验室管理员视角；其余（SYS_ADMIN）→ 系统管理员视角。
// 后端按 JWT 自动收窄范围，前端三视角共用同一组驾驶舱组件。
const Student = defineAsyncComponent(() => import('./Student.vue'))
const LabAdmin = defineAsyncComponent(() => import('./LabAdmin.vue'))
const Admin = defineAsyncComponent(() => import('./Admin.vue'))

const u = useUserStore()
const comp = computed(() =>
  u.hasRole('STUDENT') ? Student : u.hasRole('LAB_ADMIN') ? LabAdmin : Admin,
)
</script>

<template>
  <component :is="comp" />
</template>
