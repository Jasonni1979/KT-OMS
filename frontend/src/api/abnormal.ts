/** 异常单域 API（SRS-D03.09 异常单与缺货处理 · W8） */
import { get, post } from '@/api/http'
import http from '@/api/http'

// ============ 类型字典 ============

export interface AbnormalType {
  id: number
  type_code: string
  type_name: string
  category: string
  default_group_id: number | null
  default_sla_hours: number
  need_abnormal_bill: number
  block_fulfill: number
  action_set: string[]
  reason_code_map: string[] | Record<string, unknown> | null
}

export interface ReasonCode {
  reason_code: string
  reason_name: string
  plugin_name: string
  level: string
  default_route: string
  default_suggest: string | null
  exc_type: string | null
}

// ============ 异常单 ============

export interface SlaStatus {
  deadline: string | null
  overdue: boolean
  remain_hours: number | null
}

/** 列表项（后端 /abnormal/list 实际返回结构） */
export interface AbnormalItem {
  id: number
  abnormal_bn: string
  order_id: number
  order_bn: string
  shop_id: number | null
  exc_type: string
  exc_category: string
  source: string
  status: string
  group_id: number | null
  op_id: number | null
  sla: SlaStatus
  create_time: string | null
  /** 详情页才有 */
  source_ref?: string
  dispatch_time?: string | null
  sla_deadline?: string | null
  escalate_level?: number
  resolve_action?: string | null
  rel_retrial_id?: number | null
  suspend_until?: string | null
  reason_detail?: Record<string, unknown> | null
  timeline?: TimelineEntry[] | null
}

export interface TimelineEntry {
  at: string
  operator: string
  action: string
  note?: string
  from?: string
  to?: string
}

export interface StockoutDetail {
  id: number
  abnormal_id?: number
  branch_id: number
  bm_id: number
  bm_number?: string
  lack_num: number
  strategy_status: string | null
  strategy_result: Record<string, unknown> | null
  oversold_flag?: number
  stock_snapshot: Record<string, unknown> | null
}

/**
 * 详情（后端 /abnormal/{id} 为**平铺结构** —— 不是 {item, stockouts} 嵌套）
 */
export interface AbnormalDetail extends AbnormalItem {
  stockouts: StockoutDetail[]
  timeline: TimelineEntry[]
}

export interface AbnormalListResult {
  items: AbnormalItem[]
  total: number
}

// ============ 动作 ============

export interface ActionItem {
  action: string
  enabled: boolean
  reason: string
}

export const ACTION_LABEL: Record<string, string> = {
  reaudit: '修复后重新审单',
  to_retrial: '转复审（改单）',
  to_aftersale: '转售后',
  suspend: '挂起',
  cancel: '取消订单',
  force_pass: '强制放行',
  refund: '退款',
}

export const ABNORMAL_STATUS_LABEL: Record<string, string> = {
  wait_dispatch: '待分派',
  assigned: '已分派',
  processing: '处理中',
  resolved: '已解决',
  cancelled: '已取消',
  suspended: '已挂起',
}

export const ABNORMAL_CATEGORY_LABEL: Record<string, string> = {
  data: '数据类',
  risk: '风控类',
  stock: '库存类',
  fulfill: '履约类',
  platform: '平台类',
  other: '其他',
}

// ============ 端点 ============

export const listAbnormalTypes = () =>
  get<{ items: AbnormalType[] }>('/abnormal/types')

export const listReasonCodes = () =>
  get<{ items: ReasonCode[] }>('/abnormal/reason-codes')

export interface AbnormalListParams {
  exc_type?: string
  status?: string
  /** 后端参数名是 exc_category（不是 category） */
  exc_category?: string
  order_id?: number
  shop_id?: number
  group_id?: number
  keyword?: string
  /** 只看未闭环 */
  only_open?: boolean
  limit?: number
  offset?: number
}

export const listAbnormals = (params?: AbnormalListParams) =>
  get<AbnormalListResult>('/abnormal/list', params as Record<string, unknown>)

export const getAbnormal = (id: number) =>
  get<AbnormalDetail>(`/abnormal/${id}`)

export const listStockouts = (params?: { abnormal_id?: number; branch_id?: number; bm_id?: number }) =>
  get<{ items: StockoutDetail[]; total: number }>(
    '/abnormal/stockouts',
    params as Record<string, unknown>,
  )

export const createAbnormal = (data: {
  order_id: number
  exc_type: string
  note: string
}) => post('/abnormal', data)

export const dispatchAbnormal = (id: number, data: { group_id: number; op_id?: number; note?: string }) =>
  post(`/abnormal/${id}/dispatch`, data)

export const startAbnormal = (id: number, data?: { note?: string }) =>
  post(`/abnormal/${id}/process`, data ?? {})

export const suspendAbnormal = (id: number, data: { until_hours: number; note?: string }) =>
  post(`/abnormal/${id}/suspend`, data)

export const resolveAbnormal = (id: number, data?: { note?: string }) =>
  post(`/abnormal/${id}/resolve`, data ?? {})

export const cancelAbnormal = (id: number, data?: { note?: string }) =>
  post(`/abnormal/${id}/cancel`, data ?? {})

export const listActions = (id: number) =>
  get<{ items: ActionItem[]; total: number }>(`/abnormal/${id}/actions`)

export interface ActionResult {
  ok: boolean
  action?: string
  abnormal_id?: number
  /** 未实现的动作（转售后 / 退款）返回 enabled=false + reason */
  enabled?: boolean
  reason?: string
  stage?: string
  closed?: boolean
  released_plans?: number
  released_reasons?: number
  retrial_id?: number
  retrial_bn?: string
  audit_decision?: string
  fail_message?: string
}

export const executeAction = (
  id: number,
  data: { action: string; note?: string; operator?: string; extra?: Record<string, unknown> },
) => post<ActionResult>(`/abnormal/${id}/action`, data)

export const autoDispatchAbnormal = (id: number) =>
  post<{
    dispatched: boolean
    group_id: number
    status: string
    decision: Record<string, unknown>
  }>(`/abnormal/${id}/auto-dispatch`, {})

export const calcStrategy = (id: number) =>
  get<{
    status: string
    candidates?: { branch_id: number; available: number; satisfied: boolean }[]
    borrow_stock?: { enabled: boolean; reason: string }
    reason?: string
  }>(`/abnormal/${id}/strategy`)

export const switchBranch = (id: number) =>
  post<Record<string, unknown>>(`/abnormal/${id}/switch-branch`, {})

export const releaseRetry = (id: number) =>
  post<Record<string, unknown>>(`/abnormal/${id}/release-retry`, {})

export const updateAbnormal = (id: number, data: object) =>
  http.put(`/abnormal/${id}`, data)
