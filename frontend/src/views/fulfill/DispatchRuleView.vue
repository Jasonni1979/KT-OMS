<script setup lang="ts">
/**
 * 分仓规则管理（SRS-D03.06 FR-02a）
 *
 * - 规则列表：条件 → 候选仓序 + 选仓策略
 * - 策略类型自描述（binding_priority / region_route / stock_depth / owner_assign）
 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listDispatchRules, type DispatchRule } from '@/api/fulfill'

const rules = ref<DispatchRule[]>([])
const loading = ref(false)

const STRATEGY_LABEL: Record<string, string> = {
  binding_priority: '店铺绑定仓优先级',
  region_route: '区域路由',
  stock_depth: '库存深度优先',
  owner_assign: '货主指定仓',
  store_o2o: '门店仓 O2O（P1）',
  round_robin: '轮询均衡（P1）',
}

async function load() {
  loading.value = true
  try {
    rules.value = await listDispatchRules()
  } catch (e) {
    ElMessage.error(`加载失败：${(e as Error).message}`)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2>分仓规则管理</h2>
      <el-tag type="info" effect="plain">规则匹配：weight DESC 首个全条件命中生效，缺省按店铺绑定仓优先级</el-tag>
      <el-button @click="load">刷新</el-button>
    </div>

    <el-table :data="rules" v-loading="loading" border stripe size="small">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="rule_name" label="规则名" width="180" />
      <el-table-column label="选仓策略" width="180">
        <template #default="{ row }">
          <el-tag size="small" type="primary">
            {{ STRATEGY_LABEL[row.strategy_type] ?? row.strategy_type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="候选仓序" min-width="200">
        <template #default="{ row }">
          <el-tag v-for="b in row.branch_seq ?? []" :key="b" size="small" style="margin-right: 4px">
            {{ b }}
          </el-tag>
          <span v-if="!(row.branch_seq ?? []).length" style="color: #c0c4cc">未指定</span>
        </template>
      </el-table-column>
      <el-table-column prop="weight" label="权重" width="90" />
      <el-table-column label="缺省" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.default_flag" type="warning" size="small">是</el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="生效时段" min-width="160">
        <template #default="{ row }">
          <span v-if="row.effective_period">
            {{ (row.effective_period as any).start ?? '—' }} ~ {{ (row.effective_period as any).end ?? '—' }}
          </span>
          <span v-else style="color: #c0c4cc">不限</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'enabled' ? 'success' : 'info'" size="small">
            {{ row.status === 'enabled' ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="条件" min-width="200">
        <template #default="{ row }">
          <code style="font-size: 11px">{{ JSON.stringify(row.conditions) }}</code>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.page-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.page-head h2 { margin: 0; font-size: 18px; }
</style>
