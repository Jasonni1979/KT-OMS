/**
 * 统一请求封装（对齐后端 app/core/response.py 契约：{code, message, data}）
 * - token 注入（D10.02 真实 JWT）
 * - 401 自动刷新（refresh 旋转，单飞防并发多次刷新）后重放原请求；刷新失败才跳登录
 * - trace_id 透传（响应头 X-Trace-Id，排障用）
 * - 统一错误提示
 */
import axios, { type AxiosInstance, type AxiosRequestConfig, type InternalAxiosRequestConfig } from 'axios'
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

// ---- 401 自动刷新（单飞）----
let refreshing: Promise<string> | null = null

async function doRefresh(): Promise<string> {
  const auth = useAuthStore()
  if (!auth.refreshToken) throw new Error('no refresh token')
  // 用裸 axios（不走本实例拦截器，避免递归）
  const resp = await axios.post('/api/v1/auth/refresh', {
    refresh_token: auth.refreshToken,
    device_type: 'pc',
  })
  const data = resp.data?.data
  if (!data?.access_token) throw new Error('refresh failed')
  auth.setTokens(data.access_token, data.refresh_token)
  return data.access_token
}

function redirectToLogin(msg = '登录已过期，请重新登录') {
  const auth = useAuthStore()
  auth.logout()
  ElMessage.warning(msg)
  const cur = router.currentRoute.value
  if (cur.path !== '/login') {
    router.push({ path: '/login', query: { redirect: cur.fullPath } })
  }
}

http.interceptors.response.use(
  (resp) => {
    const body = resp.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) return body.data
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(new Error(body.message))
    }
    return body
  },
  async (error) => {
    const { config, response } = error as { config?: InternalAxiosRequestConfig; response?: any }
    const status = response?.status
    const errCode = response?.data?.code

    // 401 且非登录/刷新接口本身 → 尝试刷新重放一次
    const isAuthApi = config?.url?.startsWith('/auth/login') || config?.url?.startsWith('/auth/refresh')
    if (status === 401 && config && !isAuthApi && !(config as any)._retried) {
      ;(config as any)._retried = true
      try {
        refreshing = refreshing ?? doRefresh()
        const newToken = await refreshing
        refreshing = null
        config.headers.Authorization = `Bearer ${newToken}`
        return http.request(config as AxiosRequestConfig)
      } catch {
        refreshing = null
        redirectToLogin()
        return Promise.reject(error)
      }
    }

    if (status === 401) {
      redirectToLogin(errCode === 'ROLES_CHANGED' ? '权限已变更，请重新登录' : undefined)
    } else {
      const msg = response?.data?.message || error.message || '网络错误'
      ElMessage.error(msg)
    }
    const traceId = response?.headers?.['x-trace-id']
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
