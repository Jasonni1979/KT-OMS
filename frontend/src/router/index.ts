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
      { path: 'material/materials', name: 'materials', component: () => import('@/views/material/MaterialListView.vue'), meta: { title: '基础物料', icon: 'Goods' } },
      { path: 'material/categories', name: 'material-cats', component: () => import('@/views/material/CategoryView.vue'), meta: { title: '物料分类', icon: 'Folder' } },
      { path: 'material/brands', name: 'brands', component: () => import('@/views/material/BrandListView.vue'), meta: { title: '品牌档案', icon: 'Star' } },
      { path: 'material/sales', name: 'sales-materials', component: () => import('@/views/material/SalesMaterialView.vue'), meta: { title: '销售物料与BOM', icon: 'GoodsFilled' } },
      { path: 'material/barcodes', name: 'barcodes', component: () => import('@/views/material/BarcodeView.vue'), meta: { title: '条码管理', icon: 'Postcard' } },
      { path: 'import/center', name: 'import-center', component: () => import('@/views/import/ImportCenterView.vue'), meta: { title: '导入中心', icon: 'Upload' } },
      { path: 'stock/ledger', name: 'stock-ledger', component: () => import('@/views/stock/StockLedgerView.vue'), meta: { title: '库存余额与对账', icon: 'Coin' } },
      { path: 'stock/bills', name: 'stock-bills', component: () => import('@/views/stock/StockBillView.vue'), meta: { title: '出入库单据', icon: 'Tickets' } },
      { path: 'architecture/contracts', name: 'architecture-contracts', component: () => import('@/views/architecture/ContractView.vue'), meta: { title: '架构契约', icon: 'Tickets' } },
      { path: 'abnormal/workbench', name: 'abnormal-workbench', component: () => import('@/views/abnormal/AbnormalWorkbenchView.vue'), meta: { title: '异常单工作台', icon: 'Warning' } },
      { path: 'orders', name: 'orders', component: () => import('@/views/order/OrderListView.vue'), meta: { title: '订单列表', icon: 'List' } },
      { path: 'orders/detail', name: 'order-detail', component: () => import('@/views/order/OrderDetailView.vue'), meta: { title: '订单详情', hidden: true } },
      { path: 'monitor', name: 'monitor-dashboard', component: () => import('@/views/monitor/MonitorDashboardView.vue'), meta: { title: '履约监控看板', icon: 'DataLine' } },
      { path: 'audit/workbench', name: 'audit-workbench', component: () => import('@/views/audit/AuditWorkbenchView.vue'), meta: { title: '人工审单工作台', icon: 'DocumentChecked' } },
      { path: 'audit/rules', name: 'audit-rules', component: () => import('@/views/audit/AuditRuleView.vue'), meta: { title: '审单规则管理', icon: 'SetUp' } },
      { path: 'fulfill/deliveries', name: 'deliveries', component: () => import('@/views/fulfill/DeliveryWorkbenchView.vue'), meta: { title: '发货单工作台', icon: 'Van' } },
      { path: 'fulfill/split-rules', name: 'split-rules', component: () => import('@/views/fulfill/SplitRuleView.vue'), meta: { title: '拆单规则管理', icon: 'Files' } },
      { path: 'fulfill/dispatch-rules', name: 'dispatch-rules', component: () => import('@/views/fulfill/DispatchRuleView.vue'), meta: { title: '分仓规则管理', icon: 'Location' } },
      { path: 'tenants', name: 'tenants', component: () => import('@/views/TenantListView.vue'), meta: { title: '租户列表(骨架演示)', icon: 'OfficeBuilding' } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：未登录跳 login；刷新后恢复会话（token 在但权限未加载 → fetchMe）
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.public) return true
  if (!auth.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (!auth.accountName) {
    try {
      const { fetchMe } = await import('@/api/auth')
      auth.setMe(await fetchMe())
    } catch {
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }
  return true
})

export default router
