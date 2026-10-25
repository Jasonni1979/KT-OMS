/** 档案域 API（D10.01 组织树/货主 + 店铺/仓库最小版） */
import { get, post } from '@/api/http'
import http from '@/api/http'

// ============ 类型 ============
export interface OrgNode {
  id: number; org_code: string; org_name: string; node_type: string
  parent_id: number; cat_path: string; node_level: number; ref_id: number
  sort_no: number; status: number; remark: string; version: number; create_time: string
}
export interface Owner {
  id: number; owner_code: string; owner_name: string; owner_type: string
  org_node_id: number; tax_no: string; contact_name: string
  status: number; remark: string; version: number; create_time: string
}
export interface Shop {
  id: number; shop_bn: string; shop_name: string; owner_id: number
  platform: string; platform_shop_id: string; shop_type: string; business_type: string
  auth_status: string; org_node_id: number; status: string; version: number; create_time: string
}
export interface Branch {
  id: number; branch_bn: string; branch_name: string; owner_id: number | null
  branch_type: string; region_code: string | null; province: string | null
  city: string | null; address: string | null; contact_name: string | null
  is_ctrl: number; countable_flag: number; cutoff_time: string | null
  org_node_id: number | null; status: string; version: number; create_time: string
}
/** 仓 ↔ 可服务货主关系（D10.01 FR-07a） */
export interface BranchOwnerRel {
  id: number; node_id: number; branch_id: number; branch_name: string
  owner_id: number; owner_code: string; owner_name: string; owner_type: string
  owner_status: number; is_primary: number; status: number; create_time: string
}

// ============ 组织树 ============
export const listOrgNodes = (parent_id: number) => get<OrgNode[]>('/master/org-nodes', { parent_id })
export const searchOrgNodes = (keyword: string) => get<OrgNode[]>('/master/org-nodes/search', { keyword })
export const createOrgNode = (data: object) => post<OrgNode>('/master/org-nodes', data)
export const updateOrgNode = (id: number, data: object) => http.put(`/master/org-nodes/${id}`, data)
export const deleteOrgNode = (id: number) => http.delete(`/master/org-nodes/${id}`)

// ============ 货主 ============
export const listOwners = (keyword?: string) => get<Owner[]>('/master/owners', keyword ? { keyword } : undefined)
export const createOwner = (data: object) => post<Owner>('/master/owners', data)
export const updateOwner = (id: number, data: object) => http.put(`/master/owners/${id}`, data)

// ============ 店铺 ============
export const listShops = (keyword?: string) => get<Shop[]>('/master/shops', keyword ? { keyword } : undefined)
export const createShop = (data: object, parentNodeId: number) =>
  post<Shop>(`/master/shops?parent_node_id=${parentNodeId}`, data)
export const updateShop = (id: number, data: object) => http.put(`/master/shops/${id}`, data)

// ============ 仓库 ============
export const listBranches = (keyword?: string) => get<Branch[]>('/master/branches', keyword ? { keyword } : undefined)
export const createBranch = (data: object) => post<Branch>('/master/branches', data)
export const updateBranch = (id: number, data: object) => http.put(`/master/branches/${id}`, data)

// ============ 仓 ↔ 可服务货主 ============
export const listBranchOwners = (branchId: number) =>
  get<BranchOwnerRel[]>(`/master/branches/${branchId}/owners`)
export const bindBranchOwners = (branchId: number, ownerIds: number[], operator?: string) =>
  post<BranchOwnerRel[]>(`/master/branches/${branchId}/owners`, {
    owner_ids: ownerIds, operator: operator || '',
  })
export const unbindBranchOwner = (relId: number) => http.delete(`/master/branch-owner-rels/${relId}`)
export const listOwnerBranches = (ownerId: number) =>
  get<BranchOwnerRel[]>(`/master/owners/${ownerId}/branches`)

// ============ 枚举字典（前端展示） ============
export const NODE_TYPE_LABEL: Record<string, string> = {
  group: '集团', brand: '品牌', owner_co: '货主公司', shop: '店铺',
  warehouse: '仓', dept: '部门', reserved_dealer: '经销商(预留)',
}
export const OWNER_TYPE_LABEL: Record<string, string> = {
  KC_BUYOUT: '凯淳买断', BRAND_CONSIGN: '品牌代销', DEALER_TC: '经销商(P2预留)',
}
export const OWNER_STATUS_LABEL: Record<number, { text: string; type: string }> = {
  1: { text: '合作中', type: 'success' }, 2: { text: '暂停', type: 'warning' }, 3: { text: '终止', type: 'danger' },
}
export const PLATFORM_LABEL: Record<string, string> = {
  taobao: '淘宝/天猫', jd: '京东', pdd: '拼多多', xhs: '小红书',
  vop: '唯品会', douyin: '抖音', wechat: '微信小店', kuaishou: '快手',
}
export const BRANCH_TYPE_LABEL: Record<string, string> = {
  entity: '实体仓', cloud: '云仓', store: '门店仓', bonded: '保税仓', virtual: '虚拟仓', defective: '次品仓',
}
