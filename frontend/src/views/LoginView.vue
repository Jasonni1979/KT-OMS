<script setup lang="ts">
/**
 * 登录页（M0 骨架：mock 登录；M1 接 D10.02 账号体系——自建账号+企微扫码，
 * 品牌方门户走手机号+验证码，见 SRS-D10.02）
 */
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { get } from '@/api/http'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)

const form = reactive({ username: '', password: '' })
const rules: FormRules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    // M0：先验证后端连通性（readyz），mock 发 token；M1 换成 POST /auth/login
    await get('/hello/readyz')
    auth.login(form.username, `mock-token-${Date.now()}`)
    ElMessage.success('登录成功（M0 mock，M1 接真实认证）')
    router.push((route.query.redirect as string) || '/')
  } catch {
    ElMessage.error('后端未就绪，请先启动 backend（uv run uvicorn app.main:app --reload）')
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
      <p class="hint">M0 骨架：任意账号密码可登录（校验后端连通性）</p>
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
