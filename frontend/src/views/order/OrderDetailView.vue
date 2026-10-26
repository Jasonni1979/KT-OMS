<script setup lang="ts">
/**
 * 订单详情（D03.01 · W8-3）
 *
 * - 订单主信息（金额勾稽：商品原价 / 优惠分摊 / 实付）
 * - 订单行（含未绑定物料提示：bm_id=0 → parse_status=pending）
 * - 收货人（脱敏展示，FR-04f PIPL 合规）
 * - 优惠分摊明细（FR-06c）
 * - 关联异常单（FR-03d 人工标记入口 + 异常单跳转）
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  AUDIT_STATUS_LABEL,
  ORDER_STATUS_LABEL,
  PAY_STATUS_LABEL,
  SHIP_STATUS_LABEL,
  getOrder,
  getOrderPmt,
  getOrderReceiver,
  type OrderDetail,
  type OrderPmtOut,
  type ReceiverOut,
} from '@/api/order'
import {
  ABNORMAL_STATUS_LABEL,
  createAbnormal,
  listAbnormalTypes,
  listAbnormals,
  type AbnormalItem,
  type AbnormalType,
} from '@/api/abnormal'

const route = useRoute()
const router = useRouter()

const orderId = computed(() => Number(route.query.id ?? 0))
const order = ref<OrderDetail | null>(null)
const receiver = ref<ReceiverOut | null>(null)
const pmts = ref<OrderPmtOut[]>([])
const abnormals = ref<AbnormalItem[]>([])
const types = ref<AbnormalType[]>([])
const loading = ref(false)

async function load() {
  if (!orderId.value) return
  loading.value = true
  try {
    order.value = await getOrder(orderId.value)
    receiver.value = await getOrderReceiver(orderId.value)
    pmts.value = (await getOrderPmt(orderId.value)) ?? []
    const ab = await listAbnormals({ order_id: orderId.value, limit: 50 })
    abnormals.value = ab.items ?? []
  } finally {
    loading.value = false
  }
}

/** 金额勾稽（FR-04b：行实付合计 = 订单实付 - 运费） */
const amountCheck = computed(() => {
  const o = order.value
  if (!o) return null
  const sumPaid = (o.items ?? []).reduce((s, i) => s + Number(i.paid_amount ?? 0), 0)
  const expect = Number(o.paid_amount ?? 0) - Number(o.freight ?? 0)
  const diff = Math.round((sumPaid - expect) * 100) / 100
  return {
    sumPaid: Math.round(sumPaid * 100) / 100,
    expect: Math.round(expect * 100) / 100,
    diff,
    ok: Math.abs(diff) <= 0.01,
  }
})

/** FR-03d：人工标记异常（类型 + 备注必填） */
async function markAbnormal() {
  const { value: excType } = await ElMessageBox.prompt(
    '请选择或输入异常类型编码（如 PRODUCT_UNBOUND）',
    '标记为异常单',
    { inputPlaceholder: '异常类型编码' },
  ).catch(() => ({ value: '' }))
  if (!excType) return
  const { value: note } = await ElMessageBox.prompt('请填写备注（必填）', '异常备注', {
    inputPlaceholder: '例如：客户要求改地址',
    inputValidator: (v) => (v && v.trim() ? true : '备注必填'),
  }).catch(() => ({ value: '' }))
  if (!note) return
  await createAbnormal({ order_id: orderId.value, exc_type: excType, note })
  ElMessage.success('已标记为异常单')
  await load()
}

function goAbnormal(id: number) {
  router.push({ path: '/abnormal/workbench', query: { id } })
}

onMounted(async () => {
  const t = await listAbnormalTypes()
  types.value = t.items ?? []
  await load()
})
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="page-head">
      <div>
        <h2>订单详情</h2>
        <p class="sub">
          SRS-D03.01 · 订单号
          <span v-if="order">{{ order.order_bn }}</span>
        </p>
      </div>
      <div class="head-actions">
        <el-button @click="router.back()">返回</el-button>
        <el-button type="warning" @click="markAbnormal">标记为异常</el-button>
      </div>
    </div>

    <template v-if="order">
      <el-card shadow="never" class="block">
        <template #header><b>基本信息</b></template>
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="订单号">{{ order.order_bn }}</el-descriptions-item>
          <el-descriptions-item label="平台单号">{{ order.platform_order_bn }}</el-descriptions-item>
          <el-descriptions-item label="店铺ID">{{ order.shop_id }}</el-descriptions-item>
          <el-descriptions-item label="订单状态">
            {{ ORDER_STATUS_LABEL[order.order_status] ?? order.order_status }}
          </el-descriptions-item>
          <el-descriptions-item label="审单状态">
            {{ AUDIT_STATUS_LABEL[order.audit_status] ?? order.audit_status }}
          </el-descriptions-item>
          <el-descriptions-item label="支付状态">
            {{ PAY_STATUS_LABEL[order.pay_status] ?? order.pay_status }}
          </el-descriptions-item>
          <el-descriptions-item label="发货状态">
            {{ SHIP_STATUS_LABEL[order.ship_status] ?? order.ship_status }}
          </el-descriptions-item>
          <el-descriptions-item label="下单时间">{{ order.order_time ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="买家">{{ order.buyer_nick || '—' }}</el-descriptions-item>
          <el-descriptions-item label="买家留言" :span="3">
            {{ order.buyer_memo || '—' }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card shadow="never" class="block">
        <template #header>
          <b>金额</b>
          <el-tag
            v-if="amountCheck"
            :type="amountCheck.ok ? 'success' : 'danger'"
            size="small"
            style="margin-left: 8px"
          >
            勾稽{{ amountCheck.ok ? '一致' : '超差' }}
            <template v-if="!amountCheck.ok">（{{ amountCheck.diff }}）</template>
          </el-tag>
        </template>
        <el-descriptions :column="4" border size="small">
          <el-descriptions-item label="商品原价">
            ￥{{ Number(order.list_amount).toFixed(2) }}
          </el-descriptions-item>
          <el-descriptions-item label="店铺优惠">
            ￥{{ Number(order.shop_discount).toFixed(2) }}
          </el-descriptions-item>
          <el-descriptions-item label="平台补贴">
            ￥{{ Number(order.platform_subsidy).toFixed(2) }}
          </el-descriptions-item>
          <el-descriptions-item label="买家实付">
            ￥{{ Number(order.paid_amount).toFixed(2) }}
          </el-descriptions-item>
          <el-descriptions-item label="运费">
            ￥{{ Number(order.freight).toFixed(2) }}
          </el-descriptions-item>
          <el-descriptions-item label="行实付合计" :span="3">
            ￥{{ amountCheck?.sumPaid.toFixed(2) ?? '—' }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card shadow="never" class="block">
        <template #header><b>订单行</b></template>
        <el-table :data="order.items ?? []" size="small" border empty-text="无订单行">
          <el-table-column label="平台SKU" prop="platform_sku_code" width="180" />
          <el-table-column label="基础物料" width="160">
            <template #default="{ row }">
              <span v-if="row.bm_id > 0">{{ row.bm_number || row.bm_name }}</span>
              <el-tag v-else type="danger" size="small">未绑定基础物料</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="数量" prop="nums" width="80" />
          <el-table-column label="单价" width="100">
            <template #default="{ row }">￥{{ Number(row.list_price).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="小计" width="110">
            <template #default="{ row }">￥{{ Number(row.list_amount).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="实付" width="110">
            <template #default="{ row }">￥{{ Number(row.paid_amount).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="解析状态" width="110">
            <template #default="{ row }">
              <el-tag
                :type="row.parse_status === 'parsed' ? 'success' : 'warning'"
                size="small"
              >
                {{ row.parse_status }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never" class="block">
        <template #header><b>收货人（脱敏 · PIPL 合规）</b></template>
        <el-descriptions v-if="receiver" :column="4" border size="small">
          <el-descriptions-item label="收货人">{{ receiver.name_masked || '—' }}</el-descriptions-item>
          <el-descriptions-item label="手机">{{ receiver.mobile_masked || '—' }}</el-descriptions-item>
          <el-descriptions-item label="省">{{ receiver.province || '—' }}</el-descriptions-item>
          <el-descriptions-item label="市">{{ receiver.city || '—' }}</el-descriptions-item>
          <el-descriptions-item label="区">{{ receiver.district || '—' }}</el-descriptions-item>
          <el-descriptions-item label="镇">{{ receiver.town || '—' }}</el-descriptions-item>
          <el-descriptions-item label="详址">{{ receiver.address_masked || '—' }}</el-descriptions-item>
        </el-descriptions>
        <el-empty v-else description="无收货人信息" :image-size="60" />
      </el-card>

      <el-card shadow="never" class="block">
        <template #header><b>优惠分摊明细</b></template>
        <el-table :data="pmts" size="small" border empty-text="无优惠记录">
          <el-table-column label="类型" prop="pmt_type" width="120" />
          <el-table-column label="承担方" prop="bearer" width="100" />
          <el-table-column label="金额" width="110">
            <template #default="{ row }">￥{{ Number(row.amount).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="平台优惠ID" prop="platform_pmt_id" />
        </el-table>
      </el-card>

      <el-card shadow="never" class="block">
        <template #header><b>关联异常单</b></template>
        <el-table :data="abnormals" size="small" border empty-text="无异常单">
          <el-table-column label="异常单号" prop="abnormal_bn" width="180" />
          <el-table-column label="类型" prop="exc_type" width="160" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">
                {{ ABNORMAL_STATUS_LABEL[row.status] ?? row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="来源" prop="source" width="100" />
          <el-table-column label="创建时间" prop="create_time" width="170" />
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button link type="primary" @click="goAbnormal(row.id)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.page-head h2 { margin: 0 0 4px; font-size: 18px; }
.sub { margin: 0; color: #909399; font-size: 12px; }
.block { margin-bottom: 12px; }
.head-actions { display: flex; gap: 8px; }
</style>
