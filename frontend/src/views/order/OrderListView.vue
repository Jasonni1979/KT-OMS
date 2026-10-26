<script setup lang="ts">
/**
 * 订单列表（D03.01 FR-10 · W8-3）
 *
 * 支持按店铺 / 平台单号 / 审单状态 / 支付状态筛选；
 * 点击行进入订单详情页。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  AUDIT_STATUS_LABEL,
  ORDER_STATUS_LABEL,
  PAY_STATUS_LABEL,
  SHIP_STATUS_LABEL,
  listOrders,
  type OrderOut,
} from '@/api/order'

const router = useRouter()
const list = ref<OrderOut[]>([])
const loading = ref(false)

const filterShop = ref<number | undefined>(undefined)
const filterPlatformBn = ref('')
const filterAudit = ref<string | undefined>(undefined)
const filterPay = ref<string | undefined>(undefined)

async function load() {
  loading.value = true
  try {
    list.value =
      (await listOrders({
        shop_id: filterShop.value,
        platform_order_bn: filterPlatformBn.value || undefined,
        audit_status: filterAudit.value,
        pay_status: filterPay.value,
        limit: 200,
      })) ?? []
  } finally {
    loading.value = false
  }
}

function openDetail(row: OrderOut) {
  router.push({ path: '/orders/detail', query: { id: row.id } })
}

function auditTag(s: string) {
  if (s === 'passed') return 'success'
  if (s === 'rejected') return 'danger'
  if (s === 'manual' || s === 'shortage' || s === 'retrial') return 'warning'
  return 'info'
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>订单列表</h2>
        <p class="sub">SRS-D03.01 · 平台订单接入后的订单总览</p>
      </div>
      <el-button @click="load">刷新</el-button>
    </div>

    <el-card shadow="never" class="filter-card">
      <div class="filters">
        <el-input-number
          v-model="filterShop"
          :controls="false"
          placeholder="店铺ID"
          style="width: 120px"
        />
        <el-input
          v-model="filterPlatformBn"
          placeholder="平台订单号"
          clearable
          style="width: 200px"
          @keyup.enter="load"
        />
        <el-select v-model="filterAudit" placeholder="审单状态" clearable style="width: 150px">
          <el-option v-for="(v, k) in AUDIT_STATUS_LABEL" :key="k" :label="v" :value="k" />
        </el-select>
        <el-select v-model="filterPay" placeholder="支付状态" clearable style="width: 130px">
          <el-option v-for="(v, k) in PAY_STATUS_LABEL" :key="k" :label="v" :value="k" />
        </el-select>
        <el-button type="primary" @click="load">查询</el-button>
      </div>
    </el-card>

    <el-card shadow="never">
      <el-table
        :data="list"
        v-loading="loading"
        stripe
        empty-text="暂无订单"
        @row-click="openDetail"
      >
        <el-table-column label="订单号" prop="order_bn" width="180" />
        <el-table-column label="平台单号" prop="platform_order_bn" width="180" />
        <el-table-column label="店铺ID" prop="shop_id" width="90" />
        <el-table-column label="订单状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">
              {{ ORDER_STATUS_LABEL[row.order_status] ?? row.order_status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="审单状态" width="110">
          <template #default="{ row }">
            <el-tag :type="auditTag(row.audit_status)" size="small">
              {{ AUDIT_STATUS_LABEL[row.audit_status] ?? row.audit_status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="支付状态" width="100">
          <template #default="{ row }">
            {{ PAY_STATUS_LABEL[row.pay_status] ?? row.pay_status }}
          </template>
        </el-table-column>
        <el-table-column label="发货状态" width="100">
          <template #default="{ row }">
            {{ SHIP_STATUS_LABEL[row.ship_status] ?? row.ship_status }}
          </template>
        </el-table-column>
        <el-table-column label="实付" width="110">
          <template #default="{ row }">￥{{ Number(row.paid_amount).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="商品原价" width="110">
          <template #default="{ row }">￥{{ Number(row.list_amount).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="买家" prop="buyer_nick" width="120" />
        <el-table-column label="下单时间" prop="order_time" width="170" />
        <el-table-column label="操作" fixed="right" width="90">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="total">共 {{ list.length }} 条（上限 200）</div>
    </el-card>
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
:deep(.el-table__row) { cursor: pointer; }
</style>
