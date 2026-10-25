/** 认证 API（D10.02）：登录/刷新/登出/当前用户 */
import { get, post } from '@/api/http'

export interface LoginResult {
  access_token: string
  refresh_token: string
  session_id: string
  expires_in: number
  must_change_pwd: boolean
  account_id: number
  account_name: string
}
export interface MeInfo {
  account_id: number
  account_name: string
  login_name: string
  is_superuser: boolean
  roles_ver: number
  permissions: string[]
}

export const login = (login_name: string, password: string, device_type = 'pc') =>
  post<LoginResult>('/auth/login', { login_name, password, device_type })

export const refreshToken = (refresh_token: string, device_type = 'pc') =>
  post<LoginResult>('/auth/refresh', { refresh_token, device_type })

export const logout = () => post('/auth/logout')

export const fetchMe = () => get<MeInfo>('/auth/me')
