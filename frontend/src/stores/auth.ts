import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { LoginResult, MeInfo } from '@/api/auth'

/**
 * 认证状态（D10.02）：纯状态容器，不 import api/http（避免与 http 拦截器循环依赖）。
 * 登录/刷新由页面或 http 拦截器调用 api 后写入本 store。
 */
export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('ktoms_token') || '')
  const refreshToken = ref<string>(localStorage.getItem('ktoms_refresh') || '')
  const username = ref<string>(localStorage.getItem('ktoms_username') || '')
  const accountName = ref<string>('')
  const isSuperuser = ref<boolean>(false)
  const permissions = ref<string[]>([])

  const logged = computed(() => !!token.value)

  function setSession(res: LoginResult) {
    token.value = res.access_token
    refreshToken.value = res.refresh_token
    username.value = res.account_name
    accountName.value = res.account_name
    localStorage.setItem('ktoms_token', res.access_token)
    localStorage.setItem('ktoms_refresh', res.refresh_token)
    localStorage.setItem('ktoms_username', res.account_name)
  }

  /** 仅更新 access（refresh 旋转时用） */
  function setTokens(access: string, refresh?: string) {
    token.value = access
    localStorage.setItem('ktoms_token', access)
    if (refresh) {
      refreshToken.value = refresh
      localStorage.setItem('ktoms_refresh', refresh)
    }
  }

  function setMe(me: MeInfo) {
    accountName.value = me.account_name
    isSuperuser.value = me.is_superuser
    permissions.value = me.permissions
  }

  function hasPerm(code: string): boolean {
    return isSuperuser.value || permissions.value.includes(code)
  }

  function logout() {
    token.value = ''
    refreshToken.value = ''
    username.value = ''
    accountName.value = ''
    isSuperuser.value = false
    permissions.value = []
    localStorage.removeItem('ktoms_token')
    localStorage.removeItem('ktoms_refresh')
    localStorage.removeItem('ktoms_username')
  }

  return {
    token, refreshToken, username, accountName, isSuperuser, permissions,
    logged, setSession, setTokens, setMe, hasPerm, logout,
  }
})
