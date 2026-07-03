<script setup lang="ts">
// 根 App 壳：仅挂载路由出口。
// Cal.com 主题层（CSS 变量、字体、.lab-card、html/body/#app 高度重置）由 main.ts 引入的
// styles/theme.scss 全局提供，这里不再写 scoped 样式，保持壳层透明。
</script>

<template>
  <router-view />
</template>
