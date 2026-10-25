<script setup lang="ts">
/** 基础物料档案（SRS-D04.01 FR-02：货号全局唯一、货主归属建档后不可改） */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  MATERIAL_TYPE_LABEL, createMaterial, listAllCategories, listBrands, listMaterials,
  updateMaterial, type Brand, type Material, type MaterialCat,
} from '@/api/material'
import { listOwners, type Owner } from '@/api/master'

const rows = ref<Material[]>([])
const owners = ref<Owner[]>([])
const cats = ref<MaterialCat[]>([])
const brands = ref<Brand[]>([])
const loading = ref(false)
const keyword = ref('')
const filterOwner = ref<number | undefined>(undefined)
const filterCat = ref<number | undefined>(undefined)

const dialog = reactive({
  visible: false,
  isEdit: false,
  form: {
    id: 0, material_bn: '', material_name: '', owner_id: undefined as number | undefined,
    material_spu: '', type: 3, cat_id: 0, brand_id: 0, color: '', size: '',
    same_code_group: '', kingdee_material_code: '', serial_number: 0,
    storage_life_flag: 0, is_ctrl_store: 1, omnichannel: 0, is_o2o_sales: 0,
    tax_rate: 0, tax_name: '', tax_code: '', org_id: 0, remark: '', version: 0,
  },
})

async function load() {
  loading.value = true
  try {
    rows.value = await listMaterials({
      keyword: keyword.value || undefined,
      owner_id: filterOwner.value,
      cat_id: filterCat.value,
    })
  } finally {
    loading.value = false
  }
}

async function loadRefs() {
  const [o, c, b] = await Promise.all([listOwners(), listAllCategories(), listBrands()])
  owners.value = o
  cats.value = c
  brands.value = b
}

function catName(id: number) {
  return cats.value.find((c) => c.id === id)?.cat_name ?? '—'
}
function brandName(id: number) {
  return brands.value.find((b) => b.id === id)?.brand_name ?? '—'
}
function ownerName(id: number) {
  return owners.value.find((o) => o.id === id)?.owner_name ?? `#${id}`
}

function openCreate() {
  dialog.isEdit = false
  dialog.form = {
    id: 0, material_bn: '', material_name: '', owner_id: undefined,
    material_spu: '', type: 3, cat_id: 0, brand_id: 0, color: '', size: '',
    same_code_group: '', kingdee_material_code: '', serial_number: 0,
    storage_life_flag: 0, is_ctrl_store: 1, omnichannel: 0, is_o2o_sales: 0,
    tax_rate: 0, tax_name: '', tax_code: '', org_id: 0, remark: '', version: 0,
  }
  dialog.visible = true
}

function openEdit(row: Material) {
  dialog.isEdit = true
  dialog.form = { ...row }
  dialog.visible = true
}

async function submit() {
  const payload = { ...dialog.form }
  if (dialog.isEdit) {
    // 货号与货主建档后不可改（改货主=资产转移 D04.05）→ 编辑时不提交这两个字段
    const { material_bn, owner_id, ...rest } = payload
    await updateMaterial(payload.id, rest)
  } else {
    await createMaterial(payload)
  }
  ElMessage.success(dialog.isEdit ? '已保存' : '基础物料已创建')
  dialog.visible = false
  load()
}

onMounted(() => { load(); loadRefs() })
</script>

<template>
  <el-card>
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span>基础物料档案（inv_material · 三元键之一：货主 + 物料）</span>
        <div>
          <el-input v-model="keyword" placeholder="搜索货号/名称/SPU" size="small"
            style="width:180px;margin-right:8px" clearable @keyup.enter="load" />
          <el-select v-model="filterOwner" placeholder="按货主" size="small"
            style="width:140px;margin-right:8px" clearable @change="load">
            <el-option v-for="o in owners" :key="o.id" :label="o.owner_name" :value="o.id" />
          </el-select>
          <el-select v-model="filterCat" placeholder="按分类" size="small"
            style="width:130px;margin-right:8px" clearable @change="load">
            <el-option v-for="c in cats" :key="c.id" :label="c.cat_name" :value="c.id" />
          </el-select>
          <el-button size="small" @click="load">查询</el-button>
          <el-button size="small" type="primary" @click="openCreate">新建物料</el-button>
        </div>
      </div>
    </template>

    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="material_bn" label="货号" width="130" />
      <el-table-column prop="material_name" label="物料名称" min-width="150" />
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.type === 5 ? 'warning' : 'info'">
            {{ MATERIAL_TYPE_LABEL[row.type] ?? row.type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="货主" width="120">
        <template #default="{ row }">{{ ownerName(row.owner_id) }}</template>
      </el-table-column>
      <el-table-column label="分类/品牌" width="150">
        <template #default="{ row }">{{ catName(row.cat_id) }} / {{ brandName(row.brand_id) }}</template>
      </el-table-column>
      <el-table-column label="颜色/尺码" width="110">
        <template #default="{ row }">{{ row.color || '-' }} / {{ row.size || '-' }}</template>
      </el-table-column>
      <el-table-column label="开关" width="180">
        <template #default="{ row }">
          <el-tag size="small" :type="row.is_ctrl_store ? 'success' : 'info'">
            {{ row.is_ctrl_store ? '记账' : '不记账' }}
          </el-tag>
          <el-tag v-if="row.serial_number === 1" size="small" type="primary" style="margin-left:4px">SN</el-tag>
          <el-tag v-if="row.storage_life_flag === 1" size="small" type="warning" style="margin-left:4px">效期</el-tag>
          <el-tag v-if="row.is_o2o_sales === 1" size="small" type="info" style="margin-left:4px">O2O</el-tag>
        </template>
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

    <el-dialog v-model="dialog.visible" :title="dialog.isEdit ? '编辑基础物料' : '新建基础物料'"
      width="640px">
      <el-form label-width="110px">
        <el-form-item label="货号" required>
          <el-input v-model="dialog.form.material_bn" :disabled="dialog.isEdit"
            placeholder="全局唯一，建议：品牌缩写+品类+规格" />
          <div v-if="dialog.isEdit" style="color:#999;font-size:12px">货号建档后不可改</div>
        </el-form-item>
        <el-form-item label="物料名称" required>
          <el-input v-model="dialog.form.material_name" />
        </el-form-item>
        <el-form-item label="货主归属" required>
          <el-select v-model="dialog.form.owner_id" :disabled="dialog.isEdit"
            placeholder="必填，建档后不可改" style="width:100%">
            <el-option v-for="o in owners" :key="o.id" :label="`${o.owner_name}（${o.owner_code}）`" :value="o.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="物料属性">
          <el-select v-model="dialog.form.type" style="width:100%">
            <el-option v-for="(label, val) in MATERIAL_TYPE_LABEL" :key="val" :label="label" :value="val" />
          </el-select>
          <div style="color:#999;font-size:12px">虚拟物料不参与实物库存记账（D04.02）</div>
        </el-form-item>
        <el-form-item label="SPU/款号">
          <el-input v-model="dialog.form.material_spu" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="dialog.form.cat_id" style="width:100%">
            <el-option label="（未分类）" :value="0" />
            <el-option v-for="c in cats" :key="c.id" :label="c.cat_name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="品牌">
          <el-select v-model="dialog.form.brand_id" style="width:100%">
            <el-option label="（无品牌）" :value="0" />
            <el-option v-for="b in brands" :key="b.id" :label="b.brand_name" :value="b.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="颜色/尺码">
          <div style="display:flex;gap:8px;width:100%">
            <el-input v-model="dialog.form.color" placeholder="颜色" />
            <el-input v-model="dialog.form.size" placeholder="尺码" />
          </div>
        </el-form-item>
        <el-form-item label="金蝶编码">
          <el-input v-model="dialog.form.kingdee_material_code" placeholder="买断货主建议必填（D08.06 推送）" />
        </el-form-item>
        <el-form-item label="同货号分组">
          <el-input v-model="dialog.form.same_code_group" placeholder="跨货主同货号关联组（选填）" />
        </el-form-item>
        <el-form-item label="开票属性">
          <div style="display:flex;gap:8px;width:100%">
            <el-input-number v-model="dialog.form.tax_rate" :min="0" :max="100" :precision="2" placeholder="税率%" />
            <el-input v-model="dialog.form.tax_name" placeholder="开票名称" />
            <el-input v-model="dialog.form.tax_code" placeholder="分类编码" />
          </div>
        </el-form-item>
        <el-form-item label="管理开关">
          <el-checkbox v-model="dialog.form.is_ctrl_store" :true-value="1" :false-value="0">库存管控(记账)</el-checkbox>
          <el-checkbox v-model="dialog.form.serial_number" :true-value="1" :false-value="0">SN码管理</el-checkbox>
          <el-checkbox v-model="dialog.form.storage_life_flag" :true-value="1" :false-value="0">效期管理</el-checkbox>
          <el-checkbox v-model="dialog.form.is_o2o_sales" :true-value="1" :false-value="0">O2O可售</el-checkbox>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="dialog.form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submit">{{ dialog.isEdit ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>
