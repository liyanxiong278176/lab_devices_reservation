<script setup lang="ts">
import Admin from './Admin.vue'
</script>

<template>
  <!--
    LAB_ADMIN 与 SYS_ADMIN 共用同一组富指标看板；后端按 JWT 角色自动收窄数据范围
    （LAB_ADMIN 仅见本实验室设备/预约）。如未来需差异化裁剪组件，可在此分叉。
  -->
  <Admin />
</template>
