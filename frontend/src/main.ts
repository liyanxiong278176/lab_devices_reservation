import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import { ElAlert } from 'element-plus/es/components/alert/index'
import { ElBadge } from 'element-plus/es/components/badge/index'
import { ElButton } from 'element-plus/es/components/button/index'
import { ElCheckbox } from 'element-plus/es/components/checkbox/index'
import { ElCol } from 'element-plus/es/components/col/index'
import { ElContainer } from 'element-plus/es/components/container/index'
import { ElDatePicker } from 'element-plus/es/components/date-picker/index'
import { ElDialog } from 'element-plus/es/components/dialog/index'
import { ElDrawer } from 'element-plus/es/components/drawer/index'
import { ElDropdown } from 'element-plus/es/components/dropdown/index'
import { ElForm } from 'element-plus/es/components/form/index'
import { ElIcon } from 'element-plus/es/components/icon/index'
import { ElInput } from 'element-plus/es/components/input/index'
import { ElInputNumber } from 'element-plus/es/components/input-number/index'
import { ElLoading } from 'element-plus/es/components/loading/index'
import { ElMenu } from 'element-plus/es/components/menu/index'
import { ElMessage } from 'element-plus/es/components/message/index'
import { ElMessageBox } from 'element-plus/es/components/message-box/index'
import { ElNotification } from 'element-plus/es/components/notification/index'
import { ElPagination } from 'element-plus/es/components/pagination/index'
import { ElRadio } from 'element-plus/es/components/radio/index'
import { ElRate } from 'element-plus/es/components/rate/index'
import { ElRow } from 'element-plus/es/components/row/index'
import { ElSelect } from 'element-plus/es/components/select/index'
import { ElSwitch } from 'element-plus/es/components/switch/index'
import { ElTable } from 'element-plus/es/components/table/index'
import { ElTabs } from 'element-plus/es/components/tabs/index'
import { ElTag } from 'element-plus/es/components/tag/index'
import { ElTreeSelect } from 'element-plus/es/components/tree-select/index'
import {
  Bell,
  Calendar,
  Checked,
  Cpu,
  MagicStick,
  OfficeBuilding,
  Odometer,
  SetUp,
  Setting,
  Tools,
  UserFilled,
  Warning,
} from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
// EP 暗色基础变量(必须在 dist/index.css 之后、theme.dark.scss 之前,让本项目 token 覆盖 EP 默认暗色)
import 'element-plus/theme-chalk/dark/css-vars.css'
import 'vue-echarts/style.css'
// 自托管字体(离线,答辩不依赖外网)— 仅引需要的 weight
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource-variable/plus-jakarta-sans/wght.css'
// 统一浅色/深色 token。主题由用户显式切换，默认浅色。
import './styles/theme.scss'
// 动效 token + 通用 keyframes/工具类(在颜色 token 之后加载)
import './styles/_motion.scss'
import App from './App.vue'
import router from './router'
import { vPermission } from './directives/permission'
import { useUserStore } from './stores/user'
import { useThemeStore } from './stores/theme'

const app = createApp(App)
const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)
// 注册 v-permission 指令（按权限码裁剪元素）
app.directive('permission', vPermission)
// 侧栏图标来自路由 meta.icon，是动态组件名；只注册导航实际使用的图标，
// 避免恢复旧版“全量注册所有图标”带来的 bundle 膨胀。
const navigationIcons = {
  Bell,
  Calendar,
  Checked,
  Cpu,
  MagicStick,
  OfficeBuilding,
  Odometer,
  SetUp,
  Setting,
  Tools,
  UserFilled,
  Warning,
}
for (const [name, icon] of Object.entries(navigationIcons)) {
  app.component(name, icon)
}
// 只安装实际使用的 Element Plus 组件。组件插件会同时注册自己的子组件，
// 例如 Container 会带上 Aside/Header/Main，Table 会带上 TableColumn，
// 这样保留模板兼容性的同时避免把整套组件实现打进首屏 bundle。
app
  .use(pinia)
  .use(router)
  .use(ElAlert)
  .use(ElBadge)
  .use(ElButton)
  .use(ElCheckbox)
  .use(ElCol)
  .use(ElContainer)
  .use(ElDatePicker)
  .use(ElDialog)
  .use(ElDrawer)
  .use(ElDropdown)
  .use(ElForm)
  .use(ElIcon)
  .use(ElInput)
  .use(ElInputNumber)
  .use(ElMenu)
  .use(ElPagination)
  .use(ElRadio)
  .use(ElRate)
  .use(ElRow)
  .use(ElSelect)
  .use(ElSwitch)
  .use(ElTable)
  .use(ElTabs)
  .use(ElTag)
  .use(ElTreeSelect)
  .use(ElLoading)
  .use(ElMessage)
  .use(ElMessageBox)
  .use(ElNotification)
// 主题由本地偏好驱动，首次默认为 light；同时加 .js class 作为
// [data-stagger] 初始态隐藏的 gate(JS 没跑则内容可见,无障碍/健壮)。
document.documentElement.classList.add('js')
const themeStore = useThemeStore()
themeStore.init()

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
