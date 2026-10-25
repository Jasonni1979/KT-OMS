/** 库存记账 API（SRS-D04.02） */
import { get, post } from '@/api/http'

export interface StockBalance {
  branch_id: number; bm_id: number; owner_id: number
  store: number; freeze: number; arrive_store: number; defective: number
  safe_store: number; is_locked: number; available: number
  unit_cost: number; inventory_cost: number; status: number
  material_bn: string; material_name: string; branch_name: string
}
export interface StockChangeResult {
  idempotent: boolean
  balances: Record<string, number>
  available: number
  change_log_ids: number[]
}
export interface ReconDiff {
  id: number; owner_id: number; recon_date: string; recon_type: number
  branch_id: number; bm_id: number; change_field: string
  oms_num: number; peer_num: number; diff_num: number
  status: number; handle_remark: string; handler: string; handle_time: string | null
}
export interface ReconReport {
  recon_type: number; checked: number; diff_count: number; fixed: number; diffs: ReconDiff[]
}

export const queryStockLedger = (params?: {
  branch_id?: number; owner_id?: number; brand_id?: number; cat_id?: number; keyword?: string
}) => get<StockBalance[]>('/stock/ledger', params)
export const getStockBalance = (branchId: number, bmId: number, ownerId: number) =>
  get<StockBalance>(`/stock/ledger/${branchId}/${bmId}/${ownerId}`)
export const applyStockChange = (data: object) => post<StockChangeResult>('/stock/ledger/change', data)
export const applyStockAdjust = (data: object) => post<StockChangeResult>('/stock/ledger/adjust', data)
export const runStockRecon = (fix = true) =>
  post<ReconReport>(`/stock/recon/run?fix=${fix}`, {})
export const listReconDiffs = (status?: number) =>
  get<ReconDiff[]>('/stock/recon/diffs', status ? { status } : undefined)
export const handleReconDiff = (id: number, status: number, remark = '', handler = '') =>
  post<ReconDiff>(`/stock/recon/diffs/${id}/handle?status=${status}&remark=${encodeURIComponent(remark)}&handler=${handler}`, {})
export const rebuildStockCache = (branchId?: number, ownerId?: number) =>
  post<{ rebuilt: number }>(`/stock/recon/rebuild-cache?branch_id=${branchId ?? ''}&owner_id=${ownerId ?? ''}`, {})
export const makeStockSnapshot = () => post<{ created: number }>('/stock/snapshot', {})

export const STOCK_FIELD_LABEL: Record<string, string> = {
  store: '实际库存',
  freeze: '锁定库存',
  arrive_store: '在途库存',
  defective: '次品库存',
}

// ============ 出入库单据（D04.04）============
export interface IoBillType {
  type_code: string; type_name: string; direction: number
  effect_template: { field?: string; sign?: number; action?: string }[] | null
  need_wms: number; need_approval: number; settle_rel: number
}
export interface IoBillItem {
  id: number; bill_id: number; bill_bn: string; owner_id: number; bm_id: number
  issued_num: number; returned_num: number; confirmed_num: number; defect_num: number
  batch_no: string; unit_cost: number; amount: number
}
export interface IoBill {
  id: number; owner_id: number; bill_bn: string; bill_type: string; direction: number
  branch_id: number; source_bill_type: string; source_bill_bn: string
  wms_bill_no: string; shop_id: number; status: number; red_flush_of: string
  settle_status: number; settle_bn: string; settle_num: number; settle_money: number
  operator: string; confirm_time: string | null; memo: string; source: string
  version: number; create_time: string; items: IoBillItem[]
}
export interface IoBillTrace {
  bill: IoBill
  change_logs: {
    id: number; bm_id: number; change_field: string; change_num: number
    before_balance: number; after_balance: number; action: string
    bill_bn: string; create_time: string
  }[]
  ledger: Record<string, number>
}

export const listBillTypes = () => get<IoBillType[]>('/stock/bill/types')
export const listBills = (params?: {
  bill_type?: string; branch_id?: number; status?: number; source_bill_bn?: string
}) => get<IoBill[]>('/stock/bills', params)
export const getBill = (id: number) => get<IoBill>(`/stock/bills/${id}`)
export const createBill = (data: object) => post<IoBill>('/stock/bills', data)
export const pushBillToWms = (id: number, wmsBillNo = '') =>
  post<IoBill>(`/stock/bills/${id}/push-wms?wms_bill_no=${wmsBillNo}`, {})
export const callbackBill = (id: number, data: object) => post<IoBill>(`/stock/bills/${id}/callback`, data)
export const confirmBill = (id: number) => post<IoBill>(`/stock/bills/${id}/confirm`, {})
export const redFlushBill = (id: number, reason: string) =>
  post<IoBill>(`/stock/bills/${id}/red-flush`, { reason })
export const settleBill = (id: number, data: object) => post<IoBill>(`/stock/bills/${id}/settle`, data)
export const traceBill = (id: number) => get<IoBillTrace>(`/stock/bills/${id}/trace`)

export const BILL_STATUS_LABEL: Record<number, string> = {
  1: '草稿', 2: '已下发WMS', 3: '部分回传', 4: '全部回传',
  5: '已确认', 6: '已红冲', 7: '已关闭',
}
export const SETTLE_STATUS_LABEL: Record<number, string> = {
  0: '无需结算', 1: '未结算', 2: '部分结算', 3: '已结算', 4: '结算锁定',
}
