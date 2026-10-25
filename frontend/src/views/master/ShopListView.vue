<script setup lang="ts">
/** 店铺档案（最小版：平台授权归 W4 D02.06；建档联动组织树 shop 节点） */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  PLATFORM_LABEL, createShop, listOwners, listShops,
  searchOrgNodes, type OrgNode, type Owner, type Shop,
} from '@/api/master'

const rows = ref<Shop[]>([])
const owners = ref<Owner[]>([])
const parentNodes = ref<OrgNode[]>([])  // 可挂店铺的 brand/owner_co 节点
const loading = ref(false)
const keyword = ref('')

const dialog = reactive({
  visible: false,
  form: {
    shop_name: '', owner_id: 0, platform: 'taobao', platform_shop_id: '',
    shop_type: 'flagship', business_type: 'direct_sale', parent_node_id: 0,
  },
})

async function load() {
  loading.value = true
  try {
    rows.value = await listShops(keyword.value || undefined)
  } finally {
    loading.value = false
  }
}

async function loadRefs() {
  owners.value = (await listOwners()).filter((o) => o.status === 1)
  // 可挂载节点：默认货主公司 + 搜索到的品牌节点
  const coNodes = await searchOrgNodes('凯淳')
  parentNodes.value = coNodes.filter((n) => ['brand', 'owner_co'].includes(n.node_type))
}

function openCreate() {
  dialog.form = {
    shop_name: '', owner_id: owners.value[0]?.id ?? 0, platform: 'taobao',
    platform_shop_id: '', shop_type: 'flagship', business_type: 'direct_sale',
    parent_node_id: parentNodes.value[0]?.id ?? 0,
  }
  dialog.visible = true
}

async function submit() {
  const { parent_node_id, ...data } = dialog.form
  await createShop(data, parent_node_id)
  ElMessage.success('店铺已创建（组织树节点自动联动）')
  dialog.visible = false
  load()
}

function ownerName(id: number) {
  return owners.value.find((o) => o.id === id)?.owner_name ?? `#${id}`
}

onMounted(() => { load(); loadRefs() })
</script>

<template>
  <el-card>
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span>店铺档案（gw_shop · 平台授权 W4 接入）</span>
        <div>
          <el-input v-model="keyword" placeholder="搜索名称/编码" size="small" style="width:200px;margin-right:8px"
            clearable @keyup.enter="load" />
          <el-button size="small" @click="load">查询</el-button>
          <el-button size="small" type="primary" @click="openCreate">新建店铺</el-button>
        </div>
      </div>
    </template>

    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="shop_bn" label="店铺编码" width="110" />
      <el-table-column prop="shop_name" label="店铺名称" min-width="150" />
      <el-table-column label="平台" width="110">
        <template #default="{ row }">{{ PLATFORM_LABEL[row.platform] ?? row.platform }}</template>
      </el-table-column>
      <el-table-column prop="platform_shop_id" label="平台店铺ID" width="130" />
      <el-table-column label="货主" width="140">
        <template #default="{ row }">{{ ownerName(row.owner_id) }}</template>
      </el-table-column>
      <el-table-column label="授权状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.auth_status === 'normal' ? 'success' : 'info'">
            {{ { pending: '待授权', normal: '正常', expired: '过期', disabled: '停用' }[row.auth_status as string] ?? row.auth_status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="档案状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'enabled' ? 'success' : 'info'">
            {{ row.status === 'enabled' ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="create_time" label="创建时间" width="170" />
    </el-table>

    <el-dialog v-model="dialog.visible" title="新建店铺" width="520px">
      <el-form label-width="110px">
        <el-form-item label="店铺名称" required><el-input v-model="dialog.form.shop_name" /></el-form-item>
        <el-form-item label="平台" required>
          <el-select v-model="dialog.form.platform" style="width:100%">
            <el-option v-for="(label, val) in PLATFORM_LABEL" :key="val" :label="label" :value="val"
              :disabled="val !== 'taobao'" />
          </el-select>
          <div style="color:#999;font-size:12px">MVP 首发天猫/淘宝，其余平台 M4+（DEP-01 资质）</div>
        </el-form-item>
        <el-form-item label="平台店铺ID"><el-input v-model="dialog.form.platform_shop_id" placeholder="sellerId（仿真环境可留空）" /></el-form-item>
        <el-form-item label="货主" required>
          <el-select v-model="dialog.form.owner_id" style="width:100%">
            <el-option v-for="o in owners" :key="o.id" :label="`${o.owner_name}（${o.owner_code}）`" :value="o.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="挂载组织节点" required>
          <el-select v-model="dialog.form.parent_node_id" style="width:100%">
            <el-option v-for="n in parentNodes" :key="n.id"
              :label="`${n.org_name}（${n.node_type === 'brand' ? '品牌' : '货主公司'}）`" :value="n.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="店铺类型">
          <el-select v-model="dialog.form.shop_type" style="width:100%">
            <el-option label="旗舰店" value="flagship" />
            <el-option label="直营" value="direct" />
            <el-option label="加盟" value="franchise" />
            <el-option label="门店O2O" value="store" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submit">创建</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>
