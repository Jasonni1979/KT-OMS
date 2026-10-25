<script setup lang="ts">
/** 销售物料档案 + BOM 绑定（SRS-D04.01 FR-01 销售物料 / FR-03 BOM）
 *  待绑定清单（FR-01c）+ 自动绑定建议（FR-03d）+ 版本化留痕（FR-03b）
 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  SALES_MATERIAL_TYPE_LABEL, bindBom, getBomCandidates, getBomHistory, getCurrentBom,
  listMaterials, listSalesMaterials, listUnboundSalesMaterials, unbindBom,
  updateSalesMaterial, type BomCandidate, type BomVersion, type Material, type SalesMaterial,
} from '@/api/material'
import { listOwners, listShops, type Owner, type Shop } from '@/api/master'

const rows = ref<SalesMaterial[]>([])
const unbound = ref<SalesMaterial[]>([])
const shops = ref<Shop[]>([])
const owners = ref<Owner[]>([])
const materials = ref<Material[]>([])
const loading = ref(false)
const keyword = ref('')
const filterShop = ref<number | undefined>(undefined)
const tab = ref<'all' | 'unbound'>('all')

// BOM 绑定抽屉
const bomDrawer = reactive({
  visible: false,
  sm: null as SalesMaterial | null,
  items: [] as { bm_id: number; material_bn: string; material_name: string; bind_num: number; rate: number; fixed_price: number }[],
  candidates: [] as BomCandidate[],
  history: [] as BomVersion[],
  current: null as BomVersion | null,
  loading: false,
})

async function load() {
  loading.value = true
  try {
    if (tab.value === 'unbound') {
      unbound.value = await listUnboundSalesMaterials(filterShop.value)
      rows.value = []
    } else {
      rows.value = await listSalesMaterials({
        keyword: keyword.value || undefined,
        shop_id: filterShop.value,
      })
      unbound.value = []
    }
  } finally {
    loading.value = false
  }
}

async function loadRefs() {
  const [s, o, m] = await Promise.all([listShops(), listOwners(), listMaterials()])
  shops.value = s
  owners.value = o
  materials.value = m
}

function shopName(id: number) {
  return shops.value.find((s) => s.id === id)?.shop_name ?? `#${id}`
}
function ownerName(id: number) {
  if (!id) return '—'
  return owners.value.find((o) => o.id === id)?.owner_name ?? `#${id}`
}

async function openBom(row: SalesMaterial) {
  bomDrawer.sm = row
  bomDrawer.visible = true
  bomDrawer.loading = true
  try {
    const [cur, cands, hist] = await Promise.all([
      getCurrentBom(row.id), getBomCandidates(row.id), getBomHistory(row.id),
    ])
    bomDrawer.current = cur
    bomDrawer.candidates = cands
    bomDrawer.history = hist
    bomDrawer.items = cur
      ? cur.items.map((i) => ({
          bm_id: i.bm_id, material_bn: i.material_bn, material_name: i.material_name,
          bind_num: i.bind_num, rate: i.rate, fixed_price: i.fixed_price,
        }))
      : []
  } finally {
    bomDrawer.loading = false
  }
}

function addCandidate(c: BomCandidate) {
  if (bomDrawer.items.some((i) => i.bm_id === c.bm_id)) {
    ElMessage.warning('该基础物料已在明细中')
    return
  }
  const total = bomDrawer.items.reduce((s, i) => s + i.rate, 0)
  bomDrawer.items.push({
    bm_id: c.bm_id, material_bn: c.material_bn, material_name: c.material_name,
    bind_num: 1, rate: Math.max(0, 100 - total), fixed_price: 0,
  })
}

function addManual() {
  const used = new Set(bomDrawer.items.map((i) => i.bm_id))
  const pool = materials.value.filter((m) => !used.has(m.id))
  if (!pool.length) {
    ElMessage.warning('没有可添加的基础物料')
    return
  }
  const total = bomDrawer.items.reduce((s, i) => s + i.rate, 0)
  bomDrawer.items.push({
    bm_id: pool[0].id, material_bn: pool[0].material_bn, material_name: pool[0].material_name,
    bind_num: 1, rate: Math.max(0, 100 - total), fixed_price: 0,
  })
}

function removeItem(idx: number) {
  bomDrawer.items.splice(idx, 1)
}

async function saveBom() {
  const sm = bomDrawer.sm
  if (!sm) return
  if (!bomDrawer.items.length) {
    ElMessage.warning('请至少添加一条绑定明细')
    return
  }
  bomDrawer.loading = true
  try {
    const payload = bomDrawer.items.map((i) => ({
      bm_id: i.bm_id, bind_num: i.bind_num, rate: i.rate, fixed_price: i.fixed_price,
    }))
    const bom = await bindBom(sm.id, payload)
    ElMessage.success(`绑定成功（BOM v${bom.version_no} 生效）`)
    bomDrawer.current = bom
    bomDrawer.history = await getBomHistory(sm.id)
    load()
  } finally {
    bomDrawer.loading = false
  }
}

async function doUnbind() {
  const sm = bomDrawer.sm
  if (!sm) return
  await ElMessageBox.confirm(
    '解绑后该销售物料回到「未绑定」，已有未审单订单将按新 BOM 解析（FR-03c 影响面）。确认解绑？',
    '解绑 BOM',
    { type: 'warning' },
  )
  await unbindBom(sm.id)
  ElMessage.success('已解绑')
  bomDrawer.items = []
  bomDrawer.current = null
  bomDrawer.history = await getBomHistory(sm.id)
  load()
}

async function toggleVisible(row: SalesMaterial) {
  const next = row.visibled === 1 ? 0 : 1
  await updateSalesMaterial(row.id, { visibled: next, version: row.version })
  ElMessage.success(next === 1 ? '已上架' : '已下架')
  load()
}

onMounted(() => { load(); loadRefs() })
</script>

<template>
  <el-card>
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span>销售物料与 BOM 绑定（inv_sales_material · 绑定后回填货主归属）</span>
        <div>
          <el-input v-model="keyword" placeholder="搜索平台编码/标题" size="small"
            style="width:180px;margin-right:8px" clearable @keyup.enter="load" />
          <el-select v-model="filterShop" placeholder="按店铺" size="small"
            style="width:130px;margin-right:8px" clearable @change="load">
            <el-option v-for="s in shops" :key="s.id" :label="s.shop_name" :value="s.id" />
          </el-select>
          <el-button size="small" @click="load">查询</el-button>
        </div>
      </div>
    </template>

    <el-tabs v-model="tab" @tab-change="load">
      <el-tab-pane label="全部销售物料" name="all" />
      <el-tab-pane label="待绑定清单" name="unbound" />
    </el-tabs>

    <el-table v-loading="loading" :data="tab === 'all' ? rows : unbound" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="sales_material_bn" label="平台编码" width="150" />
      <el-table-column prop="sales_material_name" label="平台标题" min-width="180" />
      <el-table-column prop="spec_text" label="规格" width="110" />
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.sales_material_type === 2 ? 'warning' : 'info'">
            {{ SALES_MATERIAL_TYPE_LABEL[row.sales_material_type] ?? row.sales_material_type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="所属店铺" width="120">
        <template #default="{ row }">{{ shopName(row.shop_id) }}</template>
      </el-table-column>
      <el-table-column label="绑定状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.bind_status === 1 ? 'success' : 'warning'">
            {{ row.bind_status === 1 ? '已绑定' : '未绑定' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="归属货主" width="110">
        <template #default="{ row }">{{ ownerName(row.owner_id) }}</template>
      </el-table-column>
      <el-table-column label="来源" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.source === 'api' ? 'primary' : 'info'">
            {{ row.source === 'api' ? '自动' : '手工' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="上下架" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.visibled === 1 ? 'success' : 'info'">
            {{ row.visibled === 1 ? '上架' : '下架' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link type="primary" @click="openBom(row)">
            {{ row.bind_status === 1 ? '查看/改绑' : '绑定BOM' }}
          </el-button>
          <el-button size="small" link :type="row.visibled === 1 ? 'warning' : 'success'"
            @click="toggleVisible(row)">
            {{ row.visibled === 1 ? '下架' : '上架' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- BOM 绑定抽屉 -->
    <el-drawer v-model="bomDrawer.visible" title="BOM 绑定（销售物料 → 基础物料）" size="720px">
      <div v-if="bomDrawer.sm">
        <el-descriptions :column="2" border size="small" style="margin-bottom:14px">
          <el-descriptions-item label="平台编码">{{ bomDrawer.sm.sales_material_bn }}</el-descriptions-item>
          <el-descriptions-item label="平台标题">{{ bomDrawer.sm.sales_material_name }}</el-descriptions-item>
          <el-descriptions-item label="规格">{{ bomDrawer.sm.spec_text || '—' }}</el-descriptions-item>
          <el-descriptions-item label="当前版本">
            <el-tag v-if="bomDrawer.current" size="small" type="success">
              v{{ bomDrawer.current.version_no }} 生效
            </el-tag>
            <span v-else style="color:#999">未绑定</span>
          </el-descriptions-item>
        </el-descriptions>

        <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
          title="规则：同一销售物料的全部明细必须同货主；比例模式下占比合计=100%；BOM 只允许一层，组合装成员不得再作为另一组合装成员。" />

        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <b>绑定明细</b>
          <div>
            <el-button size="small" @click="addManual">手工添加</el-button>
            <el-button size="small" type="primary" :loading="bomDrawer.loading" @click="saveBom">保存绑定</el-button>
            <el-button v-if="bomDrawer.current" size="small" type="danger" plain @click="doUnbind">解绑</el-button>
          </div>
        </div>

        <el-table :data="bomDrawer.items" size="small" border v-loading="bomDrawer.loading">
          <el-table-column prop="material_bn" label="货号" width="120" />
          <el-table-column prop="material_name" label="基础物料" min-width="140" />
          <el-table-column label="数量" width="100">
            <template #default="{ row }">
              <el-input-number v-model="row.bind_num" :min="1" :max="9999" size="small" controls-position="right" />
            </template>
          </el-table-column>
          <el-table-column label="占比%" width="120">
            <template #default="{ row }">
              <el-input-number v-model="row.rate" :min="0" :max="100" :precision="2" size="small" controls-position="right" />
            </template>
          </el-table-column>
          <el-table-column label="固定价" width="130">
            <template #default="{ row }">
              <el-input-number v-model="row.fixed_price" :min="0" :precision="2" size="small" controls-position="right" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="70">
            <template #default="{ $index }">
              <el-button size="small" link type="danger" @click="removeItem($index)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-divider content-position="left">自动绑定建议（FR-03d）</el-divider>
        <el-table :data="bomDrawer.candidates" size="small" border>
          <el-table-column prop="material_bn" label="货号" width="120" />
          <el-table-column prop="material_name" label="基础物料" min-width="150" />
          <el-table-column prop="score" label="匹配度" width="90" />
          <el-table-column prop="reason" label="理由" min-width="160" />
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="addCandidate(row)">添加</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-divider content-position="left">版本历史（变更留痕）</el-divider>
        <el-table :data="bomDrawer.history" size="small" border>
          <el-table-column prop="version_no" label="版本" width="80" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 2 ? 'success' : 'info'">
                {{ row.status === 2 ? '生效' : row.status === 3 ? '历史' : '草稿' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="明细数" width="90">
            <template #default="{ row }">{{ row.items.length }}</template>
          </el-table-column>
          <el-table-column prop="operator" label="操作人" width="110" />
          <el-table-column prop="effective_time" label="生效时间" min-width="170" />
        </el-table>
      </div>
    </el-drawer>
  </el-card>
</template>
