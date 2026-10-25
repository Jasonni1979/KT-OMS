<script setup lang="ts">
/**
 * 发货单工作台（SRS-D03.07 FR-10）
 *
 * - 发货单列表（多维筛选：状态/仓/店铺/订单号/关键字）
 * - 详情侧滑（头/行/明细溯源/包裹/状态日志/差异登记）
 * - **四指令操作**：推送 / 叫回 / 恢复 / 确认（+取消 / 打回）
 * - 异常视图（推送失败/叫回失败/差异登记）
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deliveryCancel,
  deliveryConfirm,
  deliveryPush,
  deliveryRecall,
  deliveryRecallResult,
  deliveryReject,
  deliveryResume,
  getDeliveryDetail,
  listDeliveryAbnormal,
  listDeliveries,
  type DeliveryBrief,
  type DeliveryDetail,
} from '@/api/fulfill'

const list = ref<DeliveryBrief[]>([])
const loading = ref(false)
const abnormal = ref<Record<string, unknown>[]>([])
const tab = ref<'list' | 'abnormal'>('list')

const filterStatus = ref<string | undefined>(undefined)
const filterBranch = ref<number | undefined>(undefined)
const filterShop = ref<number | undefined>(undefined)
const keyword = ref('')

const drawer = ref({
  visible: false,
  loading: false,
  detail: null as DeliveryDetail | null,
})

/** 状态 → 中文标签 */
const STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  pushed: '已推送',
  push_failed: '推送失败',
  processing: '出库中',
  partial_outbound: '部分出库',
  outbound: '已出库',
  shipped: '已发货',
  finished: '完成',
  recalling: '叫回中',
  recalled: '已叫回',
  rejected: '已打回',
  cancelled: '已取消',
}

const STATUS_TAG: Record<string, string> = {
  draft: 'info',
  pushed: 'primary',
  push_failed: 'danger',
  processing: 'warning',
  partial_outbound: 'warning',
  outbound: 'primary',
  shipped: 'success',
  finished: 'success',
  recalling: 'warning',
  recalled: 'info',
  rejected: 'danger',
  cancelled: 'info',
}

/** 指令 → 中文 + 类型 */
const CMD_LABEL: Record<string, { label: string; type: 'primary' | 'success' | 'warning' | 'danger' | 'info' }> = {
  push: { label: '推送', type: 'primary' },
  push_failed: { label: '标记推送失败', type: 'danger' },
  callback_ack: { label: 'WMS接收确认', type: 'primary' },
  callback_outbound: { label: '出库回传', type: 'primary' },
  recall: { label: '叫回', type: 'warning' },
  recall_failed: { label: '叫回失败', type: 'danger' },
  resume: { label: '恢复', type: 'primary' },
  confirm: { label: '确认发货', type: 'success' },
  cancel: { label: '取消', type: 'danger' },
  reject: { label: '打回', type: 'danger' },
  finish: { label: '完成', type: 'success' },
}

const statusOptions = Object.entries(STATUS_LABEL).map(([v, l]) => ({ value: v, label: l }))

const currentDetail = computed(() => drawer.value.detail)

async function load() {
  loading.value = true
  try {
    const res = await listDeliveries({
      status: filterStatus.value,
      branch_id: filterBranch.value,
      shop_id: filterShop.value,
      keyword: keyword.value || undefined,
      limit: 200,
    })
    list.value = res
  } catch (e) {
    ElMessage.error(`发货单加载失败：${(e as Error).message}`)
  } finally {
    loading.value = false
  }
}

async function loadAbnormal() {
  try {
    abnormal.value = await listDeliveryAbnormal()
  } catch (e) {
    ElMessage.error(`异常视图加载失败：${(e as Error).message}`)
  }
}

async function openDetail(row: DeliveryBrief) {
  drawer.value.visible = true
  drawer.value.loading = true
  drawer.value.detail = null
  try {
    drawer.value.detail = await getDeliveryDetail(row.id)
  } catch (e) {
    ElMessage.error(`详情加载失败：${(e as Error).message}`)
  } finally {
    drawer.value.loading = false
  }
}

/** 执行指令（统一入口 + 错误提示） */
async function runCommand(cmd: string, id: number, needReason = false) {
  let reason = ''
  if (needReason) {
    const { value } = await ElMessageBox.prompt('请输入原因（必填）', '操作确认', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValidator: (v) => (v && v.trim() ? true : '原因必填'),
    })
    reason = value
  }
  try {
    let res: { ok: boolean; to_status?: string; fail_message?: string }
    if (cmd === 'push') res = await deliveryPush(id, reason)
    else if (cmd === 'recall') res = await deliveryRecall(id, reason)
    else if (cmd === 'resume') res = await deliveryResume(id, reason)
    else if (cmd === 'confirm') res = await deliveryConfirm(id, reason)
    else if (cmd === 'cancel') res = await deliveryCancel(id, reason)
    else if (cmd === 'reject') res = await deliveryReject(id, reason)
    else if (cmd === 'recall_failed')
      res = await deliveryRecallResult(id, false, reason)
    else return

    if (res.ok) {
      ElMessage.success(`指令 ${CMD_LABEL[cmd]?.label ?? cmd} 执行成功 → ${STATUS_LABEL[res.to_status ?? ''] ?? res.to_status}`)
      await load()
      await loadAbnormal()
      if (drawer.value.visible) await openDetail(list.value.find((x) => x.id === id) ?? ({ id } as DeliveryBrief))
    } else {
      ElMessage.warning(res.fail_message || '指令执行失败（非法流转）')
    }
  } catch (e) {
    ElMessage.error(`指令执行失败：${(e as Error).message}`)
  }
}

onMounted(async () => {
  await load()
  await loadAbnormal()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2>发货单工作台</h2>
      <el-tag type="info" effect="plain">指令状态机：draft → pushed → processing → outbound → shipped → finished</el-tag>
    </div>

    <el-tabs v-model="tab" @tab-change="(t: string) => (t === 'abnormal' ? loadAbnormal() : load())">
      <el-tab-pane label="发货单列表" name="list">
        <div class="filters">
          <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 150px" @change="load">
            <el-option v-for="o in statusOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
          <el-input-number v-model="filterBranch" placeholder="仓库ID" :controls="false" style="width: 120px" @change="load" />
          <el-input-number v-model="filterShop" placeholder="店铺ID" :controls="false" style="width: 120px" @change="load" />
          <el-input v-model="keyword" placeholder="发货单号" clearable style="width: 200px" @keyup.enter="load" />
          <el-button type="primary" @click="load">查询</el-button>
          <el-button @click="load">刷新</el-button>
        </div>

        <el-table :data="list" v-loading="loading" border stripe size="small" @row-dblclick="openDetail">
          <el-table-column prop="delivery_bn" label="发货单号" width="170" />
          <el-table-column prop="order_id" label="订单ID" width="90" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="(STATUS_TAG[row.status] as any) || 'info'" size="small">
                {{ STATUS_LABEL[row.status] ?? row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="branch_id" label="发货仓" width="90" />
          <el-table-column prop="owner_id" label="货主" width="80" />
          <el-table-column prop="logi_no" label="运单号" width="150" />
          <el-table-column label="虚拟" width="70">
            <template #default="{ row }">
              <el-tag v-if="row.is_virtual" type="warning" size="small">虚拟</el-tag>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column prop="source" label="来源" width="80" />
          <el-table-column prop="create_time" label="创建时间" width="180" />
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openDetail(row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="异常视图" name="abnormal">
        <el-table :data="abnormal" border stripe size="small">
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="delivery_bn" label="发货单号" width="170" />
          <el-table-column prop="abnormal_type" label="异常类型" width="120" />
          <el-table-column prop="status" label="当前状态" width="110" />
          <el-table-column prop="diff_type" label="差异类型" width="100" />
          <el-table-column prop="diff_num" label="差异数量" width="90" />
          <el-table-column prop="memo" label="说明" min-width="200" />
          <el-table-column prop="sync_msg" label="同步信息" min-width="160" />
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="drawer.visible" title="发货单详情" size="68%">
      <div v-loading="drawer.loading">
        <template v-if="currentDetail">
          <el-descriptions :column="4" border size="small">
            <el-descriptions-item label="发货单号">{{ currentDetail.delivery.delivery_bn }}</el-descriptions-item>
            <el-descriptions-item label="订单ID">{{ currentDetail.delivery.order_id }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="(STATUS_TAG[currentDetail.delivery.status] as any) || 'info'" size="small">
                {{ STATUS_LABEL[currentDetail.delivery.status] ?? currentDetail.delivery.status }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="发货仓">{{ currentDetail.delivery.branch_id }}</el-descriptions-item>
            <el-descriptions-item label="货主">{{ currentDetail.delivery.owner_id }}</el-descriptions-item>
            <el-descriptions-item label="推仓状态">{{ currentDetail.delivery.sync_status }}</el-descriptions-item>
            <el-descriptions-item label="运单号">{{ currentDetail.delivery.logi_no || '—' }}</el-descriptions-item>
            <el-descriptions-item label="来源">{{ currentDetail.delivery.source }}</el-descriptions-item>
          </el-descriptions>

          <div class="cmd-bar">
            <span class="cmd-label">可用指令：</span>
            <el-button
              v-for="c in currentDetail.allowed_commands"
              :key="c"
              :type="(CMD_LABEL[c]?.type as any) || 'primary'"
              size="small"
              @click="runCommand(c, currentDetail.delivery.id, c === 'cancel' || c === 'reject' || c === 'recall_failed')"
            >
              {{ CMD_LABEL[c]?.label ?? c }}
            </el-button>
          </div>

          <el-tabs>
            <el-tab-pane label="发货单行" name="items">
              <el-table :data="currentDetail.items" border size="small">
                <el-table-column prop="id" label="行ID" width="80" />
                <el-table-column prop="bm_number" label="货号" width="140" />
                <el-table-column prop="num" label="数量" width="80" />
                <el-table-column prop="settled_num" label="已核销" width="90" />
                <el-table-column prop="owner_id" label="货主" width="80" />
                <el-table-column prop="price" label="金额" width="110" />
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="明细溯源" name="details">
              <el-table :data="currentDetail.details" border size="small">
                <el-table-column prop="delivery_item_id" label="发货单行" width="110" />
                <el-table-column prop="order_item_id" label="订单行" width="110" />
                <el-table-column prop="split_qty" label="分配数量" width="110" />
                <el-table-column prop="freeze_ref" label="预占引用" min-width="140" />
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="包裹" name="packages">
              <el-table :data="currentDetail.packages" border size="small">
                <el-table-column prop="package_no" label="包裹号" width="140" />
                <el-table-column prop="waybill_no" label="运单号" width="160" />
                <el-table-column prop="weight" label="重量" width="100" />
                <el-table-column prop="volume" label="体积" width="100" />
                <el-table-column prop="batch_no" label="回传批次" width="150" />
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="状态日志" name="logs">
              <el-table :data="currentDetail.logs" border size="small">
                <el-table-column prop="create_time" label="时间" width="180" />
                <el-table-column label="指令" width="130">
                  <template #default="{ row }">
                    {{ CMD_LABEL[row.command]?.label ?? row.command }}
                  </template>
                </el-table-column>
                <el-table-column label="流转" width="200">
                  <template #default="{ row }">
                    {{ STATUS_LABEL[row.from_status] || '—' }} → {{ STATUS_LABEL[row.to_status] || row.to_status }}
                  </template>
                </el-table-column>
                <el-table-column prop="operator" label="操作者" width="120" />
                <el-table-column prop="reason" label="原因" min-width="180" />
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="差异登记" name="diffs">
              <el-table :data="currentDetail.diffs" border size="small">
                <el-table-column prop="diff_type" label="差异类型" width="100" />
                <el-table-column prop="diff_num" label="数量" width="90" />
                <el-table-column prop="liability" label="责任方" width="100" />
                <el-table-column prop="handle_way" label="处理方式" width="110" />
                <el-table-column prop="handle_status" label="处理状态" width="100" />
                <el-table-column prop="memo" label="说明" min-width="200" />
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.page-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.page-head h2 { margin: 0; font-size: 18px; }
.filters { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.cmd-bar { display: flex; align-items: center; gap: 8px; margin: 12px 0; flex-wrap: wrap; }
.cmd-label { font-size: 13px; color: #606266; }
</style>
