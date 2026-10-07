import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { guard } from './guard'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/login/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/login/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/dashboard/Index.vue'),
        meta: { title: '仪表盘', icon: 'Odometer', permissions: ['dashboard:read'] },
      },
      {
        path: 'ai',
        name: 'ai-workbench',
        component: () => import('@/views/ai/Workbench.vue'),
        meta: { title: 'AI 工作台', icon: 'MagicStick', permissions: ['ai:use'] },
      },
      {
        path: 'devices',
        name: 'devices',
        component: () => import('@/views/device/Index.vue'),
        meta: { title: '设备', icon: 'Cpu', permissions: ['device:read'] },
      },
      {
        path: 'devices/:id',
        name: 'device-detail',
        component: () => import('@/views/device/Detail.vue'),
        meta: { title: '设备详情', hidden: true },
      },
      {
        path: 'recommendations',
        name: 'recommendations',
        component: () => import('@/views/recommendation/Index.vue'),
        // 保留推荐页路由，但不放入本轮确定的普通用户主菜单。
        meta: { title: '为你推荐', icon: 'MagicStick', permissions: ['reservation:create'], hidden: true },
      },
      {
        path: 'reservations/create',
        name: 'reservation-create',
        component: () => import('@/views/reservation/Create.vue'),
        meta: { title: '建预约', permissions: ['reservation:create'], hidden: true },
      },
      {
        path: 'reservations/mine',
        name: 'reservation-mine',
        component: () => import('@/views/reservation/Mine.vue'),
        meta: { title: '我的预约', icon: 'Calendar', permissions: ['reservation:read:own'] },
      },
      {
        path: 'penalties',
        name: 'penalties',
        component: () => import('@/views/penalty/Index.vue'),
        meta: {
          title: '违规与申诉',
          icon: 'Warning',
        },
      },
      {
        path: 'reservations/:id',
        name: 'reservation-detail',
        component: () => import('@/views/reservation/Detail.vue'),
        meta: { title: '预约详情', permissions: ['reservation:read:own', 'reservation:read:scope'], hidden: true },
      },
      {
        path: 'approvals/pending',
        name: 'approvals',
        component: () => import('@/views/approval/Pending.vue'),
        meta: { title: '待审批', icon: 'Checked', permissions: ['reservation:approve'] },
      },
      {
        path: 'notifications',
        name: 'notifications',
        component: () => import('@/views/notification/Index.vue'),
        meta: { title: '我的通知', icon: 'Bell', permissions: ['notification:read:own'] },
      },
      {
        path: 'repairs/submit',
        name: 'repair-submit',
        component: () => import('@/views/repair/Submit.vue'),
        meta: { title: '提交报修', icon: 'Warning', permissions: ['repair:create'] },
      },
      {
        path: 'repairs/mine',
        name: 'repair-mine',
        component: () => import('@/views/repair/Mine.vue'),
        meta: { title: '我的报修', icon: 'Tools', permissions: ['repair:read:own'] },
      },
      {
        path: 'repairs',
        name: 'repairs-admin',
        component: () => import('@/views/repair/AdminList.vue'),
        meta: { title: '报修处理', icon: 'SetUp', permissions: ['repair:handle'] },
      },
      {
        path: 'devices-manage',
        name: 'devices-manage',
        component: () => import('@/views/device/Manage.vue'),
        meta: { title: '设备管理', icon: 'Setting', permissions: ['device:manage'] },
      },
      {
        path: 'handovers',
        name: 'handovers',
        component: () => import('@/views/handover/Index.vue'),
        meta: { title: '设备交接', icon: 'Connection', permissions: ['reservation:handover', 'reservation:accept-return'] },
      },
      {
        path: 'reports',
        name: 'reports',
        component: () => import('@/views/reports/Index.vue'),
        meta: { title: '运营报表', icon: 'DataAnalysis', permissions: ['report:read'] },
      },
      {
        path: 'reservation-rules',
        name: 'reservation-rules',
        component: () => import('@/views/scheduling/Index.vue'),
        meta: { title: '预约规则', icon: 'Calendar', permissions: ['reservation-rule:manage'] },
      },
      {
        path: 'maintenance',
        name: 'maintenance',
        component: () => import('@/views/maintenance/Index.vue'),
        meta: { title: '维护与校准', icon: 'Tools', permissions: ['maintenance:manage'] },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('@/views/user/Index.vue'),
        meta: { title: '用户管理', icon: 'UserFilled', permissions: ['user:manage'] },
      },
      {
        path: 'organization',
        name: 'organization',
        component: () => import('@/views/organization/Index.vue'),
        meta: { title: '组织管理', icon: 'OfficeBuilding', permissions: ['organization:manage'] },
      },
      {
        path: 'rbac',
        name: 'rbac',
        component: () => import('@/views/rbac/Index.vue'),
        meta: { title: '角色权限', icon: 'Lock', permissions: ['rbac:manage'] },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(guard)

/**
 * 应用内导航深度计数(sessionStorage 持久化,刷新也保留):
 *   - 直达 URL / 外部来源点进:router.isReady() 后才有 nav,计数为 0,
 *     点击"返回"应回首页而非 history.go(-1) 跳到外部页(否则把用户推出 SPA)。
 *   - 应用内 push/replace:n>=1,点击"返回"应 router.back()。
 * 仅在 appReady 之后累加:避免"isReady 后的初始路由解析"误把直达计入一次。
 * 用 sessionStorage(非 localStorage)保留跨刷新的 SPA 内深度,但同会话结束即丢。
 */
const SPA_DEPTH_KEY = 'lab-spa-depth'
let _appReady = false
router.isReady().then(() => {
  _appReady = true
})
router.afterEach(() => {
  if (!_appReady) return
  const cur = Number(sessionStorage.getItem(SPA_DEPTH_KEY) ?? '0')
  sessionStorage.setItem(SPA_DEPTH_KEY, String(cur + 1))
})

export function readSpaDepth(): number {
  return Number(sessionStorage.getItem(SPA_DEPTH_KEY) ?? '0')
}
export function resetSpaDepth(): void {
  sessionStorage.removeItem(SPA_DEPTH_KEY)
}

export default router
