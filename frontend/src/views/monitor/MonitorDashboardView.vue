<script setup lang="ts">
/**
 * 履约监控看板（SRS-D11.03 最小可用版 · W8-3）
 *
 * 顶部 4 张指标卡：拉单水位落后 / 审单积压 / 回传失败 / 未闭环异常单
 * 下方分域明细：拉单水位表、审单积压分级、回传失败分级、异常单类型分布
 *
 * ⚠ 口径：实时快照（直查业务表），非 D11.01 报表口径 —— 页面底部明示。
 */
import { computed, onMounted, ref } from 'vue'
import { getMonitorOverview, type MonitorOverview } from '@/api/monitor'

const data = ref<MonitorOverview | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    data.value = await getMonitorOverview()
  } finally {
    loading.value = false
  }
}

function fmtLag(sec: number) {
  if (sec < 0) return '—'
  if (sec < 60) return `${sec} 秒`
  if (sec < 3600) return `${Math.round(sec / 60)} 分钟`
  return `${(sec / 3600).toFixed(1)} 小时`
}

const typeEntries = computed(() => {
  const m = data.value?.abnormal_realtime.by_type ?? {}
  return Object.entries(m).sort((a, b) => b[1] - a[1])
})

const categoryEntries = computed(() => {
  const m = data.value?.abnormal_realtime.by_category ?? {}
  return Object.entries(m).sort((a, b) => b[1] - a[1])
})

const levelEntries = computed(() => {
  const m = data.value?.writeback_failures.by_err_level ?? {}
  return Object.entries(m).sort((a, b) => b[1] - a[1])
})

const classEntries = computed(() => {
  const m = data.value?.writeback_failures.by_err_class ?? {}
  return Object.entries(m).sort((a, b) => b[1] - a[1])
})

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <div class="page-head">
      <div>
        <h2>履约监控看板</h2>
        <p class="sub">SRS-D11.03 · 拉单水位 / 审单积压 / 回传失败 / 异常单实时</p>
      </div>
      <el-button @click="load">刷新</el-button>
    </div>

    <div class="cards">
      <el-card v-for="c in data?.cards ?? []" :key="c.key" shadow="never" class="card">
        <div class="card-body">
          <div class="card-title">{{ c.title }}</div>
          <div class="card-value" :class="c.level">
            {{ c.value }}<span class="unit">{{ c.unit }}</span>
          </div>
          <div v-if="c.hint" class="card-hint">
            {{ c.hint }}：{{ c.total }}
          </div>
          <el-progress
            v-if="c.total > 0 && c.value > 0"
            :percentage="Math.min(100, Math.round((c.total / c.value) * 100))"
            :status="c.level === 'danger' ? 'exception' : c.level === 'warning' ? 'warning' : 'success'"
            :show-text="false"
            :stroke-width="4"
          />
        </div>
      </el-card>
    </div>

    <el-row :gutter="12" class="row">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><b>拉单水位</b></template>
          <el-table :data="data?.pull_watermark.items ?? []" size="small" border empty-text="无水位记录">
            <el-table-column label="店铺ID" prop="shop_id" width="90" />
            <el-table-column label="渠道" prop="channel" width="90" />
            <el-table-column label="最近拉单" prop="last_download_time" width="170" />
            <el-table-column label="落后" width="110">
              <template #default="{ row }">
                <span :class="row.over_threshold ? 'bad' : ''">{{ fmtLag(row.lag_seconds) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="阈值(秒)" prop="lag_alert_threshold_sec" width="100" />
          </el-table>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card shadow="never">
          <template #header><b>审单积压</b></template>
          <el-row :gutter="8" class="mini">
            <el-col :span="8">
              <div class="mini-item">
                <div class="mini-label">待审总数</div>
                <div class="mini-value">{{ data?.audit_backlog.pending ?? 0 }}</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="mini-item">
                <div class="mini-label">SLA 超期</div>
                <div class="mini-value bad">{{ data?.audit_backlog.overdue ?? 0 }}</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="mini-item">
                <div class="mini-label">超 72h</div>
                <div class="mini-value bad">
                  {{ data?.audit_backlog.age_buckets?.gt_72h ?? 0 }}
                </div>
              </div>
            </el-col>
          </el-row>
          <div class="section-title">按任务状态</div>
          <div class="kv">
            <span v-for="(v, k) in data?.audit_backlog.by_status ?? {}" :key="k" class="kv-item">
              {{ k }} <b>{{ v }}</b>
            </span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="12" class="row">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header><b>回传失败</b></template>
          <el-row :gutter="8" class="mini">
            <el-col :span="6">
              <div class="mini-item">
                <div class="mini-label">平台未处理</div>
                <div class="mini-value bad">{{ data?.writeback_failures.platform_pending ?? 0 }}</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-item">
                <div class="mini-label">平台死信</div>
                <div class="mini-value">{{ data?.writeback_failures.platform_dead ?? 0 }}</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-item">
                <div class="mini-label">WMS 未处理</div>
                <div class="mini-value bad">{{ data?.writeback_failures.wms_pending ?? 0 }}</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="mini-item">
                <div class="mini-label">WMS 死信</div>
                <div class="mini-value">{{ data?.writeback_failures.wms_dead ?? 0 }}</div>
              </div>
            </el-col>
          </el-row>
          <div class="section-title">平台侧错误级别</div>
          <div class="kv">
            <span v-for="(v, k) in Object.fromEntries(levelEntries)" :key="k" class="kv-item">
              {{ k }} <b>{{ v }}</b>
            </span>
            <span v-if="!levelEntries.length" class="kv-empty">无</span>
          </div>
          <div class="section-title">通道侧错误分类</div>
          <div class="kv">
            <span v-for="(v, k) in Object.fromEntries(classEntries)" :key="k" class="kv-item">
              {{ k }} <b>{{ v }}</b>
            </span>
            <span v-if="!classEntries.length" class="kv-empty">无</span>
          </div>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card shadow="never">
          <template #header><b>异常单实时</b></template>
          <el-row :gutter="8" class="mini">
            <el-col :span="8">
              <div class="mini-item">
                <div class="mini-label">未闭环</div>
                <div class="mini-value">{{ data?.abnormal_realtime.open_total ?? 0 }}</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="mini-item">
                <div class="mini-label">SLA 超期</div>
                <div class="mini-value bad">{{ data?.abnormal_realtime.overdue ?? 0 }}</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="mini-item">
                <div class="mini-label">账龄 >72h</div>
                <div class="mini-value bad">
                  {{ data?.abnormal_realtime.age_buckets?.gt_72h ?? 0 }}
                </div>
              </div>
            </el-col>
          </el-row>
          <div class="section-title">按类型</div>
          <div class="kv">
            <span v-for="[k, v] in typeEntries" :key="k" class="kv-item">
              {{ k }} <b>{{ v }}</b>
            </span>
            <span v-if="!typeEntries.length" class="kv-empty">无</span>
          </div>
          <div class="section-title">按分类</div>
          <div class="kv">
            <span v-for="[k, v] in categoryEntries" :key="k" class="kv-item">
              {{ k }} <b>{{ v }}</b>
            </span>
            <span v-if="!categoryEntries.length" class="kv-empty">无</span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-alert
      v-if="data?.caliber_note"
      type="info"
      :closable="false"
      :title="`口径说明：${data.caliber_note}`"
      style="margin-top: 12px"
    />
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; }
.page-head h2 { margin: 0 0 4px; font-size: 18px; }
.sub { margin: 0; color: #909399; font-size: 12px; }
.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 12px; }
.card-body { text-align: left; }
.card-title { color: #909399; font-size: 12px; }
.card-value { font-size: 26px; font-weight: 600; line-height: 1.4; }
.card-value.ok { color: #67c23a; }
.card-value.warning { color: #e6a23c; }
.card-value.danger { color: #f56c6c; }
.unit { font-size: 12px; margin-left: 2px; color: #909399; font-weight: 400; }
.card-hint { font-size: 11px; color: #909399; margin-bottom: 4px; }
.row { margin-bottom: 12px; }
.mini { margin-bottom: 10px; }
.mini-item { border: 1px solid #ebeef5; border-radius: 4px; padding: 8px 10px; }
.mini-label { color: #909399; font-size: 11px; }
.mini-value { font-size: 20px; font-weight: 600; }
.mini-value.bad { color: #f56c6c; }
.section-title { margin: 10px 0 6px; font-size: 12px; color: #606266; font-weight: 600; }
.kv { display: flex; gap: 10px; flex-wrap: wrap; }
.kv-item { font-size: 12px; color: #606266; background: #f5f7fa; padding: 2px 8px; border-radius: 3px; }
.kv-empty { color: #c0c4cc; font-size: 12px; }
</style>
