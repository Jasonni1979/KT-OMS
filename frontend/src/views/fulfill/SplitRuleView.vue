<script setup lang="ts">
/**
 * 拆单规则管理（SRS-D03.04 FR-01b/FR-01c/FR-04a）
 *
 * - 策略注册表自描述（新增策略零引擎改动即可被引用）
 * - 规则 CRUD：一级策略 + 配置 schema + 二三级级联
 * - 保存期校验（策略 schema / 级联类型不重复 / 级联兼容清单）
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  disableSplitRule,
  listSplitRules,
  listSplitStrategies,
  saveSplitRule,
  updateSplitRule,
  type SplitRule,
  type SplitStrategyMeta,
} from '@/api/fulfill'

const rules = ref<SplitRule[]>([])
const strategies = ref<SplitStrategyMeta[]>([])
const loading = ref(false)

const dialog = ref({
  visible: false,
  saving: false,
  editingId: 0,
  form: {
    rule_name: '',
    split_type: '',
    split_config: '{}',
    split_type_2: '',
    split_config_2: '{}',
    split_type_3: '',
    split_config_3: '{}',
    scope_type: 'global',
    confirm_source: 'all',
    status: 'enabled',
  },
})

const strategyMap = computed(() => {
  const m: Record<string, SplitStrategyMeta> = {}
  strategies.value.forEach((s) => (m[s.split_type] = s))
  return m
})

/** 当前一级策略的配置 schema */
const schema = computed(() => strategyMap.value[dialog.value.form.split_type]?.config_schema ?? {})

/** 一级策略的可级联下层（getSpecial 兼容清单） */
const cascadeOptions = computed(() => {
  const cur = dialog.value.form.split_type
  const s = strategyMap.value[cur]
  if (!s) return strategies.value.map((x) => x.split_type)
  return s.special
})

/** 二级策略的可级联下层 */
const cascade2Options = computed(() => {
  const cur = dialog.value.form.split_type_2
  const s = strategyMap.value[cur]
  if (!s) return []
  return s.special
})

async function load() {
  loading.value = true
  try {
    const [rs, ss] = await Promise.all([listSplitRules(), listSplitStrategies()])
    rules.value = rs
    strategies.value = ss
  } catch (e) {
    ElMessage.error(`加载失败：${(e as Error).message}`)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  dialog.value.editingId = 0
  dialog.value.form = {
    rule_name: '',
    split_type: strategies.value[0]?.split_type ?? 'owner',
    split_config: '{}',
    split_type_2: '',
    split_config_2: '{}',
    split_type_3: '',
    split_config_3: '{}',
    scope_type: 'global',
    confirm_source: 'all',
    status: 'enabled',
  }
  dialog.value.visible = true
}

function openEdit(row: SplitRule) {
  dialog.value.editingId = row.id
  dialog.value.form = {
    rule_name: row.rule_name,
    split_type: row.split_type,
    split_config: JSON.stringify(row.split_config ?? {}, null, 2),
    split_type_2: row.split_type_2 ?? '',
    split_config_2: JSON.stringify(row.split_config_2 ?? {}, null, 2),
    split_type_3: row.split_type_3 ?? '',
    split_config_3: JSON.stringify(row.split_config_3 ?? {}, null, 2),
    scope_type: row.scope_type,
    confirm_source: row.confirm_source,
    status: row.status,
  }
  dialog.value.visible = true
}

function parseJson(text: string, label: string): Record<string, unknown> {
  try {
    return JSON.parse(text || '{}')
  } catch {
    throw new Error(`${label} 不是合法 JSON`)
  }
}

async function save() {
  dialog.value.saving = true
  try {
    const payload = {
      rule_name: dialog.value.form.rule_name,
      split_type: dialog.value.form.split_type,
      split_config: parseJson(dialog.value.form.split_config, '一级配置'),
      split_type_2: dialog.value.form.split_type_2 || null,
      split_config_2: dialog.value.form.split_type_2
        ? parseJson(dialog.value.form.split_config_2, '二级配置')
        : null,
      split_type_3: dialog.value.form.split_type_3 || null,
      split_config_3: dialog.value.form.split_type_3
        ? parseJson(dialog.value.form.split_config_3, '三级配置')
        : null,
      scope_type: dialog.value.form.scope_type,
      confirm_source: dialog.value.form.confirm_source,
      status: dialog.value.form.status,
    }
    if (dialog.value.editingId) await updateSplitRule(dialog.value.editingId, payload)
    else await saveSplitRule(payload)
    ElMessage.success('保存成功（保存期校验已通过）')
    dialog.value.visible = false
    await load()
  } catch (e) {
    ElMessage.error(`保存失败：${(e as Error).message}`)
  } finally {
    dialog.value.saving = false
  }
}

async function disable(row: SplitRule) {
  await ElMessageBox.confirm(`确认停用规则「${row.rule_name}」？`, '停用确认', {
    type: 'warning',
  })
  await disableSplitRule(row.id)
  ElMessage.success('已停用')
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2>拆单规则管理</h2>
      <el-tag type="info" effect="plain">策略注册表可插拔：新增策略零引擎改动</el-tag>
      <el-button type="primary" @click="openCreate">新建拆单规则</el-button>
    </div>

    <el-table :data="rules" v-loading="loading" border stripe size="small">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="rule_name" label="规则名" width="180" />
      <el-table-column label="一级策略" width="160">
        <template #default="{ row }">
          <el-tag size="small">{{ strategyMap[row.split_type]?.name ?? row.split_type }}</el-tag>
          <span style="margin-left: 6px; color: #909399">{{ row.split_type }}</span>
        </template>
      </el-table-column>
      <el-table-column label="级联" width="200">
        <template #default="{ row }">
          <el-tag v-if="row.split_type_2" size="small" type="warning">
            → {{ strategyMap[row.split_type_2]?.name ?? row.split_type_2 }}
          </el-tag>
          <el-tag v-if="row.split_type_3" size="small" type="info" style="margin-left: 4px">
            → {{ strategyMap[row.split_type_3]?.name ?? row.split_type_3 }}
          </el-tag>
          <span v-if="!row.split_type_2 && !row.split_type_3" style="color: #c0c4cc">无</span>
        </template>
      </el-table-column>
      <el-table-column prop="scope_type" label="生效范围" width="100" />
      <el-table-column prop="confirm_source" label="审单来源" width="100" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'enabled' ? 'success' : 'info'" size="small">
            {{ row.status === 'enabled' ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" size="small" @click="disable(row)">停用</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-card shadow="never" style="margin-top: 16px">
      <template #header>策略注册表（SRS-D03.04 FR-01b）</template>
      <el-table :data="strategies" border size="small">
        <el-table-column prop="split_type" label="类型码" width="140" />
        <el-table-column prop="name" label="名称" width="150" />
        <el-table-column prop="description" label="说明" min-width="320" />
        <el-table-column label="可作下层" min-width="180">
          <template #default="{ row }">
            <el-tag v-for="s in row.special" :key="s" size="small" style="margin-right: 4px">
              {{ strategyMap[s]?.name ?? s }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="配置项" min-width="220">
          <template #default="{ row }">
            <el-tag
              v-for="(v, k) in row.config_schema"
              :key="k"
              size="small"
              :type="v.required ? 'danger' : 'info'"
              style="margin-right: 4px"
            >
              {{ k }}{{ v.required ? '*' : '' }}
            </el-tag>
            <span v-if="Object.keys(row.config_schema).length === 0" style="color: #c0c4cc">无</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialog.visible"
      :title="dialog.editingId ? '编辑拆单规则' : '新建拆单规则'"
      width="640px"
    >
      <el-form label-width="110px" size="small">
        <el-form-item label="规则名">
          <el-input v-model="dialog.form.rule_name" placeholder="如：按货主+按仓拆单" />
        </el-form-item>
        <el-form-item label="一级策略">
          <el-select v-model="dialog.form.split_type" style="width: 100%">
            <el-option
              v-for="s in strategies"
              :key="s.split_type"
              :label="`${s.name}（${s.split_type}）`"
              :value="s.split_type"
            />
          </el-select>
          <div v-if="schema && Object.keys(schema).length" class="hint">
            配置项：{{ Object.keys(schema).join('、') }}
          </div>
        </el-form-item>
        <el-form-item label="一级配置">
          <el-input v-model="dialog.form.split_config" type="textarea" :rows="3" placeholder="{}" />
        </el-form-item>
        <el-form-item label="二级策略">
          <el-select v-model="dialog.form.split_type_2" clearable style="width: 100%">
            <el-option
              v-for="t in cascadeOptions"
              :key="t"
              :label="`${strategyMap[t]?.name ?? t}（${t}）`"
              :value="t"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="dialog.form.split_type_2" label="二级配置">
          <el-input v-model="dialog.form.split_config_2" type="textarea" :rows="2" placeholder="{}" />
        </el-form-item>
        <el-form-item label="三级策略">
          <el-select v-model="dialog.form.split_type_3" clearable style="width: 100%">
            <el-option
              v-for="t in cascade2Options"
              :key="t"
              :label="`${strategyMap[t]?.name ?? t}（${t}）`"
              :value="t"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="dialog.form.split_type_3" label="三级配置">
          <el-input v-model="dialog.form.split_config_3" type="textarea" :rows="2" placeholder="{}" />
        </el-form-item>
        <el-form-item label="生效范围">
          <el-select v-model="dialog.form.scope_type" style="width: 100%">
            <el-option label="全局" value="global" />
            <el-option label="店铺" value="shop" />
            <el-option label="订单分组" value="order_group" />
          </el-select>
        </el-form-item>
        <el-form-item label="审单来源">
          <el-select v-model="dialog.form.confirm_source" style="width: 100%">
            <el-option label="自动" value="auto" />
            <el-option label="手工" value="manual" />
            <el-option label="全部" value="all" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.page-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.page-head h2 { margin: 0; font-size: 18px; }
.hint { font-size: 12px; color: #909399; margin-top: 2px; }
</style>
