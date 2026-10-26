/** 架构契约 API（P1 · 让「模块契约」在界面上可见） */
import { get } from '@/api/http'

/** 契约里的一个接口条目 */
export interface ContractApi {
  name: string
  desc: string
}

/** 允许的跨模块调用 */
export interface AllowedDep {
  module: string
  access: string
  note: string
}

/** 单个模块的契约 */
export interface ModuleContract {
  code: string
  slug: string
  title: string
  duty: string
  services: string[]
  meta: string
  /** 可写表（`schema.table` 全名） */
  write_tables: string[]
  forbidden_write: string[]
  external: { module: string; access: string }[]
  read_apis: ContractApi[]
  write_apis: ContractApi[]
  allowed_deps: AllowedDep[]
  forbidden: string[]
  /** 已知待收口点 */
  todos: string[]
  table_summary: { schema: string; count: string }[]
}

export interface ContractsOverview {
  module_count: number
  enum_count: number
  enum_by_schema: { schema: string; count: number }[]
  enum_by_kind: Record<string, number>
  total_write_tables: number
  /** 契约漂移数（后端实时跑门禁算出，非硬编码）；-1 = 门禁不可用 */
  drift_count: number
  modules: ModuleContract[]
}

export interface EnumItem {
  column: string
  const: string
  kind: 'int' | 'str'
  values: Record<string, string>
}

export interface EnumList {
  total: number
  items: EnumItem[]
}

/** 契约总览（8 个模块 + 枚举统计） */
export const getContracts = () => get<ContractsOverview>('/architecture/contracts')

/** 枚举契约清单（可搜索） */
export const listEnums = (q?: string, limit = 200) =>
  get<EnumList>('/architecture/enums', { q, limit })
