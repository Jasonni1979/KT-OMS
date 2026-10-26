/** 履约监控看板 API（SRS-D11.03 最小可用版 · W8-3） */
import { get } from '@/api/http'

export interface MonitorCard {
  key: string
  title: string
  value: number
  total: number
  unit: string
  level: 'ok' | 'warning' | 'danger'
  hint?: string
}

export interface PullWatermarkItem {
  shop_id: number
  channel: string
  last_download_time: string
  lag_seconds: number
  lag_alert_threshold_sec: number
  poll_interval_sec: number
  over_threshold: boolean
}

export interface MonitorOverview {
  generated_at: string
  cards: MonitorCard[]
  pull_watermark: {
    total_shops: number
    lagged_shops: number
    items: PullWatermarkItem[]
  }
  audit_backlog: {
    pending: number
    overdue: number
    age_buckets: Record<string, number>
    by_status: Record<string, number>
  }
  writeback_failures: {
    platform_pending: number
    platform_dead: number
    wms_pending: number
    wms_dead: number
    total_pending: number
    by_err_level: Record<string, number>
    by_err_class: Record<string, number>
  }
  abnormal_realtime: {
    open_total: number
    overdue: number
    by_type: Record<string, number>
    by_category: Record<string, number>
    age_buckets: Record<string, number>
  }
  caliber_note: string
}

export const getMonitorOverview = () => get<MonitorOverview>('/monitor/overview')

export const getPullWatermark = () =>
  get<MonitorOverview['pull_watermark']>('/monitor/pull-watermark')

export const getAuditBacklog = () =>
  get<MonitorOverview['audit_backlog']>('/monitor/audit-backlog')

export const getWritebackFailures = () =>
  get<MonitorOverview['writeback_failures']>('/monitor/writeback-failures')

export const getAbnormalRealtime = () =>
  get<MonitorOverview['abnormal_realtime']>('/monitor/abnormal-realtime')
