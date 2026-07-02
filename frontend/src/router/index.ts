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
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/dashboard/Index.vue'),
        meta: { title: '驾驶舱', icon: 'Odometer' },
      },
      {
        path: 'devices',
        name: 'devices',
        component: () => import('@/views/device/Index.vue'),
        meta: { title: '设备', icon: 'Cpu' },
      },
      {
        path: 'devices/:id',
        name: 'device-detail',
        component: () => import('@/views/device/Detail.vue'),
        meta: { title: '设备详情', hidden: true },
      },
      {
        path: 'reservations/create',
        name: 'reservation-create',
        component: () => import('@/views/reservation/Create.vue'),
        meta: { title: '建预约', hidden: true },
      },
      {
        path: 'reservations/mine',
        name: 'reservation-mine',
        component: () => import('@/views/reservation/Mine.vue'),
        meta: { title: '我的预约', icon: 'Calendar' },
      },
      {
        path: 'reservations/:id',
        name: 'reservation-detail',
        component: () => import('@/views/reservation/Detail.vue'),
        meta: { title: '预约详情', hidden: true },
      },
      {
        path: 'approvals/pending',
        name: 'approvals',
        component: () => import('@/views/approval/Pending.vue'),
        meta: { title: '待审批', icon: 'Checked', roles: ['LAB_ADMIN', 'SYS_ADMIN'] },
      },
      {
        path: 'notifications',
        name: 'notifications',
        component: () => import('@/views/notification/Index.vue'),
        meta: { title: '我的通知', icon: 'Bell' },
      },
      {
        path: 'repairs/submit',
        name: 'repair-submit',
        component: () => import('@/views/repair/Submit.vue'),
        meta: { title: '提交报修', icon: 'Warning' },
      },
      {
        path: 'repairs/mine',
        name: 'repair-mine',
        component: () => import('@/views/repair/Mine.vue'),
        meta: { title: '我的报修', icon: 'Tools' },
      },
      {
        path: 'repairs',
        name: 'repairs-admin',
        component: () => import('@/views/repair/AdminList.vue'),
        meta: { title: '报修处理', icon: 'SetUp', roles: ['LAB_ADMIN', 'SYS_ADMIN'] },
      },
      {
        path: 'devices-manage',
        name: 'devices-manage',
        component: () => import('@/views/device/Manage.vue'),
        meta: { title: '设备管理', icon: 'Setting', roles: ['LAB_ADMIN', 'SYS_ADMIN'] },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('@/views/user/Index.vue'),
        meta: { title: '用户管理', icon: 'UserFilled', roles: ['SYS_ADMIN'] },
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

export default router
