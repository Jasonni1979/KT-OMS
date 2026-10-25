<script setup lang="ts">
/** 出入库单据中心（SRS-D04.04）：列表 / 状态流转 / 追溯 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  BILL_STATUS_LABEL, SETTLE_STATUS_LABEL, confirmBill, listBillTypes, listBills,
  pushBillToWms, redFlushBill, traceBill, type IoBill, type IoBillType, type IoBillTrace,
} from '@/api/stock'

const bills = ref<IoBill[]>([])
const types = ref<IoBillType[]>([])
const loading = ref(false)
const filterType = ref<string | undefined>(undefined)
const filterStatus = ref<number | undefined>(undefined)

const traceDrawer = reactive({
  visible: false,
  loading: false,
  data: null as IoBillTrace | null,
})

async function load() {
  loading.value = true
  try {
    bills.value = await listBills({
      bill_type: filterType.value,
      status: filterStatus.value,
    })
  } finally {
    loading.value = false
  }
}

async function loadTypes() {
  types.value = await listBillTypes()
}

function typeName(code: string) {
  return types.value.find((t) => t.type_code === code)?.type_name ?? code
}

async function doPush(row: IoBill) {
  await pushBillToWms(row.id)
  ElMessage.success('已下发 WMS')
  load()
}

async function doConfirm(row: IoBill) {
  await ElMessageBox.confirm(
    `确认单据 ${row.bill_bn}？将按类型口径模板生成记账指令并立即生效。`,
    '确认即记账',
    { type: 'warning' },
  )
  await confirmBill(row.id)
  ElMessage.success('已确认并记账')
  load()
}

async function doRedFlush(row: IoBill) {
  const { value } = await ElMessageBox.prompt('请输入红冲原因（必填）', '红冲', {
    inputPattern: /\S+/,
    inputErrorMessage: '原因必填',
  })
  await redFlushBill(row.id, value)
  ElMessage.success('已红冲（生成反向单据并反向记账）')
  load()
}

async function openTrace(row: IoBill) {
  traceDrawer.visible = true
  traceDrawer.loading = true
  try {
    traceDrawer.data = await traceBill(row.id)
  } finally {
    traceDrawer.loading = false
  }
}

onMounted(() => { load(); loadTypes() })
</script>

<template>
  <el-card>
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span>出入库单据中心（口径影响模板驱动记账 · 确认即记账 · 变更留痕可追溯）</span>
        <div>
          <el-select v-model="filterType" placeholder="单据类型" size="small"
            style="width:150px;margin-right:8px" clearable @change="load">
            <el-option v-for="t in types" :key="t.type_code"
              :label="`${t.type_name}（${t.type_code}）`" :value="t.type_code" />
          </el-select>
          <el-select v-model="filterStatus" placeholder="状态" size="small"
            style="width:120px;margin-right:8px" clearable @change="load">
            <el-option v-for="(label, val) in BILL_STATUS_LABEL" :key="val"
              :label="label" :value="val" />
          </el-select>
          <el-button size="small" @click="load">查询</el-button>
        </div>
      </div>
    </template>

    <el-table v-loading="loading" :data="bills" stripe>
      <el-table-column prop="bill_bn" label="单据号" width="230" />
      <el-table-column label="类型" width="130">
        <template #default="{ row }">
          {{ typeName(row.bill_type) }}
          <el-tag size="small" :type="row.direction === 1 ? 'success' : 'warning'" style="margin-left:4px">
            {{ row.direction === 1 ? '入' : '出' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="branch_id" label="仓ID" width="80" />
      <el-table-column prop="source_bill_bn" label="源单号" width="130" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 5 ? 'success' : row.status === 6 ? 'danger' : 'info'">
            {{ BILL_STATUS_LABEL[row.status] ?? row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="结算状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.settle_status === 3 ? 'success' : 'info'">
            {{ SETTLE_STATUS_LABEL[row.settle_status] ?? row.settle_status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="行数" width="70">
        <template #default="{ row }">{{ row.items.length }}</template>
      </el-table-column>
      <el-table-column prop="operator" label="经手人" width="100" />
      <el-table-column prop="create_time" label="创建时间" min-width="170" />
      <el-table-column label="操作" width="210" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.status === 1" size="small" link type="primary" @click="doPush(row)">
            下发
          </el-button>
          <el-button v-if="row.status === 1 || row.status === 4" size="small" link type="success" @click="doConfirm(row)">
            确认记账
          </el-button>
          <el-button v-if="row.status === 5" size="small" link type="danger" @click="doRedFlush(row)">
            红冲
          </el-button>
          <el-button size="small" link @click="openTrace(row)">追溯</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="traceDrawer.visible" title="单据追溯链（单据 → 行 → 流水 → 余额）" size="720px">
      <div v-if="traceDrawer.data" v-loading="traceDrawer.loading">
        <el-descriptions :column="3" border size="small" style="margin-bottom:12px">
          <el-descriptions-item label="单据号">{{ traceDrawer.data.bill.bill_bn }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ typeName(traceDrawer.data.bill.bill_type) }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            {{ BILL_STATUS_LABEL[traceDrawer.data.bill.status] }}
          </el-descriptions-item>
          <el-descriptions-item label="源单号">{{ traceDrawer.data.bill.source_bill_bn || '—' }}</el-descriptions-item>
          <el-descriptions-item label="红冲引用">{{ traceDrawer.data.bill.red_flush_of || '—' }}</el-descriptions-item>
          <el-descriptions-item label="结算状态">
            {{ SETTLE_STATUS_LABEL[traceDrawer.data.bill.settle_status] }}
          </el-descriptions-item>
        </el-descriptions>

        <el-divider content-position="left">单据行</el-divider>
        <el-table :data="traceDrawer.data.bill.items" size="small" border style="margin-bottom:12px">
          <el-table-column prop="bm_id" label="物料ID" width="90" />
          <el-table-column prop="issued_num" label="下发" width="80" />
          <el-table-column prop="returned_num" label="回传" width="80" />
          <el-table-column prop="confirmed_num" label="确认" width="80" />
          <el-table-column prop="defect_num" label="不良" width="80" />
          <el-table-column prop="unit_cost" label="单价" width="90" />
          <el-table-column prop="amount" label="金额" width="100" />
        </el-table>

        <el-divider content-position="left">变动流水</el-divider>
        <el-table :data="traceDrawer.data.change_logs" size="small" border style="margin-bottom:12px">
          <el-table-column prop="change_field" label="口径" width="90" />
          <el-table-column prop="change_num" label="变动" width="80" />
          <el-table-column prop="before_balance" label="变动前" width="90" />
          <el-table-column prop="after_balance" label="变动后" width="90" />
          <el-table-column prop="action" label="动作" width="100" />
          <el-table-column prop="create_time" label="时间" min-width="170" />
        </el-table>

        <el-divider content-position="left">当前记账行余额</el-divider>
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item v-for="(v, k) in traceDrawer.data.ledger" :key="k" :label="k">
            {{ v }}
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </el-drawer>
  </el-card>
</template>
