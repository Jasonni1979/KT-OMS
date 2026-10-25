<script setup lang="ts">
/** 组织架构树（D10.01 FR-02e：懒加载子树/搜索/新增/停用/删除） */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  NODE_TYPE_LABEL, createOrgNode, deleteOrgNode, listOrgNodes,
  searchOrgNodes, updateOrgNode, type OrgNode,
} from '@/api/master'

interface TreeNode { id: number; label: string; isLeaf: boolean; raw: OrgNode; children?: TreeNode[] }

const treeRef = ref()
const loading = ref(false)
const searchKeyword = ref('')
const searchResults = ref<OrgNode[]>([])

const dialog = reactive({ visible: false, form: { org_code: '', org_name: '', node_type: 'brand', parent_id: 0, remark: '' } })
const parentLabel = ref('')

// 允许新建的节点类型（shop/warehouse 由店铺/仓库建档联动生成，不手工建）
const creatableTypes = ['brand', 'owner_co', 'dept']

function toTreeNode(n: OrgNode): TreeNode {
  return {
    id: n.id,
    label: `${n.org_name}（${NODE_TYPE_LABEL[n.node_type] ?? n.node_type}）`,
    isLeaf: ['shop', 'warehouse', 'reserved_dealer'].includes(n.node_type),
    raw: n,
  }
}

async function loadChildren(node: any, resolve: (data: TreeNode[]) => void) {
  const parentId = node.level === 0 ? 0 : node.data.id
  const children = await listOrgNodes(parentId)
  resolve(children.map(toTreeNode))
}

async function onSearch() {
  if (!searchKeyword.value.trim()) { searchResults.value = []; return }
  searchResults.value = await searchOrgNodes(searchKeyword.value.trim())
}

function openCreate(node?: TreeNode) {
  dialog.form = { org_code: '', org_name: '', node_type: 'brand', parent_id: node?.raw.id ?? 0, remark: '' }
  parentLabel.value = node ? node.raw.org_name : '（根）'
  dialog.visible = true
}

async function submitCreate() {
  await createOrgNode(dialog.form)
  ElMessage.success('节点已创建')
  dialog.visible = false
  refreshTree()
}

async function onDeactivate(node: TreeNode) {
  await ElMessageBox.confirm(`确认停用「${node.raw.org_name}」？停用后子树在授权选择器不可见`, '停用节点')
  await updateOrgNode(node.raw.id, { status: 2, version: node.raw.version })
  ElMessage.success('已停用')
  refreshTree()
}

async function onDelete(node: TreeNode) {
  await ElMessageBox.confirm(`确认删除「${node.raw.org_name}」？仅停用且无关联的节点可删`, '删除节点', { type: 'warning' })
  await deleteOrgNode(node.raw.id)
  ElMessage.success('已删除')
  refreshTree()
}

function refreshTree() {
  // 重新挂载树组件触发根层重载
  loading.value = true
  treeRef.value?.store?.setData([])
  setTimeout(() => { loading.value = false }, 100)
  key.value++
}

const key = ref(0)
onMounted(() => { /* lazy load 自动触发 */ })
</script>

<template>
  <el-card>
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span>组织架构（一棵树 · D10.01）</span>
        <div>
          <el-input v-model="searchKeyword" placeholder="搜索名称/编码" size="small" style="width:200px;margin-right:8px"
            clearable @keyup.enter="onSearch" @clear="searchResults = []" />
          <el-button size="small" @click="onSearch">搜索</el-button>
          <el-button size="small" type="primary" @click="openCreate()">新增节点</el-button>
        </div>
      </div>
    </template>

    <el-alert v-if="searchResults.length" type="info" :closable="false" style="margin-bottom:12px">
      <div v-for="n in searchResults" :key="n.id" style="line-height:1.9">
        {{ n.org_name }}（{{ NODE_TYPE_LABEL[n.node_type] }}）· 编码 {{ n.org_code }} · 路径 {{ n.cat_path }} ·
        <el-tag size="small" :type="n.status === 1 ? 'success' : 'info'">{{ n.status === 1 ? '启用' : '停用' }}</el-tag>
      </div>
    </el-alert>

    <el-tree
      :key="key"
      ref="treeRef"
      v-loading="loading"
      lazy
      :load="loadChildren"
      node-key="id"
      :expand-on-click-node="false"
      default-expand-all
    >
      <template #default="{ data }">
        <div style="display:flex;align-items:center;gap:8px;width:100%">
          <span>{{ data.label }}</span>
          <el-tag size="small" :type="data.raw.status === 1 ? 'success' : 'info'">
            {{ data.raw.status === 1 ? '启用' : '停用' }}
          </el-tag>
          <span style="color:#999;font-size:12px">{{ data.raw.org_code }}</span>
          <span style="margin-left:auto;display:flex;gap:4px" @click.stop>
            <el-button v-if="creatableTypes.includes(data.raw.node_type) || ['group', 'brand'].includes(data.raw.node_type)"
              size="small" link type="primary" @click="openCreate(data)">加子节点</el-button>
            <el-button v-if="data.raw.status === 1 && data.raw.node_type !== 'group'" size="small" link type="warning"
              @click="onDeactivate(data)">停用</el-button>
            <el-button v-if="data.raw.status === 2" size="small" link type="danger" @click="onDelete(data)">删除</el-button>
          </span>
        </div>
      </template>
    </el-tree>

    <el-dialog v-model="dialog.visible" title="新增组织节点" width="480px">
      <el-form label-width="90px">
        <el-form-item label="父节点"><el-input :model-value="parentLabel" disabled /></el-form-item>
        <el-form-item label="编码" required><el-input v-model="dialog.form.org_code" placeholder="全局唯一，创建后不可改" /></el-form-item>
        <el-form-item label="名称" required><el-input v-model="dialog.form.org_name" /></el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="dialog.form.node_type">
            <el-option v-for="t in creatableTypes" :key="t" :label="NODE_TYPE_LABEL[t]" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="dialog.form.remark" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>
