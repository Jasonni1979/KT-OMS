<script setup lang="ts">
/**
 * 审单规则管理（SRS-D03.02 FR-03c：CRUD + 启停 + 试算器）
 *
 * - 规则列表（weight DESC 排序，缺省规则标记）
 * - 条件 DSL 可视化编辑（维度 + 操作符 + 值）
 * - 试算器：输入订单号 → 展示命中规则与逐项求值明细（不落库不执行）
 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { dryRunRule, listAuditRules, updateAuditRule, type AuditRule } from '@/api/audit'

const rules = ref<AuditRule[]>([])
const loading = ref(false)
const dialog = reactive({
  visible: false,
  isEdit: false,
  form: {
    id: 0,
    rule_name: '',
    weight: 0,
    auto_confirm: 0,
    pass_action: 'exec_plan',
    router_num_limit: 5,
    status: 'enabled',
    version: 0,
    conditions: { logic: 'AND', items: [] as any[] },
  },
})

/** 维度字典（与后端 AUDIT_DIM_GROUP 对齐） */
const DIMENSIONS = [
  { key: 'shop_id', label: '店铺', type: 'set' },
  { key: 'brand_id', label: '品牌', type: 'set' },
  { key: 'owner_id', label: '货主', type: 'set' },
  { key: 'order.amount_paid', label: '客户实付金额', type: 'number' },
  { key: 'order.amount_list', label: '订单原价', type: 'number' },
  { key: 'order_type', label: '订单类型', type: 'set' },
  { key: 'order.items.category', label: '商品类目', type: 'set' },
  { key: 'order.items.sku', label: 'SKU', type: 'set' },
  { key: 'order.items.nums', label: '明细件数', type: 'number' },
  { key: 'order.is_cod', label: '货到付款', type: 'bool' },
  { key: 'order.receiver_province', label: '收货省份', type: 'set' },
  { key: 'order.has_memo', label: '有无买家留言', type: 'bool' },
  { key: 'order.createway', label: '下单来源', type: 'set' },
]

const OPS_BY_TYPE: Record<string, string[]> = {
  set: ['in', 'not_in'],
  number: ['eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'between'],
  bool: ['is_true', 'is_false'],
  string: ['eq', 'neq', 'contains'],
  datetime: ['in_window', 'before', 'after'],
}

/** 试算器 */
const dryRun = reactive({
  visible: false,
  ruleId: 0,
  orderId: 0,
  loading: false,
  result: null as any,
})

async function load() {
  loading.value = true
  try {
    rules.value = await listAuditRules()
  } finally {
    loading.value = false
  }
}

function openEdit(row: AuditRule) {
  dialog.isEdit = true
  dialog.form = {
    id: row.id,
    rule_name: row.rule_name,
    weight: row.weight,
    auto_confirm: row.auto_confirm,
    pass_action: row.pass_action,
    router_num_limit: row.router_num_limit,
    status: row.status,
    version: row.version,
    conditions: JSON.parse(JSON.stringify(row.conditions || { logic: 'AND', items: [] })),
  }
  dialog.visible = true
}

function addCondition() {
  dialog.form.conditions.items.push({ dim: 'shop_id', op: 'in', value: [] })
}

function removeCondition(idx: number) {
  dialog.form.conditions.items.splice(idx, 1)
}

function dimType(dim: string) {
  return DIMENSIONS.find((d) => d.key === dim)?.type ?? 'set'
}

function dimOps(dim: string) {
  return OPS_BY_TYPE[dimType(dim)] ?? OPS_BY_TYPE.set
}

async function save() {
  await updateAuditRule(dialog.form.id, {
    rule_name: dialog.form.rule_name,
    weight: dialog.form.weight,
    auto_confirm: dialog.form.auto_confirm,
    pass_action: dialog.form.pass_action,
    router_num_limit: dialog.form.router_num_limit,
    status: dialog.form.status,
    conditions: dialog.form.conditions,
  })
  ElMessage.success('已保存（规则缓存已失效重载）')
  dialog.visible = false
  await load()
}

async function runDryRun() {
  if (!dryRun.ruleId || !dryRun.orderId) {
    ElMessage.warning('请填写规则 ID 与订单 ID')
    return
  }
  dryRun.loading = true
  try {
    dryRun.result = await dryRunRule(dryRun.ruleId, dryRun.orderId)
  } finally {
    dryRun.loading = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>审单规则（三层模型：条件 / 插件 / 动作；weight DESC 首个命中）</span>
          <div>
            <el-button size="small" @click="dryRun.visible = true">试算器</el-button>
            <el-button size="small" @click="load">刷新</el-button>
          </div>
        </div>
      </template>

      <el-table v-loading="loading" :data="rules" stripe>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="rule_name" label="规则名称" min-width="220" />
        <el-table-column label="条件" min-width="260">
          <template #default="{ row }">
            <el-tag
              v-for="(it, i) in row.conditions.items"
              :key="i"
              size="small"
              style="margin:2px"
            >{{ it.dim }} {{ it.op }} {{ Array.isArray(it.value) ? it.value.join(',') : it.value }}</el-tag>
            <span v-if="!row.conditions.items?.length" style="color:#bbb">（无条件 / 缺省兜底）</span>
          </template>
        </el-table-column>
        <el-table-column prop="weight" label="权重" width="80" />
        <el-table-column label="自动通过" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.auto_confirm ? 'success' : 'warning'">
              {{ row.auto_confirm ? '开' : '关' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="通过动作" width="120">
          <template #default="{ row }">
            {{ row.pass_action === 'exec_plan' ? '执行 plan' : '转人工确认' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_default ? 'info' : 'success'">
              {{ row.is_default ? '缺省' : row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              link
              type="primary"
              :disabled="!!row.is_default"
              @click="openEdit(row)"
            >编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 规则编辑 -->
    <el-dialog v-model="dialog.visible" title="编辑审单规则" width="720px">
      <el-form :model="dialog.form" label-width="110px">
        <el-form-item label="规则名称">
          <el-input v-model="dialog.form.rule_name" />
        </el-form-item>
        <el-form-item label="权重">
          <el-input-number v-model="dialog.form.weight" :min="-9999" :max="9999" />
          <span style="color:#999;margin-left:8px">大者先命中</span>
        </el-form-item>
        <el-form-item label="自动通过">
          <el-switch v-model="dialog.form.auto_confirm" :active-value="1" :inactive-value="0" />
          <span style="color:#999;margin-left:8px">关 = 决策草稿转人工确认</span>
        </el-form-item>
        <el-form-item label="路由上限">
          <el-input-number v-model="dialog.form.router_num_limit" :min="1" :max="20" />
        </el-form-item>
        <el-form-item label="条件组">
          <div style="width:100%">
            <el-table :data="dialog.form.conditions.items" size="small" border>
              <el-table-column label="维度" width="200">
                <template #default="{ row }">
                  <el-select v-model="row.dim" size="small" filterable style="width:100%">
                    <el-option v-for="d in DIMENSIONS" :key="d.key" :label="d.label" :value="d.key" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="操作符" width="130">
                <template #default="{ row }">
                  <el-select v-model="row.op" size="small" style="width:100%">
                    <el-option v-for="op in dimOps(row.dim)" :key="op" :label="op" :value="op" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="值">
                <template #default="{ row }">
                  <el-input
                    v-model="row.value"
                    size="small"
                    :placeholder="dimType(row.dim) === 'set' ? '多个值用英文逗号分隔' : '单值'"
                  />
                </template>
              </el-table-column>
              <el-table-column width="60">
                <template #default="{ $index }">
                  <el-button size="small" link type="danger" @click="removeCondition($index)">删</el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-button size="small" style="margin-top:8px" @click="addCondition">+ 条件项</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 试算器（不落库不执行） -->
    <el-dialog v-model="dryRun.visible" title="规则试算器（dry-run：不落库不执行）" width="720px">
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px">
        <el-input-number v-model="dryRun.ruleId" :min="1" placeholder="规则 ID" />
        <el-input-number v-model="dryRun.orderId" :min="1" placeholder="订单 ID" />
        <el-button type="primary" :loading="dryRun.loading" @click="runDryRun">试算</el-button>
      </div>
      <el-alert
        v-if="dryRun.result"
        :type="dryRun.result.hit ? 'success' : 'warning'"
        :title="`命中：${dryRun.result.hit ? '是' : '否'}　生效时段内：${dryRun.result.in_effective_window ? '是' : '否'}　排除时段：${dryRun.result.in_exclude_window ? '是' : '否'}`"
        :closable="false"
        show-icon
        style="margin-bottom:12px"
      />
      <el-table v-if="dryRun.result" :data="dryRun.result.details" size="small" border>
        <el-table-column prop="dim" label="维度" width="180" />
        <el-table-column prop="op" label="操作符" width="100" />
        <el-table-column prop="expected" label="期望值" width="140" />
        <el-table-column prop="actual" label="实际值" width="140" />
        <el-table-column label="结果" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.hit ? 'success' : 'danger'">{{ row.hit ? '命中' : '不中' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="说明" min-width="200" />
      </el-table>
    </el-dialog>
  </div>
</template>
