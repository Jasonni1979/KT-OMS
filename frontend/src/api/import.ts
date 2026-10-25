/** 导入中心 API（SRS-D01.06） */
import { get, post } from '@/api/http'
import http from '@/api/http'

export interface ImportTemplate {
  template_code: string
  template_name: string
  domain_code: string
  entity_ref: string
  version: number
  columns: { col_name: string; field_map: string; required: boolean; value_type: string; desc: string }[]
}
export interface ImportTask {
  id: number
  task_bn: string
  template_code: string
  status: number
  row_count_total: number
  progress: { processed: number; success: number; fail: number; percent: number } | null
  result: {
    success_rows: number; fail_rows: number; error_report_ref: string
    cluster_summary: { error_code: string; count: number; sample_rows: number[] }[]
  } | null
  error_report_ref: string
  creator: string
  cost_ms: number
  create_time: string
}
export interface ImportError {
  id: number
  row_no: number
  error_stage: string
  error_code: string
  error_message: string
  row_snapshot: unknown
}

export const listImportTemplates = () => get<ImportTemplate[]>('/import/templates')
export const listImportTasks = (limit = 50) => get<ImportTask[]>('/import/tasks', { limit })
export const getImportTask = (id: number) => get<ImportTask>(`/import/tasks/${id}`)
export const listImportTaskErrors = (id: number) => get<ImportError[]>(`/import/tasks/${id}/errors`)
export const runImportTask = (id: number) => post(`/import/tasks/${id}/run`, {})

/** 上传文件创建任务（multipart） */
export async function createImportTask(file: File, templateCode: string, creator = ''): Promise<{ id: number }> {
  const form = new FormData()
  form.append('file', file)
  form.append('template_code', templateCode)
  form.append('creator', creator)
  const res = await http.post('/import/tasks', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res
}

/** 模板下载（返回 blob） */
export async function downloadTemplate(code: string): Promise<Blob> {
  const res = await http.get(`/import/templates/${code}/file`, { responseType: 'blob' })
  return res.data
}

export const IMPORT_STATUS_LABEL: Record<number, { text: string; type: string }> = {
  0: { text: '待执行', type: 'info' },
  1: { text: '执行中', type: 'primary' },
  2: { text: '成功', type: 'success' },
  3: { text: '部分成功', type: 'warning' },
  4: { text: '失败', type: 'danger' },
  5: { text: '已取消', type: 'info' },
}
export const ERROR_STAGE_LABEL: Record<string, string> = {
  format: '格式校验',
  business: '业务校验',
  commit: '批次提交',
}
