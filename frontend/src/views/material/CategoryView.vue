<script setup lang="ts">
/** 基础物料分类树（SRS-D04.01 FR-05a：增删改、移动节点、路径维护） */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createCategory, deleteCategory, listAllCategories, moveCategory, updateCategory,
  type MaterialCat,
} from '@/api/material'

const cats = ref<MaterialCat[]>([])
const loading = ref(false)

const dialog = reactive({
  visible: false,
  isEdit: false,
  form: { id: 0, cat_name: '', parent_id: 0, sort_no: 0, status: 1, version: 0 },
})

async function load() {
  loading.value = true
  try {
    cats.value = await listAllCategories()
  } finally {
    loading.value = false
  }
}

function openCreate(parentId = 0) {
  dialog.isEdit = false
  dialog.form = { id: 0, cat_name: '', parent_id: parentId, sort_no: 0, status: 1, version: 0 }
  dialog.visible = true
}

function openEdit(cat: MaterialCat) {
  dialog.isEdit = true
  dialog.form = { ...cat }
  dialog.visible = true
}

async function submit() {
  if (dialog.isEdit) {
    await updateCategory(dialog.form.id, {
      cat_name: dialog.form.cat_name,
      sort_no: dialog.form.sort_no,
      status: dialog.form.status,
      version: dialog.form.version,
    })
    ElMessage.success('已保存')
  } else {
    await createCategory({
      cat_name: dialog.form.cat_name,
      parent_id: dialog.form.parent_id,
      sort_no: dialog.form.sort_no,
    })
    ElMessage.success('分类已创建')
  }
  dialog.visible = false
  load()
}

async function remove(cat: MaterialCat) {
  await ElMessageBox.confirm(
    `确认删除分类「${cat.cat_name}」？有子分类或被物料引用时会被拒绝。`,
    '删除分类',
    { type: 'warning' },
  )
  await deleteCategory(cat.id)
  ElMessage.success('已删除')
  load()
}

async function move(cat: MaterialCat, newParentId: number) {
  await moveCategory(cat.id, newParentId)
  ElMessage.success('已移动（子树路径已级联刷新）')
  load()
}

/** 移动目标选择：可移到根层或任一其他分类 */
async function openMove(cat: MaterialCat) {
  const targets = cats.value.filter((c) => c.id !== cat.id)
  const options = [{ id: 0, cat_name: '（根层）' }, ...targets]
  const { value } = await ElMessageBox.prompt(
    `输入目标分类 ID（可选：${options.map((o) => `${o.id}=${o.cat_name}`).join('，')}）`,
    '移动分类',
    { inputValue: String(cat.parent_id ?? 0), inputPattern: /^\d+$/, inputErrorMessage: '请输入数字 ID' },
  )
  await move(cat, Number(value))
}

onMounted(load)
</script>

<template>
  <el-card>
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span>物料分类树（inv_material_cat · 路径冗余支持按子树查询）</span>
        <div>
          <el-button size="small" @click="load">刷新</el-button>
          <el-button size="small" type="primary" @click="openCreate(0)">新增根分类</el-button>
        </div>
      </div>
    </template>

    <el-table v-loading="loading" :data="cats" stripe size="small">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="cat_name" label="分类名称" min-width="160" />
      <el-table-column prop="parent_id" label="父ID" width="80" />
      <el-table-column prop="cat_level" label="层级" width="70" />
      <el-table-column prop="cat_path" label="路径" width="160" />
      <el-table-column prop="sort_no" label="排序" width="70" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 1 ? 'success' : 'info'">
            {{ row.status === 1 ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link type="primary" @click="openCreate(row.id)">加子类</el-button>
          <el-button size="small" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" link type="warning" @click="openMove(row)">移动</el-button>
          <el-button size="small" link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog.visible" :title="dialog.isEdit ? '编辑分类' : '新增分类'" width="480px">
      <el-form label-width="90px">
        <el-form-item label="上级分类">
          <el-select v-model="dialog.form.parent_id" :disabled="dialog.isEdit" style="width:100%">
            <el-option label="（根层）" :value="0" />
            <el-option v-for="c in cats" :key="c.id" :label="`${c.cat_name}（${c.cat_path}）`" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="分类名称" required>
          <el-input v-model="dialog.form.cat_name" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="dialog.form.sort_no" :min="0" />
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
