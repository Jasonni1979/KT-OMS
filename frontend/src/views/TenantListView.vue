<script setup lang="ts">
/** 租户列表（M0 骨架演示：跨 schema 读 oms_org.org_tenant，验证前后端全链路） */
import { onMounted, ref } from 'vue'
import { get } from '@/api/http'

interface Tenant { id: number; tenant_code: string; tenant_name: string; tenant_type: string; status: number }

const rows = ref<Tenant[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const data = await get<{ total: number; items: Tenant[] }>('/hello/tenants')
    rows.value = data.items
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <el-card>
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span>租户（oms_org.org_tenant · 跨 schema 读取演示）</span>
        <el-button size="small" @click="load">刷新</el-button>
      </div>
    </template>
    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="id" label="ID" width="80" />
      <el-table-column prop="tenant_code" label="租户编码" width="160" />
      <el-table-column prop="tenant_name" label="名称" />
      <el-table-column prop="tenant_type" label="类型" width="120" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 1 ? 'success' : 'info'">{{ row.status === 1 ? '启用' : '停用' }}</el-tag>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>
