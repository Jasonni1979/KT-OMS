<script setup lang="ts">
/**
 * 异常单工作台（SRS-D03.09 · W8-3）
 *
 * - 异常单列表（类型/状态/分类/关键字筛选 + SLA 超期标识）
 * - 单据详情抽屉（订单快照 + 缺货明细 + 时间线 + SLA）
 * - 处置动作区：**按类型 action_set 白名单**渲染可用动作
 *   （未实现的动作置灰并明示原因，不隐藏）
 * - 缺货类可走策略链：换仓测算 / 换仓重试 / 解除重审
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ABNORMAL_CATEGORY_LABEL,
  ABNORMAL_STATUS_LABEL,
  ACTION_LABEL,
  autoDispatchAbnormal,
  calcStrategy,
  executeAction,
  listAbnormalTypes,
  listAbnormals,
  listActions,
  getAbnormal,
  releaseRetry,
  resolveAbnormal,
  startAbnormal,
  switchBranch,
  type AbnormalDetail,
  type AbnormalItem,
  type AbnormalType,
  type ActionItem,
} from '@/api/abnormal'

const list = ref<AbnormalItem[]>([])
const total = ref(0)
const loading = ref(false)
const types = ref<AbnormalType[]>([])

const filterType = ref<string | undefined>(undefined)
const filterStatus = ref<string | undefined>(undefined)
const filterCategory = ref<string | undefined>(undefined)
const keyword = ref('')
const onlyOpen = ref(true)

const drawer = ref({
  visible: false,
  loading: false,
  detail: null as AbnormalDetail | null,
  actions: [] as ActionItem[],
  strategy: null as Record<string, unknown> | null,
})

const typeMap = computed(() => {
  const m: Record<string, AbnormalType> = {}
  types.value.forEach((t) => (m[t.type_code] = t))
  return m
})

function typeName(code: string) {
  return typeMap.value[code]?.type_name ?? code
}

function typeTag(code: string) {
  const cat = typeMap.value[code]?.category ?? ''
  if (cat === 'risk') return 'danger'
  if (cat === 'stock') return 'warning'
  if (cat === 'data') return 'primary'
  if (cat === 'fulfill') return 'success'
  return 'info'
}

async function loadTypes() {
  const res = await listAbnormalTypes()
  types.value = res.items ?? []
}

async function load() {
  loading.value = true
  try {
    const res = await listAbnormals({
      exc_type: filterType.value,
      status: filterStatus.value,
      exc_category: filterCategory.value,
      keyword: keyword.value || undefined,
      only_open: onlyOpen.value || undefined,
      limit: 200,
    })
    list.value = res.items ?? []
    total.value = res.total ?? 0
  } finally {
    loading.value = false
  }
}

async function openDetail(row: AbnormalItem) {
  drawer.value.visible = true
  drawer.value.loading = true
  drawer.value.strategy = null
  try {
    drawer.value.detail = await getAbnormal(row.id)
    const act = await listActions(row.id)
    drawer.value.actions = act.items ?? []
  } finally {
    drawer.value.loading = false
  }
}

/** 缺货类 → 换仓测算 */
async function calcStrategyAction() {
  const d = drawer.value.detail
  if (!d) return
  const res = await calcStrategy(d.id)
  drawer.value.strategy = res as unknown as Record<string, unknown>
  const status = String(res.status ?? '')
  if (status === 'full') ElMessage.success('存在可整单满足的候选仓，建议一键换仓重审')
  else if (status === 'partial') ElMessage.warning('仅部分行可满足，建议拆单换仓')
  else if (status === 'none') ElMessage.info('无候选仓可满足，建议借调或采购加急')
  const borrow = res.borrow_stock
  if (borrow && borrow.enabled === false) {
    ElMessage.info(`借调建议暂不可用：${borrow.reason}`)
  }
}

async function doAction(action: string) {
  const d = drawer.value.detail
  if (!d) return
  const extra: Record<string, unknown> = {}
  if (action === 'suspend') {
    const { value } = await ElMessageBox.prompt(
      '请填预计恢复时间（小时数）',
      '挂起异常单',
      { inputPlaceholder: '例如 24', inputPattern: /^\d+$/, inputErrorMessage: '请输入正整数' },
    )
    extra.until_hours = Number(value)
  }
  const { value: note } = await ElMessageBox.prompt('请填写处置备注', '处置说明', {
    inputPlaceholder: '例如：已补货，解除重审',
  }).catch(() => ({ value: '' }))
  const res = await executeAction(d.id, { action, note: note || undefined, extra })
  if (res.ok === false && res.enabled === false) {
    ElMessage.warning(`${ACTION_LABEL[action] ?? action}暂不可用：${res.reason ?? ''}`)
    return
  }
  ElMessage.success(`${ACTION_LABEL[action] ?? action} 已执行`)
  await openDetail(d as unknown as AbnormalItem)
  await load()
}

/** 缺货策略链：解除重审（FR-04c） */
async function doReleaseRetry() {
  const d = drawer.value.detail
  if (!d) return
  const res = await releaseRetry(d.id)
  if (res.ok === false) {
    ElMessage.warning(`解除重审失败：${res.fail_message ?? res.reason ?? '未知原因'}`)
    return
  }
  ElMessage.success('解除重审已执行')
  await openDetail(d as unknown as AbnormalItem)
  await load()
}

/** 缺货策略链：换仓重试（FR-04b） */
async function doSwitchBranch() {
  const d = drawer.value.detail
  if (!d) return
  const res = await switchBranch(d.id)
  if (res.ok === false) {
    ElMessage.warning(`换仓重试失败：${res.fail_message ?? res.reason ?? '未知原因'}`)
    return
  }
  ElMessage.success('换仓重试已执行')
  await openDetail(d as unknown as AbnormalItem)
  await load()
}

async function quickResolve(row: AbnormalItem) {
  const { value } = await ElMessageBox.prompt('请填写解决备注', '解决异常单', {
    inputPlaceholder: '例如：已建档绑定',
  }).catch(() => ({ value: '' }))
  if (value === undefined) return
  await resolveAbnormal(row.id, { note: value })
  ElMessage.success('异常单已解决')
  await load()
}

async function quickAutoDispatch(row: AbnormalItem) {
  const res = await autoDispatchAbnormal(row.id)
  if (res.dispatched) {
    ElMessage.success(`已自动分派到处理组 ${res.group_id}`)
  } else {
    ElMessage.info('无匹配分派规则且类型无默认处理组，请人工分派')
  }
  await load()
}

async function quickStart(row: AbnormalItem) {
  await startAbnormal(row.id, {})
  ElMessage.success('已进入处理中')
  await load()
}

onMounted(async () => {
  await loadTypes()
  await load()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>异常单工作台</h2>
        <p class="sub">SRS-D03.09 · 缺货 / 未绑定商品 / 地址异常等异常的落单与人工处置</p>
      </div>
      <div class="head-actions">
        <el-button @click="load">刷新</el-button>
      </div>
    </div>

    <el-card shadow="never" class="filter-card">
      <div class="filters">
        <el-select v-model="filterType" placeholder="异常类型" clearable style="width: 180px">
          <el-option v-for="t in types" :key="t.type_code" :label="t.type_name" :value="t.type_code" />
        </el-select>
        <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 140px">
          <el-option v-for="(v, k) in ABNORMAL_STATUS_LABEL" :key="k" :label="v" :value="k" />
        </el-select>
        <el-select v-model="filterCategory" placeholder="分类" clearable style="width: 130px">
          <el-option v-for="(v, k) in ABNORMAL_CATEGORY_LABEL" :key="k" :label="v" :value="k" />
        </el-select>
        <el-input
          v-model="keyword"
          placeholder="异常单号 / 订单号"
          clearable
          style="width: 220px"
          @keyup.enter="load"
        />
        <el-checkbox v-model="onlyOpen" @change="load">只看未闭环</el-checkbox>
        <el-button type="primary" @click="load">查询</el-button>
      </div>
    </el-card>

    <el-card shadow="never">
      <el-table :data="list" v-loading="loading" stripe empty-text="暂无异常单">
        <el-table-column label="异常单号" prop="abnormal_bn" width="180" />
        <el-table-column label="类型" width="150">
          <template #default="{ row }">
            <el-tag :type="typeTag(row.exc_type)" size="small">
              {{ typeName(row.exc_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="订单号" prop="order_bn" width="180" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ ABNORMAL_STATUS_LABEL[row.status] ?? row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="SLA" width="150">
          <template #default="{ row }">
            <span v-if="row.sla?.overdue" class="sla-overdue">已超期</span>
            <span v-else-if="row.sla?.remain_hours != null" class="sla-ok">
              剩余 {{ row.sla.remain_hours }}h
            </span>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="来源" prop="source" width="110" />
        <el-table-column label="创建时间" prop="create_time" width="170" />
        <el-table-column label="操作" fixed="right" width="250">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button
              v-if="row.status === 'wait_dispatch'"
              link
              type="warning"
              @click="quickAutoDispatch(row)"
            >
              自动分派
            </el-button>
            <el-button
              v-if="row.status === 'assigned'"
              link
              type="primary"
              @click="quickStart(row)"
            >
              开始处理
            </el-button>
            <el-button
              v-if="!['resolved', 'cancelled'].includes(row.status)"
              link
              type="success"
              @click="quickResolve(row)"
            >
              解决
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="total">共 {{ total }} 条</div>
    </el-card>

    <el-drawer v-model="drawer.visible" title="异常单详情" size="720px">
      <div v-loading="drawer.loading">
        <template v-if="drawer.detail">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="异常单号">{{ drawer.detail.abnormal_bn }}</el-descriptions-item>
            <el-descriptions-item label="异常类型">
              <el-tag :type="typeTag(drawer.detail.exc_type)" size="small">
                {{ typeName(drawer.detail.exc_type) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="订单号">{{ drawer.detail.order_bn }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              {{ ABNORMAL_STATUS_LABEL[drawer.detail.status] ?? drawer.detail.status }}
            </el-descriptions-item>
            <el-descriptions-item label="来源">{{ drawer.detail.source }}</el-descriptions-item>
            <el-descriptions-item label="来源引用">{{ drawer.detail.source_ref || '—' }}</el-descriptions-item>
            <el-descriptions-item label="处理组">{{ drawer.detail.group_id ?? '未分派' }}</el-descriptions-item>
            <el-descriptions-item label="解决动作">
              {{ drawer.detail.resolve_action ? (ACTION_LABEL[drawer.detail.resolve_action] ?? drawer.detail.resolve_action) : '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="SLA 截止">{{ drawer.detail.sla?.deadline ?? '—' }}</el-descriptions-item>
            <el-descriptions-item label="剩余小时">{{ drawer.detail.sla?.remain_hours ?? '—' }}</el-descriptions-item>
          </el-descriptions>

          <div class="section-title">可用处置动作</div>
          <div class="actions">
            <el-tag
              v-for="a in drawer.actions"
              :key="a.action"
              :type="a.enabled ? 'primary' : 'info'"
              :effect="a.enabled ? 'dark' : 'plain'"
              class="action-tag"
              @click="a.enabled && doAction(a.action)"
            >
              {{ ACTION_LABEL[a.action] ?? a.action }}
              <span v-if="!a.enabled" class="action-reason">（暂不可用）</span>
            </el-tag>
            <el-empty v-if="!drawer.actions.length" description="该异常单无可用动作" :image-size="60" />
          </div>
          <div v-if="drawer.actions.some((a) => !a.enabled)" class="hint">
            置灰动作属后续批次（转售后 / 退款），系统明确返回「本期未实现」，不会伪造单据。
          </div>

          <template v-if="['STOCK_SHORT', 'OVERSOLD'].includes(drawer.detail.exc_type)">
            <div class="section-title">缺货策略链</div>
            <div class="actions">
              <el-button size="small" @click="calcStrategyAction">换仓测算</el-button>
              <el-button size="small" @click="doReleaseRetry">解除重审</el-button>
              <el-button size="small" @click="doSwitchBranch">换仓重试</el-button>
            </div>
            <el-alert
              v-if="drawer.strategy"
              type="info"
              :closable="false"
              style="margin-top: 8px"
              :title="`测算结论：${drawer.strategy.status}`"
              :description="String(drawer.strategy.reason ?? '')"
            />
          </template>

          <template v-if="drawer.detail.stockouts?.length">
            <div class="section-title">缺货明细</div>
            <el-table :data="drawer.detail.stockouts" size="small" border>
              <el-table-column label="仓库" prop="branch_id" width="90" />
              <el-table-column label="物料" prop="bm_id" width="90" />
              <el-table-column label="缺口量" prop="lack_num" width="90" />
              <el-table-column label="策略状态" prop="strategy_status" width="110" />
              <el-table-column label="库存快照">
                <template #default="{ row }">
                  <span class="mono">{{ JSON.stringify(row.stock_snapshot ?? {}) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </template>

          <div class="section-title">处理时间线</div>
          <el-timeline>
            <el-timeline-item
              v-for="(t, i) in drawer.detail.timeline ?? []"
              :key="i"
              :timestamp="t.at"
              placement="top"
            >
              <b>{{ t.action }}</b>
              <span class="op">{{ t.operator }}</span>
              <div v-if="t.note" class="note">{{ t.note }}</div>
            </el-timeline-item>
          </el-timeline>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.page-head h2 { margin: 0 0 4px; font-size: 18px; }
.sub { margin: 0; color: #909399; font-size: 12px; }
.filter-card { margin-bottom: 12px; }
.filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.total { margin-top: 10px; color: #909399; font-size: 12px; text-align: right; }
.sla-overdue { color: #f56c6c; font-weight: 600; }
.sla-ok { color: #67c23a; }
.section-title { margin: 18px 0 8px; font-weight: 600; font-size: 14px; }
.actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.action-tag { cursor: pointer; user-select: none; }
.action-reason { font-size: 11px; opacity: 0.8; }
.hint { margin-top: 6px; color: #909399; font-size: 12px; }
.mono { font-family: monospace; font-size: 11px; color: #606266; }
.op { margin-left: 8px; color: #909399; font-size: 12px; }
.note { color: #606266; font-size: 12px; margin-top: 2px; }
</style>
