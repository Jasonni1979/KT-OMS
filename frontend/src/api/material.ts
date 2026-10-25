/** 物料域 API（SRS-D04.01：分类树 / 品牌 / 基础物料） */
import { get, post } from '@/api/http'
import http from '@/api/http'

// ============ 类型 ============
export interface MaterialCat {
  id: number; cat_name: string; parent_id: number; cat_path: string
  cat_level: number; sort_no: number; status: number; version: number; create_time: string
}
export interface Brand {
  id: number; owner_id: number; brand_name: string; brand_name_en: string
  org_node_id: number; status: number; version: number; create_time: string
}
export interface Material {
  id: number; owner_id: number; material_bn: string; material_bn_crc32: number
  material_name: string; material_spu: string; type: number
  cat_id: number; cat_path: string; brand_id: number
  color: string; size: string; same_code_group: string; kingdee_material_code: string
  serial_number: number; storage_life_flag: number; is_ctrl_store: number
  omnichannel: number; is_o2o_sales: number
  tax_rate: number; tax_name: string; tax_code: string; org_id: number
  status: number; source: string; remark: string; version: number; create_time: string
}

// ============ 分类树 ============
export const listCategories = (parentId: number) =>
  get<MaterialCat[]>('/material/categories', { parent_id: parentId })
export const listAllCategories = () => get<MaterialCat[]>('/material/categories/all')
export const createCategory = (data: object) => post<MaterialCat>('/material/categories', data)
export const updateCategory = (id: number, data: object) => http.put(`/material/categories/${id}`, data)
export const moveCategory = (id: number, newParentId: number) =>
  post<MaterialCat>(`/material/categories/${id}/move?new_parent_id=${newParentId}`, {})
export const deleteCategory = (id: number) => http.delete(`/material/categories/${id}`)

// ============ 品牌 ============
export const listBrands = (keyword?: string) =>
  get<Brand[]>('/material/brands', keyword ? { keyword } : undefined)
export const createBrand = (data: object) => post<Brand>('/material/brands', data)
export const updateBrand = (id: number, data: object) => http.put(`/material/brands/${id}`, data)

// ============ 基础物料 ============
export const listMaterials = (params?: {
  keyword?: string; owner_id?: number; cat_id?: number; brand_id?: number
}) => get<Material[]>('/material/materials', params)
export const createMaterial = (data: object) => post<Material>('/material/materials', data)
export const updateMaterial = (id: number, data: object) => http.put(`/material/materials/${id}`, data)

// ============ 枚举字典 ============
export const MATERIAL_TYPE_LABEL: Record<number, string> = {
  1: '成品', 2: '半成品', 3: '普通', 4: '礼盒', 5: '虚拟',
}
export const BARCODE_TYPE_LABEL: Record<number, string> = {
  1: '厂商码', 2: '店铺码', 3: 'WMS码', 9: '其他',
}

// ============ 销售物料 ============
export interface SalesMaterial {
  id: number; owner_id: number; shop_id: number
  sales_material_bn: string; sales_material_name: string; spec_text: string
  sales_material_type: number; bind_status: number; class_id: number
  tax_rate: number; tax_name: string; tax_code: string; org_id: number
  visibled: number; status: number; source: string; version: number; create_time: string
}
export interface BomItem {
  id: number; bm_id: number; material_bn: string; material_name: string
  material_type: number; bind_num: number; rate: number; fixed_price: number; is_virtual: number
}
export interface BomVersion {
  id: number; sm_id: number; version_no: number; status: number
  effective_time: string | null; operator: string; create_time: string; items: BomItem[]
}
export interface BomCandidate {
  bm_id: number; material_bn: string; material_name: string
  owner_id: number; score: number; reason: string
}

// ============ 销售物料接口 ============
export const listSalesMaterials = (params?: {
  keyword?: string; shop_id?: number; bind_status?: number
}) => get<SalesMaterial[]>('/material/sales-materials', params)
export const listUnboundSalesMaterials = (shopId?: number) =>
  get<SalesMaterial[]>('/material/sales-materials/unbound', shopId ? { shop_id: shopId } : undefined)
export const createSalesMaterial = (data: object) => post<SalesMaterial>('/material/sales-materials', data)
export const updateSalesMaterial = (id: number, data: object) =>
  http.put(`/material/sales-materials/${id}`, data)

// ============ BOM 接口 ============
export const getCurrentBom = (smId: number) => get<BomVersion | null>(`/material/sales-materials/${smId}/bom`)
export const getBomHistory = (smId: number) => get<BomVersion[]>(`/material/sales-materials/${smId}/bom/history`)
export const bindBom = (smId: number, items: object[], operator?: string) =>
  post<BomVersion>(`/material/sales-materials/${smId}/bom`, { items, operator: operator || '' })
export const unbindBom = (smId: number) => http.delete(`/material/sales-materials/${smId}/bom`)
export const getBomCandidates = (smId: number, limit = 10) =>
  get<BomCandidate[]>(`/material/sales-materials/${smId}/bom/candidates`, { limit })

export const SALES_MATERIAL_TYPE_LABEL: Record<number, string> = {
  1: '普通', 2: '组合', 3: '赠品', 4: '多选一', 5: '礼盒', 6: '福袋',
}
