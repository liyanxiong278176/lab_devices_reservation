import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import ElementPlus from 'element-plus'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import 'vue-echarts/style.css'
import './styles/theme.scss'
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
app.mount('#app')
