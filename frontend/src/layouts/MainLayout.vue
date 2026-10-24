<script setup lang="ts">
/**
 * 主布局（M0 骨架）：侧边菜单 + 顶栏 + 内容区
 * M1 起：菜单按 D10.03 功能权限动态生成（meta.perm 匹配权限点）
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const menus = computed(() =>
  (router.options.routes.find((r) => r.path === '/')?.children ?? []).filter((r) => r.meta?.title),
)

function onLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px">
      <div class="logo">KT-OMS</div>
      <el-menu :default-active="route.path" router background-color="#0f2b46" text-color="#c8d6e5" active-text-color="#fff">
        <el-menu-item v-for="m in menus" :key="m.path" :index="'/' + m.path">
          <el-icon><component :is="m.meta?.icon ?? 'Menu'" /></el-icon>
          <span>{{ m.meta?.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span class="title">{{ route.meta?.title ?? '凯淳自研 OMS' }}</span>
        <el-dropdown>
          <span class="user">{{ auth.username || 'dev' }} ▾</span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="onLogout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main><router-view /></el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.layout { height: 100vh; }
.el-aside { background: #0f2b46; }
.logo { color: #fff; font-weight: 700; letter-spacing: 2px; text-align: center; padding: 18px 0; font-size: 18px; }
.el-menu { border-right: none; }
.header { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #eee; }
.header .title { font-size: 15px; color: #333; }
.user { cursor: pointer; color: var(--kt-primary); }
</style>
