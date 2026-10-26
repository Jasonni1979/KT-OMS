/** 订单域 API（D03.01 订单接入） */
import { get } from '@/api/http'

export interface OrderOut {
  id: number
  order_bn: string
  platform_order_bn: string
  shop_id: number
  owner_id: number
  createway: string
  order_type: string
  order_status: string
  audit_status: string
  fulfill_status: string
  pay_status: string
  ship_status: string
  list_amount: number
  shop_discount: number
  platform_subsidy: number
  paid_amount: number
  freight: number
  is_cod: number
  promotion_source: string
  buyer_nick: string
  order_time: string | null
  pay_time: string | null
  buyer_memo: string
  warehouse_memo: string
  platform_extra: Record<string, unknown> | null
}

export interface OrderItemOut {
  id: number
  order_id: number
  platform_sku_code: string
  bm_id: number
  bm_number: string
  bm_name: string
  nums: number
  list_price: number
  list_amount: number
  shop_discount: number
  platform_subsidy: number
  paid_amount: number
  parse_status: string
  is_gift: number
}

export interface OrderDetail extends OrderOut {
  items: OrderItemOut[]
}

export const ORDER_STATUS_LABEL: Record<string, string> = {
  processing: '处理中',
  pending: '待处理',
  completed: '已完成',
  cancelled: '已取消',
  closed: '已关闭',
}

export const AUDIT_STATUS_LABEL: Record<string, string> = {
  pending: '待审单',
  passed: '审单通过',
  manual: '待人工审单',
  rejected: '审单驳回',
  shortage: '缺货处理中',
  retrial: '复审中',
}

export const FULFILL_STATUS_LABEL: Record<string, string> = {
  pending: '待履约',
  dispatched: '已分仓',
  delivering: '履约中',
  shipped: '已发货',
  completed: '已完成',
  stalled: '停滞',
}

export const PAY_STATUS_LABEL: Record<string, string> = {
  unpaid: '未支付',
  paid: '已支付',
  refunding: '退款中',
  refunded: '已退款',
}

export const SHIP_STATUS_LABEL: Record<string, string> = {
  unshipped: '未发货',
  shipped: '已发货',
  delivered: '已签收',
}

export interface OrderListParams {
  shop_id?: number
  platform_order_bn?: string
  audit_status?: string
  pay_status?: string
  limit?: number
}

export const listOrders = (params?: OrderListParams) =>
  get<OrderOut[]>('/orders', params as Record<string, unknown>)

export const getOrder = (id: number) => get<OrderDetail>(`/orders/${id}`)

export interface ReceiverOut {
  name_masked: string
  mobile_masked: string
  address_masked: string
  province: string
  city: string
  district: string
  town: string
}

export interface OrderPmtOut {
  id: number
  order_id: number
  item_id: number
  pmt_type: string
  /** 承担方（shop / platform） */
  bearer: string
  amount: number
  platform_pmt_id: string
  pmt_memo: string
}

export const getOrderReceiver = (id: number) =>
  get<ReceiverOut | null>(`/orders/${id}/receiver`)

export const getOrderPmt = (id: number) =>
  get<OrderPmtOut[]>(`/orders/${id}/pmt`)
