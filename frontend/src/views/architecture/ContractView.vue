<template>
  <div class="contract-page">
    <div class="page-head">
      <div>
        <h2>架构契约</h2>
        <p class="sub">
          契约中心（P0）的可视化 —— 枚举 / 状态机 / 表所有权 / 对外接口的<b>唯一来源</b>。
          数据直接来自 <code>docs/架构/modules/</code> 与 <code>app/contracts/</code>，无副本。
        </p>
      </div>
      <el-button :loading="loading" @click="loadAll">
        <el-icon><Refresh /></el-icon>&nbsp;刷新
      </el-button>
    </div>

    <!-- 指标卡 -->
    <el-row :gutter="12" class="stat-row">
      <el-col v-for="c in stats" :key="c.key" :span="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value">{{ c.value }}</div>
          <div class="stat-title">{{ c.title }}</div>
          <div class="stat-hint">{{ c.hint }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 模块契约 -->
    <div class="section-title">
      <span class="dot" />
      模块契约
      <span class="muted">（点击卡片看完整契约）</span>
    </div>

    <el-row :gutter="12">
      <el-col v-for="m in overview?.modules ?? []" :key="m.code" :span="6">
        <el-card shadow="hover" class="mod-card" @click="open(m)">
          <div class="mod-head">
            <span class="mod-code">{{ m.code }}</span>
            <span class="mod-name">{{ m.title.replace(/^M\d+\s*/, '') }}</span>
          </div>
          <div class="mod-duty">{{ m.duty }}</div>
          <div class="mod-tags">
            <el-tag size="small" type="info" effect="plain">
              {{ m.services.length }} service
            </el-tag>
            <el-tag size="small" type="info" effect="plain">
              {{ m.write_tables.length }} 表
            </el-tag>
            <el-tag size="small" type="success" effect="plain">
              {{ m.read_apis.length + m.write_apis.length }} 接口
            </el-tag>
            <el-tag v-if="m.todos.length" size="small" type="warning" effect="plain">
              {{ m.todos.length }} 待收口
            </el-tag>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 枚举契约 -->
    <div class="section-title">
      <span class="dot" />
      枚举契约
      <span class="muted">（DDL COMMENT 自动生成 · 数值与字符串两类）</span>
    </div>

    <el-card shadow="never">
      <div class="enum-bar">
        <el-input
          v-model="kw"
          placeholder="搜索列名或常量名，如 ord_abnormal / AFT_REFUND"
          clearable
          size="default"
          class="enum-search"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <div class="enum-dist">
          <el-tag
            v-for="s in overview?.enum_by_schema ?? []"
            :key="s.schema"
            size="small"
            effect="plain"
            class="dist-tag"
          >
            {{ s.schema }} {{ s.count }}
          </el-tag>
        </div>
      </div>

      <el-table :data="enums" v-loading="enumLoading" size="small" max-height="420">
        <el-table-column prop="column" label="列" min-width="240" />
        <el-table-column prop="const" label="常量" min-width="220" />
        <el-table-column label="类型" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.kind === 'int' ? '' : 'warning'" effect="plain">
              {{ row.kind }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="取值" min-width="320">
          <template #default="{ row }">
            <span class="vals">
              <span v-for="(label, code) in row.values" :key="code" class="val">
                <code>{{ code }}</code>={{ label }}
              </span>
            </span>
          </template>
        </el-table-column>
        <template #empty>
          <span class="muted">没有匹配的枚举列</span>
        </template>
      </el-table>
      <div v-if="enumTotal > enums.length" class="more-hint">
        仅显示前 {{ enums.length }} / {{ enumTotal }} 条，请用搜索缩小范围
      </div>
    </el-card>

    <!-- 模块详情抽屉 -->
    <el-drawer v-model="drawer" size="62%" :title="cur?.title ?? ''" direction="rtl">
      <div v-if="cur" class="detail">
        <div class="detail-block">
          <div class="block-title">职责</div>
          <p class="duty-text">{{ cur.duty }}</p>
          <div class="svc-line">
            <span class="muted">收编 service：</span>
            <code v-for="s in cur.services" :key="s" class="svc">{{ s }}</code>
          </div>
        </div>

        <div class="detail-block">
          <div class="block-title">
            可写表
            <span class="muted">（{{ cur.write_tables.length }} 张 · 一表一写者）</span>
          </div>
          <div v-for="t in cur.table_summary" :key="t.schema" class="schema-group">
            <div class="schema-name">
              {{ t.schema }}<span class="muted">（{{ t.count }} 张）</span>
            </div>
            <div class="table-list">
              <code v-for="t2 in cur.write_tables.filter((x) => x.startsWith(t.schema + '.'))" :key="t2" class="tbl">
                {{ t2.split('.')[1] }}
              </code>
            </div>
          </div>
        </div>

        <div class="detail-block">
          <div class="block-title">对外只读接口 <span class="muted">（跨模块可自由调用）</span></div>
          <el-table :data="cur.read_apis" size="small" :show-header="true">
            <el-table-column prop="name" label="接口" min-width="240" />
            <el-table-column prop="desc" label="说明" min-width="200" />
            <template #empty><span class="muted">无</span></template>
          </el-table>
        </div>

        <div class="detail-block">
          <div class="block-title">对外写接口 <span class="muted">（跨模块调用须登记）</span></div>
          <el-table :data="cur.write_apis" size="small">
            <el-table-column prop="name" label="接口" min-width="240" />
            <el-table-column prop="desc" label="说明" min-width="200" />
            <template #empty><span class="muted">无</span></template>
          </el-table>
        </div>

        <div class="detail-block">
          <div class="block-title">允许的跨模块调用</div>
          <el-table :data="cur.allowed_deps" size="small">
            <el-table-column prop="module" label="下游" width="90" />
            <el-table-column prop="access" label="类型" width="90" />
            <el-table-column prop="note" label="说明" min-width="260" />
            <template #empty><span class="muted">不依赖其它模块</span></template>
          </el-table>
        </div>

        <div class="detail-block">
          <div class="block-title">禁止</div>
          <ul class="forbid">
            <li v-for="(f, i) in cur.forbidden" :key="i">{{ f }}</li>
          </ul>
        </div>

        <div v-if="cur.todos.length" class="detail-block">
          <div class="block-title">已知待收口点</div>
          <ul class="todo">
            <li v-for="(t, i) in cur.todos" :key="i">{{ t }}</li>
          </ul>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import { getContracts, listEnums, type ContractsOverview, type EnumItem, type ModuleContract } from '@/api/architecture'

const overview = ref<ContractsOverview | null>(null)
const enums = ref<EnumItem[]>([])
const enumTotal = ref(0)
const loading = ref(false)
const enumLoading = ref(false)
const kw = ref('')
const drawer = ref(false)
const cur = ref<ModuleContract | null>(null)

const stats = computed(() => [
  {
    key: 'm',
    title: '业务模块',
    value: overview.value?.module_count ?? 0,
    hint: '契约化模块（不含仿真工具域）',
  },
  {
    key: 'e',
    title: '枚举契约列',
    value: overview.value?.enum_count ?? 0,
    hint: 'DDL COMMENT 自动生成',
  },
  {
    key: 't',
    title: '已归属表',
    value: overview.value?.total_write_tables ?? 0,
    hint: '一表一写者（表所有权）',
  },
  {
    key: 'd',
    title: '契约漂移',
    value: overview.value?.drift_count ?? -1,
    hint:
      overview.value?.drift_count === -1
        ? '门禁不可用'
        : '实时跑契约门禁的结果（0 = 无漂移）',
  },
])

function open(m: ModuleContract) {
  cur.value = m
  drawer.value = true
}

async function loadEnums() {
  enumLoading.value = true
  try {
    const r = await listEnums(kw.value || undefined, 200)
    enums.value = r.items
    enumTotal.value = r.total
  } catch (e) {
    ElMessage.error('枚举契约加载失败')
  } finally {
    enumLoading.value = false
  }
}

async function loadAll() {
  loading.value = true
  try {
    overview.value = await getContracts()
    await loadEnums()
  } catch (e) {
    ElMessage.error('契约加载失败')
  } finally {
    loading.value = false
  }
}

let timer: number | undefined
watch(kw, () => {
  if (timer) window.clearTimeout(timer)
  timer = window.setTimeout(loadEnums, 300)
})

onMounted(loadAll)
</script>

<style scoped>
.contract-page {
  padding: 16px 20px 32px;
}
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}
.page-head h2 {
  margin: 0 0 6px;
  font-size: 17px;
  font-weight: 500;
}
.sub {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}
.sub b {
  color: var(--el-color-primary);
  font-weight: 500;
}
.stat-row {
  margin-bottom: 18px;
}
.stat-card :deep(.el-card__body) {
  padding: 14px 16px;
}
.stat-value {
  font-size: 24px;
  font-weight: 500;
  line-height: 1.2;
  color: var(--el-color-primary);
}
.stat-title {
  font-size: 13px;
  margin-top: 4px;
}
.stat-hint {
  font-size: 11px;
  color: var(--el-text-color-tertiary);
  margin-top: 2px;
}
.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 500;
  margin: 20px 0 10px;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--el-color-primary);
}
.muted {
  font-size: 11px;
  font-weight: 400;
  color: var(--el-text-color-tertiary);
}
.mod-card {
  cursor: pointer;
  margin-bottom: 12px;
}
.mod-card :deep(.el-card__body) {
  padding: 12px 14px;
}
.mod-head {
  display: flex;
  align-items: baseline;
  gap: 7px;
  margin-bottom: 6px;
}
.mod-code {
  font-size: 12px;
  font-weight: 500;
  color: var(--el-color-primary);
  border: 1px solid var(--el-color-primary-light-5);
  border-radius: 4px;
  padding: 0 5px;
}
.mod-name {
  font-size: 13px;
  font-weight: 500;
}
.mod-duty {
  font-size: 11px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
  min-height: 34px;
  margin-bottom: 8px;
}
.mod-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.enum-bar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.enum-search {
  width: 320px;
}
.enum-dist {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.dist-tag {
  font-size: 11px;
}
.vals {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: 11px;
}
.val code {
  color: var(--el-color-primary);
  margin-right: 2px;
}
.more-hint {
  margin-top: 8px;
  font-size: 11px;
  color: var(--el-text-color-tertiary);
}
.detail {
  padding-right: 8px;
}
.detail-block {
  margin-bottom: 22px;
}
.block-title {
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 8px;
  padding-left: 8px;
  border-left: 3px solid var(--el-color-primary);
}
.duty-text {
  margin: 0 0 8px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-primary);
}
.svc-line {
  font-size: 11px;
}
.svc,
.tbl {
  display: inline-block;
  font-family: var(--el-font-family-monospace, monospace);
  font-size: 11px;
  background: var(--el-fill-color-light);
  border-radius: 3px;
  padding: 1px 5px;
  margin: 2px 4px 2px 0;
}
.schema-group {
  margin-bottom: 10px;
}
.schema-name {
  font-size: 12px;
  font-weight: 500;
  margin-bottom: 4px;
}
.table-list {
  line-height: 1.9;
}
.forbid,
.todo {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.9;
  color: var(--el-text-color-regular);
}
.todo {
  color: var(--el-color-warning);
}
</style>
