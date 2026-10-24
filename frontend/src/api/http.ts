/**
 * 统一请求封装（对齐后端 app/core/response.py 契约：{code, message, data}）
 * - token 注入（M1 接真实登录后启用）
 * - trace_id 透传（响应头 X-Trace-Id，排障用）
 * - 统一错误提示 + 401 跳登录
 */
import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

const http: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
})

http.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = `Bearer ${auth.token}`
  }
  return config
})

http.interceptors.response.use(
  (resp) => {
    const body = resp.data
    // 统一信封：code=0 成功
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) return body.data
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(new Error(body.message))
    }
    return body
  },
  (error) => {
    const status = error.response?.status
    if (status === 401) {
      useAuthStore().logout()
      router.push('/login')
      ElMessage.warning('登录已过期，请重新登录')
    } else {
      const msg = error.response?.data?.message || error.message || '网络错误'
      ElMessage.error(msg)
    }
    // trace_id 便于与后端日志串联
    const traceId = error.response?.headers?.['x-trace-id']
    if (traceId) console.warn('[trace]', traceId)
    return Promise.reject(error)
  },
)

export function get<T>(url: string, params?: object, config?: AxiosRequestConfig): Promise<T> {
  return http.get(url, { params, ...config }) as Promise<T>
}

export function post<T>(url: string, data?: object, config?: AxiosRequestConfig): Promise<T> {
  return http.post(url, data, config) as Promise<T>
}

export default http
