/** 审单域 API（D03.02 审单引擎 + D03.03 人工审单工作台） */
import { get, post } from '@/api/http'
import http from '@/api/http'

// ============ 审单规则 ============

export interface AuditRule {
  id: number
  rule_name: string
  conditions: { logic: string; items: { dim: string; op: string; value: unknown }[] }
  weight: number
  plugin_config: Record<string, { enable?: boolean; params?: Record<string, unknown> }> | null
  auto_confirm: number
  pass_action: string
  fail_route: Record<string, string> | null
  effective_window: { start?: string; end?: string; days?: number[] } | null
  exclude_window: { start?: string; end?: string; days?: number[] } | null
  default_audit_group: number | null
  router_num_limit: number
  status: string
  is_default: number
  version: number
}

export const listAuditRules = (status?: string) =>
  get<AuditRule[]>('/audit/rules', status ? { status } : undefined)

export const updateAuditRule = (id: number, data: object) =>
  http.put(`/audit/rules/${id}`, data)

export const dryRunRule = (ruleId: number, orderId: number) =>
  get<{
    rule_id: number
    rule_name: string
    hit: boolean
    details: { dim: string; op: string; expected: unknown; actual: unknown; hit: boolean; message: string }[]
    in_effective_window: boolean
    in_exclude_window: boolean
  }>(`/audit/rules/${ruleId}/dry-run`, { order_id: orderId })

export const matchOrderRule = (orderId: number) =>
  get<{
    rule_id: number
    rule_name: string
    auto_confirm: boolean
    auto_confirm_effective: boolean
    snapshot_id: string
    traces: { rule_id: number; rule_name: string; hit: boolean }[]
  }>(`/audit/orders/${orderId}/match`)

// ============ 审单结果 ============

export interface AuditReason {
  id: number
  plugin_name: string
  reason_code: string
  level: 'BLOCK' | 'WARN'
  description: string
  detail: Record<string, unknown> | null
  suggest_action: string
  route_target: string
  handle_status: string
}

export interface AuditOutcome {
  order_id: number
  order_bn: string
  batch_no: string
  decision: string
  plan_id: number | null
  plan_bn: string
  reasons: AuditReason[]
  traces: { plugin: string; phase: string; status: string; cost_ms: number; reason_codes: string[] }[]
  rule_id: number
  rule_name: string
  rule_snapshot_id: string
  decision_ctx: Record<string, unknown>
  cost_ms: number
}

export const submitAudit = (orderId: number, batchNo = '') =>
  post<AuditOutcome>(`/audit/orders/${orderId}/submit`, {}, { params: { batch_no: batchNo } })

export const listOrderReasons = (orderId: number, onlyOpen = false) =>
  get<AuditReason[]>(`/audit/orders/${orderId}/reasons`, { only_open: onlyOpen })

export interface PlanVersion {
  plan_id: number
  plan_bn: string
  plan_version: number
  plan_status: string
  exec_status: string
  rule_snapshot_id: string
  warehouse_alloc: Record<string, unknown>
  split_matrix: { groups: { group_key: string; branch_id: number; lines: { item_id: number; nums: number }[] }[] }
  logistics_alloc: Record<string, unknown>
  decision_by: string
  decision_time: string | null
  plugin_trace: Record<string, unknown> | null
  delivery_ids: string | null
  fail_code: string | null
}

export const listOrderPlans = (orderId: number) =>
  get<{ order_id: number; versions: PlanVersion[] }>(`/audit/orders/${orderId}/plans`)

export interface ExecResult {
  plan_id: number
  plan_bn: string
  order_id: number
  status: string
  fail_code: string
  fail_message: string
  freeze_refs: Record<string, unknown>[]
  delivery_ids: string[]
  cost_ms: number
}

export const executePlan = (planId: number, operator = '') =>
  post<ExecResult>(`/audit/plans/${planId}/execute`, {}, { params: { operator } })

export const discardPlan = (planId: number, operator = '') =>
  post<{ plan_id: number; status: string }>(`/audit/plans/${planId}/discard`, {}, { params: { operator } })

// ============ 人工审单工作台 ============

export interface QueueItem {
  task_id: number
  order_id: number
  order_bn: string
  platform_order_bn: string
  shop_id: number
  audit_status: string
  task_status: string
  assign_group: number | null
  assign_op: number | null
  assign_time: string | null
  assign_way: string | null
  paid_amount: number
  buyer_nick: string
  buyer_memo: string
  pay_time: string | null
  sla_deadline: string | null
  overtime_level: number
  reason_codes: string[]
}

export const listAuditQueue = (params?: {
  shop_id?: number
  reason_code?: string
  assign_op?: number
  task_status?: string
  limit?: number
}) => get<{ total: number; items: QueueItem[] }>('/audit/workbench/queue', params)

export interface WorkbenchSplitMatrix {
  groups?: { group_key?: string; branch_id?: number; lines?: { item_id: number; nums: number }[] }[]
}

export interface WorkbenchDetail {
  order: Record<string, any>
  items: { id: number; bm_number: string; bm_name: string; nums: number; paid_amount: number; owner_id: number }[]
  receiver: { province: string; city: string; district: string; town: string; is_cipher: number }
  reasons: AuditReason[]
  decision_draft: {
    plan_id: number
    plan_bn: string
    plan_version: number
    plan_status: string
    exec_status: string
    warehouse_alloc: { branch_id?: number; branch_name?: string }
    split_matrix: WorkbenchSplitMatrix
    logistics_alloc: { carrier_code?: string; carrier_name?: string }
  } | null
  task: {
    task_id: number
    task_status: string
    assign_group: number | null
    assign_op: number | null
    lock_op: number | null
    lock_expire: string | null
    sla_deadline: string | null
  } | null
}

export const getWorkbenchDetail = (orderId: number) =>
  get<WorkbenchDetail>(`/audit/workbench/orders/${orderId}`)

export const passAudit = (orderId: number, payload: object) =>
  post<ExecResult>(`/audit/workbench/orders/${orderId}/pass`, payload)

export const rejectAudit = (orderId: number, payload: object) =>
  post<{ order_id: number; audit_status: string; reason_code: string }>(
    `/audit/workbench/orders/${orderId}/reject`, payload)

export interface AuditGroup {
  id: number
  group_name: string
  org_id: number | null
  leader_op_id: number | null
  members: { op_id: number; name: string; duty_status: string; task_limit: number }[]
  default_shop_scope: unknown
  status: string
}

export const listAuditGroups = () => get<AuditGroup[]>('/audit/workbench/groups')

export const listDispatchRules = () => get<any[]>('/audit/workbench/dispatch-rules')

export const autoDispatch = (orderId: number, reasonCodes: string[]) =>
  post<{
    order_id: number
    task_id: number | null
    assign_group: number | null
    assign_op: number | null
    route: string
    reason: string
  }>('/audit/workbench/dispatch', { order_id: orderId, reason_codes: reasonCodes })

// ============ 枚举映射 ============

export const REASON_LEVEL_LABEL: Record<string, { text: string; type: string }> = {
  BLOCK: { text: '拦截', type: 'danger' },
  WARN: { text: '提示', type: 'warning' },
}

export const ROUTE_LABEL: Record<string, { text: string; type: string }> = {
  manual: { text: '转人工', type: 'warning' },
  shortage: { text: '缺货', type: 'danger' },
  retrial: { text: '复审', type: 'info' },
  pool: { text: '回池', type: 'info' },
  hold: { text: '挂起', type: 'info' },
}

export const DECISION_LABEL: Record<string, { text: string; type: string }> = {
  auto_pass: { text: '自动通过', type: 'success' },
  manual: { text: '转人工', type: 'warning' },
  shortage: { text: '缺货', type: 'danger' },
  retrial: { text: '复审', type: 'info' },
  pool: { text: '回池', type: 'info' },
  hold: { text: '挂起', type: 'info' },
}

export const TASK_STATUS_LABEL: Record<string, { text: string; type: string }> = {
  wait_assign: { text: '待分派', type: 'info' },
  assigned: { text: '已分派', type: 'primary' },
  processing: { text: '处理中', type: 'warning' },
  done: { text: '已完结', type: 'success' },
  rejected: { text: '已驳回', type: 'danger' },
  closed: { text: '已关闭', type: 'info' },
}
