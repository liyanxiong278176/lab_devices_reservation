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
import App from './App.vue'
import router from './router'
import { vPermission } from './directives/permission'
import { setupEcharts } from './composables/useEcharts'

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
document.documentElement.classList.add('dark')
app.mount('#app')
