<script setup lang="ts">
/** 品牌档案（SRS-D04.01 FR-05b：归属货主可空=公共品牌；映射组织树 brand 节点） */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createBrand, listBrands, updateBrand, type Brand } from '@/api/material'
import { listOrgNodes, listOwners, type OrgNode, type Owner } from '@/api/master'

const rows = ref<Brand[]>([])
const owners = ref<Owner[]>([])
const brandNodes = ref<OrgNode[]>([])
const loading = ref(false)
const keyword = ref('')

const dialog = reactive({
  visible: false,
  isEdit: false,
  form: {
    id: 0, brand_name: '', brand_name_en: '', owner_id: 0, org_node_id: 0,
    status: 1, version: 0,
  },
})

async function load() {
  loading.value = true
  try {
    rows.value = await listBrands(keyword.value || undefined)
  } finally {
    loading.value = false
  }
}

async function loadRefs() {
  owners.value = await listOwners()
  // 组织树 brand 节点位于 group 之下（§5.1 层级矩阵）→ 先取根，再取根的子节点
  const roots = await listOrgNodes(0)
  const nodes: OrgNode[] = []
  for (const root of roots.filter((n) => n.node_type === 'group')) {
    nodes.push(...(await listOrgNodes(root.id)))
  }
  brandNodes.value = nodes.filter((n) => n.node_type === 'brand')
}

function ownerName(id: number) {
  if (id === 0) return '公共品牌'
  return owners.value.find((o) => o.id === id)?.owner_name ?? `#${id}`
}

function openCreate() {
  dialog.isEdit = false
  dialog.form = {
    id: 0, brand_name: '', brand_name_en: '', owner_id: 0, org_node_id: 0, status: 1, version: 0,
  }
  dialog.visible = true
}

function openEdit(row: Brand) {
  dialog.isEdit = true
  dialog.form = { ...row }
  dialog.visible = true
}

async function submit() {
  if (dialog.isEdit) {
    await updateBrand(dialog.form.id, {
      brand_name: dialog.form.brand_name,
      brand_name_en: dialog.form.brand_name_en,
      status: dialog.form.status,
      version: dialog.form.version,
    })
    ElMessage.success('已保存')
  } else {
    await createBrand({
      brand_name: dialog.form.brand_name,
      brand_name_en: dialog.form.brand_name_en,
      owner_id: dialog.form.owner_id,
      org_node_id: dialog.form.org_node_id,
    })
    ElMessage.success('品牌已创建')
  }
  dialog.visible = false
  load()
}

onMounted(() => { load(); loadRefs() })
</script>

<template>
  <el-card>
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span>品牌档案（inv_brand · 同货主下品牌名唯一）</span>
        <div>
          <el-input v-model="keyword" placeholder="搜索品牌名/英文名" size="small"
            style="width:180px;margin-right:8px" clearable @keyup.enter="load" />
          <el-button size="small" @click="load">查询</el-button>
          <el-button size="small" type="primary" @click="openCreate">新增品牌</el-button>
        </div>
      </div>
    </template>

    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="brand_name" label="品牌名称" min-width="150" />
      <el-table-column prop="brand_name_en" label="英文名" min-width="140" />
      <el-table-column label="归属货主" width="130">
        <template #default="{ row }">
          <el-tag v-if="row.owner_id === 0" size="small" type="info">公共品牌</el-tag>
          <span v-else>{{ ownerName(row.owner_id) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="org_node_id" label="组织节点" width="100" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 1 ? 'success' : 'info'">
            {{ row.status === 1 ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="80" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link type="primary" @click="openEdit(row)">编辑</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog.visible" :title="dialog.isEdit ? '编辑品牌' : '新增品牌'" width="520px">
      <el-form label-width="110px">
        <el-form-item label="品牌名称" required>
          <el-input v-model="dialog.form.brand_name" />
        </el-form-item>
        <el-form-item label="英文名">
          <el-input v-model="dialog.form.brand_name_en" />
        </el-form-item>
        <el-form-item label="归属货主">
          <el-select v-model="dialog.form.owner_id" :disabled="dialog.isEdit" style="width:100%">
            <el-option label="公共品牌（不归属具体货主）" :value="0" />
            <el-option v-for="o in owners" :key="o.id" :label="o.owner_name" :value="o.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="组织树映射">
          <el-select v-model="dialog.form.org_node_id" style="width:100%">
            <el-option label="（不映射）" :value="0" />
            <el-option v-for="n in brandNodes" :key="n.id" :label="`${n.org_name}（${n.org_code}）`" :value="n.id" />
          </el-select>
          <div style="color:#999;font-size:12px">仅可选择 brand 类型组织节点（FR-05b）</div>
        </el-form-item>
        <el-form-item v-if="dialog.isEdit" label="状态">
          <el-radio-group v-model="dialog.form.status">
            <el-radio :value="1">启用</el-radio>
            <el-radio :value="2">停用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submit">{{ dialog.isEdit ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>
