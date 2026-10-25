/** 履约域 API（W6：D03.06 分仓 + D03.04 拆单 + D03.07 发货单） */
import { get, post } from '@/api/http'
import http from '@/api/http'

// ============ D03.06 分仓 ============

export interface BranchCandidate {
  branch_id: number
  branch_name: string
  priority: number
  source: string
  owner_ids: number[]
  region_code: string
  fulfill_rate: number
  available_map: Record<string, number>
}

export interface DispatchPlanView {
  found: boolean
  plan_id?: number
  round_no?: number
  mode?: string
  split_required?: boolean
  alloc?: Record<string, Record<string, number>>
  lack_detail?: { gaps?: { order_item_id: number; bm_number: string; need: number; gap: number }[]; gap_total?: number }
  candidates?: BranchCandidate[]
  rule_hit?: Record<string, unknown>
}

export interface DispatchResult {
  ok: boolean
  mode: string
  alloc: Record<string, Record<string, number>>
  candidates: BranchCandidate[]
  fulfill_snapshot: { branches?: BranchCandidate[] }
  lack_detail: { gaps?: unknown[]; gap_total?: number }
  rule_hit: Record<string, unknown>
  fail_code: string
  fail_message: string
  split_required: boolean
  lack_route: string
  plan_id: number
  round_no: number
  cost_ms: number
}

export const dispatchOrder = (orderId: number, source = 'auto') =>
  post<DispatchResult>(`/dispatch/orders/${orderId}`, undefined, { params: { source } })

export const getDispatchView = (orderId: number) =>
  get<DispatchPlanView>(`/dispatch/orders/${orderId}/view`)

export const retryDispatch = (orderId: number, excludeBranches: number[] = []) =>
  post<DispatchResult>(`/dispatch/orders/${orderId}/retry`, undefined, {
    params: { exclude_branches: excludeBranches }
  })

export const changeBranch = (
  orderId: number,
  newBranchId: number,
  reason: string,
  forced = false
) =>
  post<DispatchResult>(`/dispatch/orders/${orderId}/change-branch`, {
    new_branch_id: newBranchId,
    reason,
    forced
  })

export interface DispatchRule {
  id: number
  rule_name: string
  conditions: Record<string, unknown>
  strategy_type: string
  branch_seq: number[] | null
  weight: number
  effective_period: Record<string, unknown> | null
  exclude_period: Record<string, unknown> | null
  default_flag: number
  status: string
}

export const listDispatchRules = () => get<DispatchRule[]>('/dispatch/rules')

// ============ D03.04 拆单 ============

export interface SplitStrategyMeta {
  split_type: string
  name: string
  description: string
  config_schema: Record<string, { type?: string; required?: boolean; min?: number }>
  special: string[]
}

export interface SplitRule {
  id: number
  owner_id: number
  rule_name: string
  split_type: string
  split_config: Record<string, unknown>
  split_type_2: string | null
  split_config_2: Record<string, unknown> | null
  split_type_3: string | null
  split_config_3: Record<string, unknown> | null
  scope_type: string
  scope_ref: Record<string, unknown> | null
  confirm_source: string
  status: string
}

export interface SplitGroup {
  group_key: string
  items: { item_id: number; nums: number }[]
  attrs: { owner_id?: number; branch_id?: number; virtual?: boolean; hold?: boolean }
}

export interface SplitOutcome {
  ok: boolean
  groups: SplitGroup[]
  fail_code: string
  fail_detail: Record<string, unknown>
  trace_id: number
  round_no: number
  cost_ms: number
}

export const listSplitStrategies = () => get<SplitStrategyMeta[]>('/split/strategies')
export const listSplitRules = () => get<SplitRule[]>('/split/rules')

export const saveSplitRule = (data: Partial<SplitRule>) => post<SplitRule>('/split/rules', data)
export const updateSplitRule = (id: number, data: Partial<SplitRule>) =>
  http.put(`/split/rules/${id}`, data)
export const disableSplitRule = (id: number) => http.delete(`/split/rules/${id}`)

export const splitOrder = (
  orderId: number,
  splitRuleId: number,
  context: Record<string, unknown> = {},
  source = 'auto'
) => post<SplitOutcome>(`/split/orders/${orderId}`, {
  split_rule_id: splitRuleId,
  context,
  source
})

export const manualSplit = (
  orderId: number,
  groups: { group_key: string; items: { item_id: number; nums: number }[] }[]
) => post<SplitOutcome>(`/split/orders/${orderId}/manual`, { groups })

export interface SplitTrace {
  id: number
  round_no: number
  split_rule_id: number
  rule_snapshot: Record<string, unknown>
  group_result: { groups?: SplitGroup[] }
  source: string
  result_status: string
  err_code: string | null
  err_detail: Record<string, unknown> | null
  delivery_ids: unknown
  cost_ms: number | null
  operator: string
  create_time: string
}

export const getSplitTrace = (orderId: number) => get<SplitTrace[]>(`/split/orders/${orderId}/trace`)

// ============ D03.07 发货单 ============

export interface DeliveryBrief {
  id: number
  delivery_bn: string
  order_id: number
  status: string
  sync_status: string
  branch_id: number
  owner_id: number
  shop_id: number
  logi_no: string | null
  is_virtual: number
  source: string
  create_time: string
}

export interface DeliveryDetail {
  delivery: {
    id: number
    delivery_bn: string
    order_id: number
    status: string
    sync_status: string
    sync_msg: string | null
    branch_id: number
    logi_id: number | null
    logi_no: string | null
    is_bind: number
    parent_id: number | null
    is_virtual: number
    hold_flag: number
    owner_id: number
    shop_id: number
    plan_id: number | null
    split_trace_id: number | null
    source: string
    delivery_time: string | null
    finish_time: string | null
    memo: string | null
  }
  allowed_commands: string[]
  items: {
    id: number
    bm_id: number
    bm_number: string | null
    num: number
    settled_num: number
    owner_id: number
    price: number
  }[]
  details: {
    id: number
    delivery_item_id: number
    order_item_id: number
    split_qty: number
    freeze_ref: string | null
  }[]
  packages: {
    id: number
    package_no: string | null
    waybill_no: string | null
    weight: number | null
    volume: number | null
    batch_no: string
  }[]
  logs: {
    id: number
    command: string
    from_status: string
    to_status: string
    operator: string
    reason: string | null
    create_time: string
  }[]
  diffs: {
    id: number
    diff_type: string
    diff_num: number
    liability: string | null
    handle_way: string | null
    handle_status: string
    memo: string | null
  }[]
}

export const listDeliveries = (params: {
  status?: string
  branch_id?: number
  shop_id?: number
  order_id?: number
  keyword?: string
  limit?: number
} = {}) => get<DeliveryBrief[]>('/delivery/list', params)

export const getDeliveryStates = () =>
  get<{
    states: string[]
    commands: string[]
    allowed: Record<string, string[]>
    final_states: string[]
  }>('/delivery/states')

export const getDeliveryDetail = (id: number) => get<DeliveryDetail>(`/delivery/${id}`)

export const deliveryPush = (id: number, reason = '') =>
  post<{ ok: boolean; to_status: string; fail_message: string }>(`/delivery/${id}/push`, { reason })

export const deliveryRecall = (id: number, reason = '') =>
  post<{ ok: boolean; to_status: string; fail_message: string }>(`/delivery/${id}/recall`, { reason })

export const deliveryRecallResult = (id: number, success: boolean, reason = '') =>
  post<{ ok: boolean; to_status: string }>(`/delivery/${id}/recall-result`, { success, reason })

export const deliveryResume = (id: number, reason = '') =>
  post<{ ok: boolean; to_status: string }>(`/delivery/${id}/resume`, { reason })

export const deliveryConfirm = (id: number, reason = '') =>
  post<{ ok: boolean; to_status: string }>(`/delivery/${id}/confirm`, { reason })

export const deliveryCancel = (id: number, reason: string) =>
  post<{ ok: boolean; to_status: string; fail_message: string }>(`/delivery/${id}/cancel`, { reason })

export const deliveryReject = (id: number, reason: string) =>
  post<{ ok: boolean; to_status: string }>(`/delivery/${id}/reject`, { reason })

export const deliveryCallback = (
  id: number,
  batch: {
    batch_no: string
    waybill_no?: string
    weight?: number
    volume?: number
    lines: { bm_id: number; num: number }[]
  }
) => post<{ ok: boolean; to_status: string; detail: Record<string, unknown> }>(
  `/delivery/${id}/callback`,
  batch
)

export const listDeliveryAbnormal = () => get<Record<string, unknown>[]>('/delivery/abnormal/list')
