<script setup lang="ts">
/** 仓库档案（最小版：WMS 绑定/路由属性归 D09.01 后续；建档联动组织树 warehouse 节点直属根） */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  BRANCH_TYPE_LABEL, bindBranchOwners, createBranch, listBranches, listBranchOwners,
  listOwners, unbindBranchOwner, updateBranch, type Branch, type BranchOwnerRel, type Owner,
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

// 仓 ↔ 可服务货主配置抽屉（D10.01 FR-07a）
const relDrawer = reactive({
  visible: false,
  branch: null as Branch | null,
  rels: [] as BranchOwnerRel[],
  selected: [] as number[],
  loading: false,
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

// ---------- 可服务货主配置 ----------

async function openOwnerConfig(row: Branch) {
  relDrawer.branch = row
  relDrawer.visible = true
  relDrawer.loading = true
  try {
    relDrawer.rels = await listBranchOwners(row.id)
    relDrawer.selected = relDrawer.rels.filter((r) => r.status === 1).map((r) => r.owner_id)
  } finally {
    relDrawer.loading = false
  }
}

async function saveOwnerConfig() {
  const branch = relDrawer.branch
  if (!branch) return
  relDrawer.loading = true
  try {
    const current = relDrawer.rels.filter((r) => r.status === 1)
    const toBind = relDrawer.selected.filter((id) => !current.some((r) => r.owner_id === id))
    const toUnbind = current.filter((r) => !relDrawer.selected.includes(r.owner_id))
    if (toBind.length) await bindBranchOwners(branch.id, toBind)
    for (const r of toUnbind) await unbindBranchOwner(r.id)
    ElMessage.success(
      toBind.length || toUnbind.length
        ? `已保存（新增 ${toBind.length} 个，解绑 ${toUnbind.length} 个）`
        : '无变更',
    )
    relDrawer.rels = await listBranchOwners(branch.id)
    relDrawer.selected = relDrawer.rels.filter((r) => r.status === 1).map((r) => r.owner_id)
    load()
  } finally {
    relDrawer.loading = false
  }
}

async function removeRel(rel: BranchOwnerRel) {
  await ElMessageBox.confirm(
    `确认解绑货主「${rel.owner_name}」？该仓将不能再为该货主开立三元记账行。`,
    '解绑可服务货主',
    { type: 'warning' },
  )
  await unbindBranchOwner(rel.id)
  ElMessage.success('已解绑')
  relDrawer.rels = await listBranchOwners(relDrawer.branch!.id)
  relDrawer.selected = relDrawer.rels.filter((r) => r.status === 1).map((r) => r.owner_id)
}

/** 该仓已启用的可服务货主摘要 */
function relSummary(row: Branch) {
  if (row.owner_id !== null) return ownerName(row.owner_id)
  return '—'
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
      <el-table-column label="可服务货主" min-width="150">
        <template #default="{ row }">
          <el-tag v-if="row.owner_id !== null" size="small" type="success">
            {{ relSummary(row) }}（归属）
          </el-tag>
          <span v-else style="color:#999;font-size:12px">点击「配置货主」设置</span>
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
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link type="primary" @click="openOwnerConfig(row)">配置货主</el-button>
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

    <!-- 仓 ↔ 可服务货主（D10.01 FR-07a：三元记账前提） -->
    <el-drawer v-model="relDrawer.visible" title="配置可服务货主" size="520px">
      <div v-if="relDrawer.branch">
        <el-descriptions :column="1" border size="small" style="margin-bottom:16px">
          <el-descriptions-item label="仓库">
            {{ relDrawer.branch.branch_name }}（{{ relDrawer.branch.branch_bn }}）
          </el-descriptions-item>
          <el-descriptions-item label="归属">
            <el-tag v-if="relDrawer.branch.owner_id === null" size="small" type="warning">多货主共用仓</el-tag>
            <span v-else>{{ ownerName(relDrawer.branch.owner_id) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="库存管控">
            <el-tag size="small" :type="relDrawer.branch.is_ctrl ? 'success' : 'info'">
              {{ relDrawer.branch.is_ctrl ? '管控库存' : '不管控' }}
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <el-alert
          v-if="relDrawer.branch.owner_id !== null"
          type="info" :closable="false" show-icon style="margin-bottom:12px"
          title="单一归属仓只能服务其归属货主" />
        <el-alert
          v-else-if="!relDrawer.branch.is_ctrl"
          type="error" :closable="false" show-icon style="margin-bottom:12px"
          title="多货主仓必须管控库存（is_ctrl=1）才能配置可服务货主" />

        <el-form label-width="90px">
          <el-form-item label="可服务货主">
            <el-select
              v-model="relDrawer.selected" multiple filterable
              placeholder="选择该仓可服务的货主（可多选）" style="width:100%"
              :disabled="relDrawer.branch.owner_id !== null || !relDrawer.branch.is_ctrl">
              <el-option
                v-for="o in owners" :key="o.id"
                :label="`${o.owner_name}（${o.owner_code}）`" :value="o.id" />
            </el-select>
          </el-form-item>
        </el-form>

        <el-divider content-position="left">已配置关系</el-divider>
        <el-table :data="relDrawer.rels" size="small" border v-loading="relDrawer.loading">
          <el-table-column prop="owner_name" label="货主" min-width="120" />
          <el-table-column prop="owner_code" label="编码" width="120" />
          <el-table-column label="主关联" width="80">
            <template #default="{ row }">
              <el-tag v-if="row.is_primary === 1" size="small" type="primary">主</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 1 ? 'success' : 'info'">
                {{ row.status === 1 ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-button
                v-if="row.status === 1" size="small" link type="danger" @click="removeRel(row)">
                解绑
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="relDrawer.visible = false">关闭</el-button>
        <el-button type="primary" :loading="relDrawer.loading" @click="saveOwnerConfig">保存</el-button>
      </template>
    </el-drawer>
  </el-card>
</template>
