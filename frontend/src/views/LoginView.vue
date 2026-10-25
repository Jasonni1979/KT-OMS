<script setup lang="ts">
/**
 * 登录页（D10.02：内部 staff 账密通道已接通；企微扫码/门户验证码通道 MVP 后置）
 */
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { fetchMe, login } from '@/api/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)

const form = reactive({ username: 'admin', password: '' })
const rules: FormRules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    const res = await login(form.username, form.password)
    auth.setSession(res)
    // 拉取用户信息+权限点（动态菜单/按钮控制依据）
    const me = await fetchMe()
    auth.setMe(me)
    if (res.must_change_pwd) {
      ElMessage.warning('初始密码请尽快修改（改密功能 M1a 后续提供）')
    }
    ElMessage.success(`欢迎，${me.account_name}`)
    router.push((route.query.redirect as string) || '/')
  } catch {
    // 错误提示已由 http 拦截器统一弹出（账号或密码错误/锁定/禁用）
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card">
      <div class="brand">
        <h1>KT-OMS</h1>
        <p>凯淳自研订单管理系统</p>
      </div>
      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="onSubmit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="账号" :prefix-icon="'User'" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" show-password :prefix-icon="'Lock'" />
        </el-form-item>
        <el-button type="primary" class="submit" :loading="loading" @click="onSubmit">登 录</el-button>
      </el-form>
      <p class="hint">开发环境账号 admin（初始密码见 seed_auth.py）· 企微扫码通道 M4+</p>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #103d6e 0%, #185fa5 60%, #2a70b5 100%);
}
.login-card { width: 400px; padding: 12px 8px; }
.brand { text-align: center; margin-bottom: 24px; }
.brand h1 { color: var(--kt-primary); margin: 0 0 4px; letter-spacing: 2px; }
.brand p { color: #888; margin: 0; font-size: 13px; }
.submit { width: 100%; }
.hint { text-align: center; color: #aaa; font-size: 12px; margin-top: 16px; }
</style>
