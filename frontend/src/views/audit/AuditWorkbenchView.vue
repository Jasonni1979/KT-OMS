<script setup lang="ts">
/**
 * 人工审单工作台（SRS-D03.03）
 *
 * - 待审队列（多维筛选 / 时效优先排序 / 原因码徽章）
 * - 单单审核侧滑详情（订单聚合 + 结构化原因区 + 引擎决策草稿）
 * - 键盘流（J/K 上下、Enter 详情、P 通过、R 驳回、/ 聚焦筛选、Esc 关闭）
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  REASON_LEVEL_LABEL, ROUTE_LABEL, TASK_STATUS_LABEL,
  autoDispatch, getWorkbenchDetail, listAuditGroups, listAuditQueue, listDispatchRules,
  passAudit, rejectAudit,
  type AuditGroup, type QueueItem, type WorkbenchDetail,
} from '@/api/audit'

const queue = ref<QueueItem[]>([])
const total = ref(0)
const loading = ref(false)
const groups = ref<AuditGroup[]>([])
const dispatchRules = ref<any[]>([])

const filterShop = ref<number | undefined>(undefined)
const filterReason = ref<string | undefined>(undefined)
const filterTaskStatus = ref<string | undefined>(undefined)
const keyword = ref('')

const currentIndex = ref(0)
const drawer = ref({
  visible: false,
  loading: false,
  detail: null as WorkbenchDetail | null,
})
const shortcutVisible = ref(false)

/** 键盘流：当前选中行 */
const currentRow = computed<QueueItem | null>(() => queue.value[currentIndex.value] ?? null)

const SHORTCUTS = [
  { key: 'J', desc: '下一单' },
  { key: 'K', desc: '上一单' },
  { key: 'Enter', desc: '打开详情' },
  { key: 'P', desc: '审核通过' },
  { key: 'R', desc: '驳回' },
  { key: 'D', desc: '转缺货处理' },
  { key: '/', desc: '聚焦筛选' },
  { key: 'Esc', desc: '关闭侧滑' },
  { key: '?', desc: '快捷键面板' },
]

async function load() {
  loading.value = true
  try {
    const res = await listAuditQueue({
      shop_id: filterShop.value,
      reason_code: filterReason.value,
      task_status: filterTaskStatus.value,
      limit: 200,
    })
    let items = res.items
    if (keyword.value) {
      const kw = keyword.value.trim().toLowerCase()
      items = items.filter(
        (x) =>
          x.order_bn.toLowerCase().includes(kw) ||
          x.platform_order_bn.toLowerCase().includes(kw) ||
          x.buyer_nick.toLowerCase().includes(kw),
      )
    }
    queue.value = items
    total.value = res.total
    if (currentIndex.value >= items.length) currentIndex.value = 0
  } finally {
    loading.value = false
  }
}

async function loadRefs() {
  const [g, d] = await Promise.all([listAuditGroups(), listDispatchRules()])
  groups.value = g
  dispatchRules.value = d
}

async function openDetail(row: QueueItem) {
  drawer.value.visible = true
  drawer.value.loading = true
  try {
    drawer.value.detail = await getWorkbenchDetail(row.order_id)
  } finally {
    drawer.value.loading = false
  }
}

function move(delta: number) {
  if (!queue.value.length) return
  currentIndex.value = (currentIndex.value + delta + queue.value.length) % queue.value.length
  if (drawer.value.visible) {
    const row = currentRow.value
    if (row) openDetail(row)
  }
}

async function doPass(row: QueueItem) {
  const detail = drawer.value.detail
  if (!detail?.decision_draft) {
    ElMessage.warning('该订单无引擎决策草稿，请人工指定后提交')
    return
  }
  await ElMessageBox.confirm(
    `确认通过订单 ${row.order_bn}？将提交人工 plan 走同源执行器（预占 → 发货单）。`,
    '审核通过',
    { type: 'warning' },
  )
  const res = await passAudit(row.order_id, {
    operator: 'admin',
    plan_id: detail.decision_draft.plan_id,
  })
  if (res.status === 'success') {
    ElMessage.success(`已通过（发货单 ${res.delivery_ids.join(', ') || '待生成'}）`)
  } else {
    ElMessage.error(`执行失败：${res.fail_code} ${res.fail_message}`)
  }
  drawer.value.visible = false
  await load()
}

async function doReject(row: QueueItem) {
  const { value } = await ElMessageBox.prompt(
    '请填写驳回原因（结构化码，如 RECEIVER_INFO_MISSING）+ 备注',
    '驳回订单',
    { inputPlaceholder: '原因码', inputValidator: (v) => (v ? true : '驳回原因必填') },
  )
  await rejectAudit(row.order_id, { reason_code: value, operator: 'admin' })
  ElMessage.success('已驳回')
  drawer.value.visible = false
  await load()
}

async function doDispatch(row: QueueItem) {
  const res = await autoDispatch(row.order_id, row.reason_codes)
  if (res.route === 'pool') {
    ElMessage.warning(`已落公共池（${res.reason || '全员满载'}）`)
  } else {
    ElMessage.success(`已分派（审核员 ${res.assign_op ?? '-'}）`)
  }
  await load()
}

/** 键盘流（FR-08a） */
function onKey(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement)?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA') {
    if (e.key === 'Escape') (e.target as HTMLElement).blur()
    return
  }
  const row = currentRow.value
  switch (e.key) {
    case 'j':
    case 'J':
      e.preventDefault()
      move(1)
      break
    case 'k':
    case 'K':
      e.preventDefault()
      move(-1)
      break
    case 'Enter':
      if (row) {
        e.preventDefault()
        openDetail(row)
      }
      break
    case 'p':
    case 'P':
      if (drawer.value.visible && row) {
        e.preventDefault()
        doPass(row)
      }
      break
    case 'r':
    case 'R':
      if (drawer.value.visible && row) {
        e.preventDefault()
        doReject(row)
      }
      break
    case '/':
      e.preventDefault()
      document.querySelector<HTMLInputElement>('.queue-filter input')?.focus()
      break
    case '?':
      e.preventDefault()
      shortcutVisible.value = true
      break
    case 'Escape':
      if (shortcutVisible.value) shortcutVisible.value = false
      else drawer.value.visible = false
      break
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKey)
  await Promise.all([load(), loadRefs()])
})
onUnmounted(() => window.removeEventListener('keydown', onKey))

function reasonLabel(code: string) {
  return code
}
function levelTag(level: string) {
  return REASON_LEVEL_LABEL[level] ?? { text: level, type: 'info' }
}
function routeTag(route: string) {
  return ROUTE_LABEL[route] ?? { text: route || '-', type: 'info' }
}
</script>

<template>
  <div class="workbench">
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>
            待审队列
            <el-tag size="small" type="info">{{ total }} 单</el-tag>
            <el-tag v-if="queue.length" size="small" style="margin-left:6px">
              {{ currentIndex + 1 }} / {{ queue.length }}
            </el-tag>
          </span>
          <div>
            <el-button size="small" @click="shortcutVisible = true">快捷键 ?</el-button>
            <el-button size="small" @click="load">刷新</el-button>
          </div>
        </div>
      </template>

      <!-- 筛选（FR-01b 多维筛选） -->
      <div class="queue-filter" style="margin-bottom:12px;display:flex;gap:8px;flex-wrap:wrap">
        <el-input
          v-model="keyword"
          placeholder="订单号 / 买家昵称"
          size="small"
          style="width:200px"
          clearable
          @keyup.enter="load"
        />
        <el-select v-model="filterTaskStatus" placeholder="任务状态" size="small" style="width:130px" clearable @change="load">
          <el-option
            v-for="(v, k) in TASK_STATUS_LABEL"
            :key="k"
            :label="v.text"
            :value="k"
          />
        </el-select>
        <el-select v-model="filterReason" placeholder="原因码" size="small" style="width:160px" clearable @change="load">
          <el-option label="地址不合规" value="ADDRESS_INVALID" />
          <el-option label="库存不足" value="STOCK_SHORTAGE" />
          <el-option label="价格异常" value="PRICE_ABNORMAL" />
          <el-option label="大额订单" value="BIG_AMOUNT" />
          <el-option label="命中黑名单" value="BLACKLIST_HIT" />
          <el-option label="买家留言需确认" value="MEMO_HOLD" />
        </el-select>
        <el-button size="small" @click="load">查询</el-button>
      </div>

      <!-- 队列（FR-01e 原因码徽章 + 时效优先排序） -->
      <el-table
        v-loading="loading"
        :data="queue"
        stripe
        highlight-current-row
        :current-row-key="currentRow?.task_id"
        @row-click="(row: QueueItem) => { currentIndex = queue.findIndex(x => x.task_id === row.task_id); openDetail(row) }"
      >
        <el-table-column prop="order_bn" label="订单号" width="190" />
        <el-table-column label="原因码" width="220">
          <template #default="{ row }">
            <el-tag
              v-for="c in row.reason_codes"
              :key="c"
              size="small"
              type="danger"
              style="margin-right:4px"
            >{{ reasonLabel(c) }}</el-tag>
            <span v-if="!row.reason_codes.length" style="color:#bbb">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="TASK_STATUS_LABEL[row.task_status]?.type ?? 'info'">
              {{ TASK_STATUS_LABEL[row.task_status]?.text ?? row.task_status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="buyer_nick" label="买家" width="110" />
        <el-table-column label="实付" width="100">
          <template #default="{ row }">¥{{ row.paid_amount.toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="SLA 截止" width="160">
          <template #default="{ row }">
            <span :style="{ color: row.overtime_level > 0 ? '#f56c6c' : '' }">
              {{ row.sla_deadline ?? '—' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click.stop="openDetail(row)">详情</el-button>
            <el-button size="small" link type="success" @click.stop="doPass(row)">通过</el-button>
            <el-button size="small" link type="danger" @click.stop="doReject(row)">驳回</el-button>
            <el-button size="small" link @click.stop="doDispatch(row)">分派</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 侧滑详情（FR-03a/FR-08b：不离开队列页） -->
    <el-drawer v-model="drawer.visible" size="720px" :title="`审单详情 · ${currentRow?.order_bn ?? ''}`">
      <div v-if="drawer.loading" style="text-align:center;padding:40px">
        <el-skeleton :rows="8" animated />
      </div>
      <div v-else-if="drawer.detail">
        <!-- 订单聚合信息 -->
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="订单号">{{ drawer.detail.order.order_bn }}</el-descriptions-item>
          <el-descriptions-item label="平台单号">{{ drawer.detail.order.platform_order_bn || '—' }}</el-descriptions-item>
          <el-descriptions-item label="实付">¥{{ Number(drawer.detail.order.paid_amount ?? 0).toFixed(2) }}</el-descriptions-item>
          <el-descriptions-item label="订单状态">{{ drawer.detail.order.order_status }}</el-descriptions-item>
          <el-descriptions-item label="收货省市区">
            {{ drawer.detail.receiver.province }} {{ drawer.detail.receiver.city }} {{ drawer.detail.receiver.district }}
          </el-descriptions-item>
          <el-descriptions-item label="买家留言">
            {{ drawer.detail.order.buyer_memo || '—' }}
          </el-descriptions-item>
        </el-descriptions>

        <!-- 明细行 -->
        <h4 style="margin:16px 0 8px">订单明细</h4>
        <el-table :data="drawer.detail.items" size="small" border>
          <el-table-column prop="bm_number" label="货号" width="130" />
          <el-table-column prop="bm_name" label="品名" min-width="140" />
          <el-table-column prop="nums" label="数量" width="70" />
          <el-table-column label="实付" width="100">
            <template #default="{ row }">¥{{ Number(row.paid_amount).toFixed(2) }}</template>
          </el-table-column>
        </el-table>

        <!-- 结构化原因区（BLOCK/WARN 分列，FR-03a） -->
        <h4 style="margin:16px 0 8px">审核原因</h4>
        <div v-if="!drawer.detail.reasons.length" style="color:#999">无审核原因</div>
        <el-alert
          v-for="r in drawer.detail.reasons"
          :key="r.id"
          :type="levelTag(r.level).type === 'danger' ? 'error' : 'warning'"
          :title="`${r.plugin_name} · ${r.reason_code}`"
          :description="`${r.description}　建议动作：${r.suggest_action || '-'}　路由：${routeTag(r.route_target).text}`"
          :closable="false"
          show-icon
          style="margin-bottom:8px"
        />

        <!-- 引擎决策草稿（FR-03a） -->
        <h4 style="margin:16px 0 8px">引擎决策草稿</h4>
        <el-descriptions v-if="drawer.detail.decision_draft" :column="2" border size="small">
          <el-descriptions-item label="方案号">{{ drawer.detail.decision_draft.plan_bn }}</el-descriptions-item>
          <el-descriptions-item label="版本">v{{ drawer.detail.decision_draft.plan_version }}</el-descriptions-item>
          <el-descriptions-item label="仓库">
            {{ drawer.detail.decision_draft.warehouse_alloc?.branch_name ?? '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="物流">
            {{ drawer.detail.decision_draft.logistics_alloc?.carrier_name ?? '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="拆单组" :span="2">
            {{ drawer.detail.decision_draft.split_matrix?.groups?.length ?? 0 }} 组
          </el-descriptions-item>
        </el-descriptions>
        <div v-else style="color:#999">无决策草稿（该订单未投审或未产出 plan）</div>
      </div>

      <template #footer>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="color:#999;font-size:12px">
            快捷键：P 通过 · R 驳回 · J/K 上下 · Esc 关闭
          </span>
          <div>
            <el-button size="small" @click="drawer.visible = false">关闭</el-button>
            <el-button size="small" type="danger" @click="currentRow && doReject(currentRow)">驳回 R</el-button>
            <el-button size="small" type="primary" @click="currentRow && doPass(currentRow)">通过 P</el-button>
          </div>
        </div>
      </template>
    </el-drawer>

    <!-- 快捷键面板 -->
    <el-dialog v-model="shortcutVisible" title="键盘流快捷键" width="420">
      <el-table :data="SHORTCUTS" size="small">
        <el-table-column prop="key" label="按键" width="110" />
        <el-table-column prop="desc" label="说明" />
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.workbench {
  min-height: 100%;
}
</style>
