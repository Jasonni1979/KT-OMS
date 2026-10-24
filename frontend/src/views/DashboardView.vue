<script setup lang="ts">
/** M0 工作台：展示骨架状态与后端连通性（M2 起替换为 D11.03 履约监控看板） */
import { onMounted, ref } from 'vue'
import { get } from '@/api/http'

const backend = ref<{ status: string; db: string } | null>(null)
const error = ref('')

onMounted(async () => {
  try {
    backend.value = await get<{ status: string; db: string }>('/hello/readyz')
  } catch (e: any) {
    error.value = e?.message || '后端不可达'
  }
})
</script>

<template>
  <div>
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card>
          <template #header>后端状态</template>
          <el-tag v-if="backend" type="success" size="large">✓ {{ backend.status }} / DB {{ backend.db }}</el-tag>
          <el-tag v-else type="danger" size="large">✗ {{ error || '检测中...' }}</el-tag>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card>
          <template #header>M0 里程碑</template>
          <p>M0.1 数据库基建 ✅（373 表）</p>
          <p>M0.2 后端骨架 ✅（本页面经其 API）</p>
          <p>M0.3 前端骨架 ✅（本页面）</p>
          <p>M0.4-0.6 三项 spike 验证 ⏳</p>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card>
          <template #header>技术栈（V2.1）</template>
          <p>FastAPI + SQLAlchemy 2.0 async</p>
          <p>Vue3 + TS + Element Plus</p>
          <p>MySQL8 · Redis7 · RabbitMQ</p>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>
