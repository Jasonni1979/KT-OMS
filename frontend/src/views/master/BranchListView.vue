<script setup lang="ts">
/** 仓库档案（最小版：WMS 绑定/路由属性归 D09.01 后续；建档联动组织树 warehouse 节点直属根） */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  BRANCH_TYPE_LABEL, createBranch, listBranches, listOwners,
  updateBranch, type Branch, type Owner,
} from '@/api/master'

const rows = ref<Branch[]>([])
const owners = ref<Owner[]>([])
const loading = ref(false)
const keyword = ref('')

const dialog = reactive({
  visible: false,
  form: {
    branch_name: '', owner_id: null as number | null, branch_type: 'entity',
    region_code: '', province: '', city: '', address: '', contact_name: '',
    is_ctrl: 1, countable_flag: 1, cutoff_time: '',
  },
})

async function load() {
  loading.value = true
  try {
    rows.value = await listBranches(keyword.value || undefined)
  } finally {
    loading.value = false
  }
}

async function loadOwners() {
  owners.value = (await listOwners()).filter((o) => o.status === 1)
}

function openCreate() {
  dialog.form = {
    branch_name: '', owner_id: null, branch_type: 'entity', region_code: '',
    province: '', city: '', address: '', contact_name: '', is_ctrl: 1, countable_flag: 1, cutoff_time: '',
  }
  dialog.visible = true
}

async function submit() {
  await createBranch({ ...dialog.form, owner_id: dialog.form.owner_id || null, cutoff_time: dialog.form.cutoff_time || null })
  ElMessage.success('仓库已创建（组织树节点自动联动，直属集团根）')
  dialog.visible = false
  load()
}

async function toggleStatus(row: Branch) {
  const next = row.status === 'enabled' ? 'disabled' : 'enabled'
  await updateBranch(row.id, { status: next, version: row.version })
  ElMessage.success(next === 'enabled' ? '已启用' : '已停用')
  load()
}

function ownerName(id: number | null) {
  if (id === null) return '多货主共用'
  return owners.value.find((o) => o.id === id)?.owner_name ?? `#${id}`
}

onMounted(() => { load(); loadOwners() })
</script>

<template>
  <el-card>
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span>仓库档案（ful_branch · branch_id 三元键事实源）</span>
        <div>
          <el-input v-model="keyword" placeholder="搜索名称/编码" size="small" style="width:200px;margin-right:8px"
            clearable @keyup.enter="load" />
          <el-button size="small" @click="load">查询</el-button>
          <el-button size="small" type="primary" @click="openCreate">新建仓库</el-button>
        </div>
      </div>
    </template>

    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="branch_bn" label="仓库编码" width="110" />
      <el-table-column prop="branch_name" label="仓库名称" min-width="140" />
      <el-table-column label="类型" width="100">
        <template #default="{ row }">{{ BRANCH_TYPE_LABEL[row.branch_type] ?? row.branch_type }}</template>
      </el-table-column>
      <el-table-column label="归属货主" width="130">
        <template #default="{ row }">
          <el-tag v-if="row.owner_id === null" size="small" type="warning">多货主共用</el-tag>
          <span v-else>{{ ownerName(row.owner_id) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="region_code" label="区域" width="80" />
      <el-table-column label="管控/计可售" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="row.is_ctrl ? 'success' : 'info'">{{ row.is_ctrl ? '管控' : '不管控' }}</el-tag>
          <el-tag size="small" style="margin-left:4px" :type="row.countable_flag ? 'primary' : 'info'">
            {{ row.countable_flag ? '计可售' : '不计' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="cutoff_time" label="截单" width="80" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'enabled' ? 'success' : 'info'">
            {{ row.status === 'enabled' ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link :type="row.status === 'enabled' ? 'warning' : 'success'" @click="toggleStatus(row)">
            {{ row.status === 'enabled' ? '停用' : '启用' }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog.visible" title="新建仓库" width="560px">
      <el-form label-width="100px">
        <el-form-item label="仓库名称" required><el-input v-model="dialog.form.branch_name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="dialog.form.branch_type" style="width:100%">
            <el-option v-for="(label, val) in BRANCH_TYPE_LABEL" :key="val" :label="label" :value="val" />
          </el-select>
        </el-form-item>
        <el-form-item label="归属货主">
          <el-select v-model="dialog.form.owner_id" clearable placeholder="留空=多货主共用仓" style="width:100%">
            <el-option v-for="o in owners" :key="o.id" :label="`${o.owner_name}（${o.owner_code}）`" :value="o.id" />
          </el-select>
          <div style="color:#999;font-size:12px">多货主共用仓必须管控库存（三元记账前提）</div>
        </el-form-item>
        <el-form-item label="区域编码"><el-input v-model="dialog.form.region_code" placeholder="如 EAST（分仓路由用）" /></el-form-item>
        <el-form-item label="省/市">
          <div style="display:flex;gap:8px;width:100%">
            <el-input v-model="dialog.form.province" placeholder="省" />
            <el-input v-model="dialog.form.city" placeholder="市" />
          </div>
        </el-form-item>
        <el-form-item label="详细地址"><el-input v-model="dialog.form.address" /></el-form-item>
        <el-form-item label="联系人"><el-input v-model="dialog.form.contact_name" /></el-form-item>
        <el-form-item label="截单时间">
          <el-time-select v-model="dialog.form.cutoff_time" start="08:00" step="00:30" end="23:30" placeholder="HH:mm" style="width:100%" />
        </el-form-item>
        <el-form-item label="库存属性">
          <el-checkbox v-model="dialog.form.is_ctrl" :true-value="1" :false-value="0">管控库存</el-checkbox>
          <el-checkbox v-model="dialog.form.countable_flag" :true-value="1" :false-value="0">计可售</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submit">创建</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>
