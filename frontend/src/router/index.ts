import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      { path: 'dashboard', name: 'dashboard', component: () => import('@/views/DashboardView.vue'), meta: { title: '工作台', icon: 'Odometer' } },
      { path: 'master/org', name: 'org-tree', component: () => import('@/views/master/OrgTreeView.vue'), meta: { title: '组织架构', icon: 'Share' } },
      { path: 'master/owners', name: 'owners', component: () => import('@/views/master/OwnerListView.vue'), meta: { title: '货主档案', icon: 'User' } },
      { path: 'master/shops', name: 'shops', component: () => import('@/views/master/ShopListView.vue'), meta: { title: '店铺档案', icon: 'Shop' } },
      { path: 'master/branches', name: 'branches', component: () => import('@/views/master/BranchListView.vue'), meta: { title: '仓库档案', icon: 'House' } },
      { path: 'tenants', name: 'tenants', component: () => import('@/views/TenantListView.vue'), meta: { title: '租户列表(骨架演示)', icon: 'OfficeBuilding' } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录跳 login（public 路由除外）
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  return true
})

export default router
