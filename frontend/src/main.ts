import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import ElementPlus from 'element-plus'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
// EP 暗色基础变量(必须在 dist/index.css 之后、theme.dark.scss 之前,让本项目 token 覆盖 EP 默认暗色)
import 'element-plus/theme-chalk/dark/css-vars.css'
import 'vue-echarts/style.css'
// 自托管字体(离线,答辩不依赖外网)— 仅引需要的 weight
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/space-grotesk/600.css'
import '@fontsource/jetbrains-mono/400.css'
// 本项目深色 token(必须在 EP 暗色 css-vars 之后,--el-* 覆盖才生效)
import './styles/theme.dark.scss'
// 动效 token + 通用 keyframes/工具类(在颜色 token 之后加载)
import './styles/_motion.scss'
import App from './App.vue'
import router from './router'
import { vPermission } from './directives/permission'
import { setupEcharts } from './composables/useEcharts'
import { useUserStore } from './stores/user'

// 一次性注册 echarts 按需模块（驾驶舱图表依赖）。
setupEcharts()

const app = createApp(App)
const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)
for (const [k, v] of Object.entries(ElementPlusIconsVue)) {
  app.component(k, v as any)
}
// 注册 v-permission 指令（按权限码裁剪元素）
app.directive('permission', vPermission)
app.use(pinia).use(router).use(ElementPlus)
// 固定全站深色:挂载前给 <html> 加 .dark class(EP 暗色 css-vars 由该 class 激活)
// 同时加 .js class:作为 [data-stagger] 初始态隐藏的 gate(JS 没跑则内容可见,无障碍/健壮)
document.documentElement.classList.add('dark')
document.documentElement.classList.add('js')

// 持久化的 token 在,但角色/权限可能与服务端脱节(刷新后,或 localStorage 是旧形状
// 没有 roles)。挂载前水合一次 /auth/me:① 服务端改角色后刷新不卡旧角色;② 旧 persist
// 形状的会话也能拿到 roles,不被守卫拒在门外。
// 失败处理:
//   - 401 由 axios 拦截器处理(refresh→登出跳 /login)
//   - 其他失败(500/超时/断网):陈旧 roles 会让路由 guard 误放行——此时调 clearProfile
//     清空档案,guard 即拒绝,菜单暂时只到登录/公开页;refresh / 拦截器继续兜底。
// mount 必须在 finally 中:即使 useUserStore() 或 fetchMe 同步抛错,也要把应用挂上去,
// 否则 pinia 初始化回归会留空 <div id="app"> 给用户。IIFE 避免顶层 await 的构建兼容。
;(async () => {
  try {
    const userStore = useUserStore()
    if (userStore.accessToken) {
      try {
        await userStore.fetchMe()
      } catch (err: any) {
        // 401 拦截器已处理(过期→refresh→失败→登出跳 /login),无需手动清档
        if (err?.response?.status !== 401) {
          userStore.clearProfile()
        }
      }
    }
  } finally {
    app.mount('#app')
  }
})()
