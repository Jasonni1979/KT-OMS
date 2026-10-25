<script setup lang="ts">
/** 货主档案（D10.01 FR-03：类型创建后不可改；终止态只读） */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  OWNER_STATUS_LABEL, OWNER_TYPE_LABEL, createOwner, listOrgNodes,
  listOwners, searchOrgNodes, updateOwner, type Owner, type OrgNode,
} from '@/api/master'

const rows = ref<Owner[]>([])
const loading = ref(false)
const keyword = ref('')
const ownerCoNodes = ref<OrgNode[]>([])

const dialog = reactive({
  visible: false,
  isEdit: false,
  form: {
    id: 0, owner_code: '', owner_name: '', owner_type: 'BRAND_CONSIGN',
    org_node_id: 0, tax_no: '', contact_name: '', remark: '', version: 0,
  },
})

async function load() {
  loading.value = true
  try {
    rows.value = await listOwners(keyword.value || undefined)
  } finally {
    loading.value = false
  }
}

async function loadOwnerCoNodes() {
  const found = await searchOrgNodes('KC_TRADE_CO')
  ownerCoNodes.value = found
  // 补充：遍历各 group/brand 下的 owner_co 子节点（简化版：搜索接口已够用，全量树遍历后续迭代）
}

function openCreate() {
  dialog.isEdit = false
  dialog.form = {
    id: 0, owner_code: '', owner_name: '', owner_type: 'BRAND_CONSIGN',
    org_node_id: ownerCoNodes.value[0]?.id ?? 0, tax_no: '', contact_name: '', remark: '', version: 0,
  }
  dialog.visible = true
}

function openEdit(row: Owner & { version: number }) {
  dialog.isEdit = true
  dialog.form = {
    id: row.id, owner_code: row.owner_code, owner_name: row.owner_name,
    owner_type: row.owner_type, org_node_id: row.org_node_id,
    tax_no: row.tax_no, contact_name: row.contact_name, remark: row.remark, version: row.version,
  }
  dialog.visible = true
}

async function submit() {
  if (dialog.isEdit) {
    const { id, owner_code, owner_type, org_node_id, ...rest } = dialog.form
    await updateOwner(id, rest)
    ElMessage.success('已更新')
  } else {
    await createOwner(dialog.form)
    ElMessage.success('货主已创建（类型创建后不可改）')
  }
  dialog.visible = false
  load()
}

onMounted(() => { load(); loadOwnerCoNodes() })
</script>

<template>
  <el-card>
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span>货主档案（三元记账 owner_id 权威源）</span>
        <div>
          <el-input v-model="keyword" placeholder="搜索名称/编码" size="small" style="width:200px;margin-right:8px"
            clearable @keyup.enter="load" />
          <el-button size="small" @click="load">查询</el-button>
          <el-button size="small" type="primary" @click="openCreate">新建货主</el-button>
        </div>
      </div>
    </template>

    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="owner_code" label="货主编码" width="140" />
      <el-table-column prop="owner_name" label="名称" min-width="160" />
      <el-table-column label="类型" width="130">
        <template #default="{ row }">
          <el-tag size="small" :type="row.owner_type === 'KC_BUYOUT' ? 'primary' : 'success'">
            {{ OWNER_TYPE_LABEL[row.owner_type] ?? row.owner_type }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="tax_no" label="统一社会信用代码" width="190" />
      <el-table-column prop="contact_name" label="联系人" width="100" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="(OWNER_STATUS_LABEL[row.status]?.type as any) ?? 'info'">
            {{ OWNER_STATUS_LABEL[row.status]?.text ?? row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="create_time" label="创建时间" width="170" />
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.status !== 3" size="small" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-tag v-else size="small" type="info">只读</el-tag>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog.visible" :title="dialog.isEdit ? '编辑货主' : '新建货主'" width="520px">
      <el-form label-width="130px">
        <el-form-item label="货主编码" required>
          <el-input v-model="dialog.form.owner_code" :disabled="dialog.isEdit" placeholder="全局唯一，创建后不可改" />
        </el-form-item>
        <el-form-item label="名称" required><el-input v-model="dialog.form.owner_name" /></el-form-item>
        <el-form-item label="货主类型" required>
          <el-select v-model="dialog.form.owner_type" :disabled="dialog.isEdit" style="width:100%">
            <el-option label="凯淳买断" value="KC_BUYOUT" />
            <el-option label="品牌代销" value="BRAND_CONSIGN" />
            <el-option label="经销商贸易公司（P2 预留）" value="DEALER_TC" disabled />
          </el-select>
          <div v-if="!dialog.isEdit" style="color:#e6a23c;font-size:12px">类型创建后不可改（改类型=资产转移走新货主）</div>
        </el-form-item>
        <el-form-item label="归属货主公司节点" required>
          <el-select v-model="dialog.form.org_node_id" :disabled="dialog.isEdit" style="width:100%">
            <el-option v-for="n in ownerCoNodes" :key="n.id" :label="`${n.org_name}（${n.org_code}）`" :value="n.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="统一社会信用代码"><el-input v-model="dialog.form.tax_no" maxlength="18" /></el-form-item>
        <el-form-item label="联系人"><el-input v-model="dialog.form.contact_name" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="dialog.form.remark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submit">{{ dialog.isEdit ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>
