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
