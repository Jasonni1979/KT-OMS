<script setup lang="ts">
/** 条码管理（SRS-D04.01 FR-04：一品多码 · 条码全局唯一 · 反查服务） */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  BARCODE_TYPE_LABEL, createBarcode, listBarcodes, listMaterials, lookupBarcode,
  updateBarcode, type Barcode, type Material,
} from '@/api/material'
import { listShops, type Shop } from '@/api/master'

const rows = ref<Barcode[]>([])
const materials = ref<Material[]>([])
const shops = ref<Shop[]>([])
const loading = ref(false)
const keyword = ref('')
const filterType = ref<number | undefined>(undefined)

const dialog = reactive({
  visible: false,
  isEdit: false,
  form: {
    id: 0, barcode: '', bm_id: undefined as number | undefined, barcode_type: 1,
    shop_id: 0, status: 1, version: 0,
  },
})

const lookup = reactive({ code: '', result: null as Barcode | null, loading: false })

async function load() {
  loading.value = true
  try {
    rows.value = await listBarcodes({
      keyword: keyword.value || undefined,
      barcode_type: filterType.value,
    })
  } finally {
    loading.value = false
  }
}

async function loadRefs() {
  const [m, s] = await Promise.all([listMaterials(), listShops()])
  materials.value = m
  shops.value = s
}

function shopName(id: number) {
  return id ? shops.value.find((s) => s.id === id)?.shop_name ?? `#${id}` : '—'
}

function openCreate() {
  dialog.isEdit = false
  dialog.form = {
    id: 0, barcode: '', bm_id: undefined, barcode_type: 1, shop_id: 0, status: 1, version: 0,
  }
  dialog.visible = true
}

function openEdit(row: Barcode) {
  dialog.isEdit = true
  dialog.form = { ...row, bm_id: row.bm_id }
  dialog.visible = true
}

async function submit() {
  if (dialog.isEdit) {
    await updateBarcode(dialog.form.id, {
      barcode_type: dialog.form.barcode_type,
      shop_id: dialog.form.shop_id,
      status: dialog.form.status,
      version: dialog.form.version,
    })
    ElMessage.success('已保存')
  } else {
    await createBarcode({
      barcode: dialog.form.barcode,
      bm_id: dialog.form.bm_id,
      barcode_type: dialog.form.barcode_type,
      shop_id: dialog.form.shop_id,
    })
    ElMessage.success('条码已登记')
  }
  dialog.visible = false
  load()
}

async function doLookup() {
  if (!lookup.code) return
  lookup.loading = true
  try {
    lookup.result = await lookupBarcode(lookup.code)
    ElMessage.success('反查成功')
  } catch {
    lookup.result = null
  } finally {
    lookup.loading = false
  }
}

onMounted(() => { load(); loadRefs() })
</script>

<template>
  <el-card>
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span>条码管理（inv_barcode · 一品多码 · 条码全局唯一）</span>
        <div>
          <el-input v-model="keyword" placeholder="搜索条码/货号/物料名" size="small"
            style="width:180px;margin-right:8px" clearable @keyup.enter="load" />
          <el-select v-model="filterType" placeholder="条码类型" size="small"
            style="width:120px;margin-right:8px" clearable @change="load">
            <el-option v-for="(label, val) in BARCODE_TYPE_LABEL" :key="val" :label="label" :value="val" />
          </el-select>
          <el-button size="small" @click="load">查询</el-button>
          <el-button size="small" type="primary" @click="openCreate">登记条码</el-button>
        </div>
      </div>
    </template>

    <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px"
      title="条码冲突时会拒绝并提示归属物料；店铺码必须关联店铺。" />

    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="barcode" label="条码" min-width="160" />
      <el-table-column prop="material_bn" label="归属货号" width="130" />
      <el-table-column prop="material_name" label="物料名称" min-width="150" />
      <el-table-column label="类型" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.barcode_type === 2 ? 'warning' : 'info'">
            {{ BARCODE_TYPE_LABEL[row.barcode_type] ?? row.barcode_type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="关联店铺" width="120">
        <template #default="{ row }">{{ shopName(row.shop_id) }}</template>
      </el-table-column>
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

    <el-dialog v-model="dialog.visible" :title="dialog.isEdit ? '编辑条码' : '登记条码'" width="520px">
      <el-form label-width="100px">
        <el-form-item label="条码" required>
          <el-input v-model="dialog.form.barcode" :disabled="dialog.isEdit" placeholder="全局唯一" />
        </el-form-item>
        <el-form-item label="归属物料" required>
          <el-select v-model="dialog.form.bm_id" :disabled="dialog.isEdit"
            filterable placeholder="选择基础物料" style="width:100%">
            <el-option v-for="m in materials" :key="m.id"
              :label="`${m.material_bn} ${m.material_name}`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="条码类型">
          <el-select v-model="dialog.form.barcode_type" style="width:100%">
            <el-option v-for="(label, val) in BARCODE_TYPE_LABEL" :key="val" :label="label" :value="val" />
          </el-select>
        </el-form-item>
        <el-form-item label="关联店铺">
          <el-select v-model="dialog.form.shop_id" style="width:100%"
            :disabled="dialog.form.barcode_type !== 2">
            <el-option label="（不关联）" :value="0" />
            <el-option v-for="s in shops" :key="s.id" :label="s.shop_name" :value="s.id" />
          </el-select>
          <div style="color:#999;font-size:12px">店铺码类型必填关联店铺</div>
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
        <el-button type="primary" @click="submit">{{ dialog.isEdit ? '保存' : '登记' }}</el-button>
      </template>
    </el-dialog>

    <!-- 条码反查（FR-04b） -->
    <el-card shadow="never" style="margin-top:16px">
      <template #header><b>条码反查</b><span style="color:#999;font-size:12px;margin-left:8px">供 WMS 回传解析 / 门店扫码 / 售后核销调用</span></template>
      <div style="display:flex;gap:8px;max-width:520px">
        <el-input v-model="lookup.code" placeholder="输入条码值" @keyup.enter="doLookup" />
        <el-button type="primary" :loading="lookup.loading" @click="doLookup">反查</el-button>
      </div>
      <el-descriptions v-if="lookup.result" :column="3" border size="small" style="margin-top:12px">
        <el-descriptions-item label="条码">{{ lookup.result.barcode }}</el-descriptions-item>
        <el-descriptions-item label="归属货号">{{ lookup.result.material_bn }}</el-descriptions-item>
        <el-descriptions-item label="物料名称">{{ lookup.result.material_name }}</el-descriptions-item>
        <el-descriptions-item label="条码类型">
          {{ BARCODE_TYPE_LABEL[lookup.result.barcode_type] }}
        </el-descriptions-item>
        <el-descriptions-item label="基础物料ID">{{ lookup.result.bm_id }}</el-descriptions-item>
        <el-descriptions-item label="货主ID">{{ lookup.result.owner_id }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </el-card>
</template>
