<script setup lang="ts">
// 根 App 壳:全局氛围光层 + 顶层 router-view 页面 transition。
// .aurora-bg(含 @keyframes aurora 动画)与 .page-enter-*/.page-leave-* 过渡类
// 由 styles/_motion.scss 全局提供(main.ts 经 theme.scss 引入),此处不重复定义,
// 只确保 router-view 渲染的页面压在氛围光之上(z-index)。
// 主题层(CSS 变量/字体/.lab-card/html,body,#app 高度重置)仍由 theme.scss 提供。
</script>

<template>
  <div class="app-shell">
    <div class="aurora-bg" aria-hidden="true" />
    <router-view v-slot="{ Component }">
      <transition name="page">
        <component :is="Component" />
      </transition>
    </router-view>
  </div>
</template>

<style scoped lang="scss">
.app-shell {
  position: relative;
  min-height: 100vh;
}

// router-view 渲染的页面(MainLayout / Login / …)压在 .aurora-bg 之上。
// _motion.scss 的 .aurora-bg 是 fixed + z-index:0(处于定位层,
// 会盖住 in-flow 静态块),故此处显式把非氛围光子节点提到 z-index:1。
// <transition> 不引入包裹元素,直接目标 .app-shell 中除氛围光外的子节点即可。
.app-shell > :not(.aurora-bg) {
  position: relative;
  z-index: 1;
}
</style>
