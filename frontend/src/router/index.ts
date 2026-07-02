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
      // 更多路由在后续 slice 加入，按需带 meta.roles
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
