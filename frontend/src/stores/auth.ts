import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * 认证状态（M0 骨架：本地 mock 登录；M1 接 D10.02 真实账号体系 + JWT）
 */
export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('ktoms_token') || '')
  const username = ref<string>(localStorage.getItem('ktoms_username') || '')

  function login(user: string, tk: string) {
    username.value = user
    token.value = tk
    localStorage.setItem('ktoms_token', tk)
    localStorage.setItem('ktoms_username', user)
  }

  function logout() {
    token.value = ''
    username.value = ''
    localStorage.removeItem('ktoms_token')
    localStorage.removeItem('ktoms_username')
  }

  return { token, username, login, logout }
})
