<script setup lang="ts">
/** 导入中心（SRS-D01.06）：模板下载 → 上传文件 → 执行 → 错误报告 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ERROR_STAGE_LABEL, IMPORT_STATUS_LABEL, createImportTask, downloadTemplate,
  listImportTaskErrors, listImportTasks, listImportTemplates, runImportTask,
  type ImportError, type ImportTask, type ImportTemplate,
} from '@/api/import'

const templates = ref<ImportTemplate[]>([])
const tasks = ref<ImportTask[]>([])
const loading = ref(false)
const running = ref(false)

const upload = reactive({
  templateCode: '',
  file: null as File | null,
})

const errorDrawer = reactive({
  visible: false,
  task: null as ImportTask | null,
  errors: [] as ImportError[],
})

async function loadTemplates() {
  templates.value = await listImportTemplates()
  if (!upload.templateCode && templates.value.length) {
    upload.templateCode = templates.value[0].template_code
  }
}

async function loadTasks() {
  loading.value = true
  try {
    tasks.value = await listImportTasks()
  } finally {
    loading.value = false
  }
}

function onFileChange(file: any) {
  upload.file = file?.raw ?? null
}

async function doDownload(code: string) {
  const blob = await downloadTemplate(code)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${code}_template.xlsx`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('模板已下载')
}

async function doUpload() {
  if (!upload.file) {
    ElMessage.warning('请先选择文件')
    return
  }
  const res = await createImportTask(upload.file, upload.templateCode)
  ElMessage.success(`任务已创建：${res.id}`)
  upload.file = null
  await loadTasks()
}

async function doRun(task: ImportTask) {
  running.value = true
  try {
    const r = await runImportTask(task.id)
    const d = r as unknown as { status: number; result: { success_rows: number; fail_rows: number } }
    if (d.status === 2) {
      ElMessage.success(`导入成功：${d.result.success_rows} 行`)
    } else if (d.status === 3) {
      ElMessage.warning(`部分成功：成功 ${d.result.success_rows} 行 / 失败 ${d.result.fail_rows} 行`)
    } else {
      ElMessage.error('导入失败')
    }
    await loadTasks()
  } finally {
    running.value = false
  }
}

async function openErrors(task: ImportTask) {
  errorDrawer.task = task
  errorDrawer.errors = await listImportTaskErrors(task.id)
  errorDrawer.visible = true
}

onMounted(() => { loadTemplates(); loadTasks() })
</script>

<template>
  <div>
    <el-card style="margin-bottom:16px">
      <template #header><b>导入模板</b></template>
      <el-table :data="templates" size="small" border>
        <el-table-column prop="template_name" label="模板名称" min-width="160" />
        <el-table-column prop="template_code" label="模板编码" width="180" />
        <el-table-column prop="domain_code" label="归属域" width="80" />
        <el-table-column label="列数" width="70">
          <template #default="{ row }">{{ row.columns.length }}</template>
        </el-table-column>
        <el-table-column label="必填列" min-width="220">
          <template #default="{ row }">
            <el-tag v-for="c in row.columns.filter((x: any) => x.required)" :key="c.col_name"
              size="small" type="warning" style="margin-right:4px">{{ c.col_name }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="doDownload(row.template_code)">
              下载模板
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card style="margin-bottom:16px">
      <template #header><b>上传导入</b></template>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <el-select v-model="upload.templateCode" placeholder="选择模板" style="width:260px">
          <el-option v-for="t in templates" :key="t.template_code"
            :label="t.template_name" :value="t.template_code" />
        </el-select>
        <el-upload :auto-upload="false" :limit="1" :on-change="onFileChange" accept=".xlsx,.csv">
          <el-button size="small">选择文件</el-button>
        </el-upload>
        <el-button size="small" type="primary" @click="doUpload">上传并创建任务</el-button>
        <span style="color:#999;font-size:12px">支持 xlsx / csv（GBK/UTF-8 自动识别），单文件 ≤200MB</span>
      </div>
    </el-card>

    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b>导入任务</b>
          <el-button size="small" @click="loadTasks">刷新</el-button>
        </div>
      </template>
      <el-table v-loading="loading" :data="tasks" stripe size="small">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="task_bn" label="任务号" width="210" />
        <el-table-column prop="template_code" label="模板" width="170" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="(IMPORT_STATUS_LABEL[row.status]?.type as any) ?? 'info'">
              {{ IMPORT_STATUS_LABEL[row.status]?.text ?? row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" min-width="180">
          <template #default="{ row }">
            <el-progress v-if="row.progress" :percentage="row.progress.percent"
              :status="row.status === 2 ? 'success' : row.status === 4 ? 'exception' : undefined" />
            <span v-else style="color:#999">—</span>
          </template>
        </el-table-column>
        <el-table-column label="成功/失败" width="100">
          <template #default="{ row }">
            <span v-if="row.result" style="color:#67c23a">{{ row.result.success_rows }}</span>
            <span v-if="row.result" style="color:#f56c6c"> / {{ row.result.fail_rows }}</span>
            <span v-else style="color:#999">—</span>
          </template>
        </el-table-column>
        <el-table-column label="错误聚类" min-width="200">
          <template #default="{ row }">
            <el-tag v-for="c in (row.result?.cluster_summary ?? []).slice(0, 3)" :key="c.error_code"
              size="small" type="warning" style="margin-right:4px">
              {{ c.error_code }}×{{ c.count }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="cost_ms" label="耗时(ms)" width="100" />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" :loading="running" @click="doRun(row)">
              {{ row.status === 0 ? '执行' : '重跑' }}
            </el-button>
            <el-button size="small" link type="warning" @click="openErrors(row)">错误明细</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-drawer v-model="errorDrawer.visible" title="导入错误明细" size="760px">
      <el-descriptions v-if="errorDrawer.task" :column="3" border size="small" style="margin-bottom:12px">
        <el-descriptions-item label="任务号">{{ errorDrawer.task.task_bn }}</el-descriptions-item>
        <el-descriptions-item label="模板">{{ errorDrawer.task.template_code }}</el-descriptions-item>
        <el-descriptions-item label="总行数">{{ errorDrawer.task.row_count_total }}</el-descriptions-item>
      </el-descriptions>
      <el-table :data="errorDrawer.errors" size="small" border>
        <el-table-column prop="row_no" label="行号" width="70" />
        <el-table-column label="阶段" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.error_stage === 'format' ? 'info' : 'warning'">
              {{ ERROR_STAGE_LABEL[row.error_stage] ?? row.error_stage }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="error_code" label="错误码" width="200" />
        <el-table-column prop="error_message" label="错误消息" min-width="260" />
      </el-table>
    </el-drawer>
  </div>
</template>
