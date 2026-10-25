<script setup lang="ts">
/** 库存余额（五口径）与对账（SRS-D04.02）
 *  可用库存为派生计算值：available = store − freeze − defective − (is_locked ? safe_store : 0)
 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  STOCK_FIELD_LABEL, applyStockAdjust, listReconDiffs, makeStockSnapshot,
  queryStockLedger, rebuildStockCache, runStockRecon,
  type ReconDiff, type StockBalance,
} from '@/api/stock'
import { listBranches, listOwners, type Owner, type Shop } from '@/api/master'

const rows = ref<StockBalance[]>([])
const branches = ref<Shop[]>([])
const owners = ref<Owner[]>([])
const diffs = ref<ReconDiff[]>([])
const loading = ref(false)
const keyword = ref('')
const filterBranch = ref<number | undefined>(undefined)
const filterOwner = ref<number | undefined>(undefined)
const tab = ref<'balance' | 'diff'>('balance')

const DIFF_STATUS_LABEL: Record<number, string> = {
  1: '待处理', 2: '已自动修复', 3: '已人工处理', 4: '误报忽略',
}

const adjustDialog = reactive({
  visible: false,
  form: {
    branch_id: 0, bm_id: 0, owner_id: 0, field: 'store',
    adjust_num: 0, adjust_type: '盘盈', reason: '', operator: '',
  },
})

async function load() {
  loading.value = true
  try {
    rows.value = await queryStockLedger({
      keyword: keyword.value || undefined,
      branch_id: filterBranch.value,
      owner_id: filterOwner.value,
    })
  } finally {
    loading.value = false
  }
}

async function loadDiffs() {
  diffs.value = await listReconDiffs()
}

async function loadRefs() {
  const [b, o] = await Promise.all([listBranches(), listOwners()])
  branches.value = b as unknown as Shop[]
  owners.value = o
}

function openAdjust(row: StockBalance) {
  adjustDialog.form = {
    branch_id: row.branch_id, bm_id: row.bm_id, owner_id: row.owner_id,
    field: 'store', adjust_num: 0, adjust_type: '盘盈', reason: '', operator: '',
  }
  adjustDialog.visible = true
}

async function submitAdjust() {
  await applyStockAdjust({ ...adjustDialog.form })
  ElMessage.success('调整已生效（已记账 + 流水）')
  adjustDialog.visible = false
  load()
}

async function doRecon() {
  const report = await runStockRecon(true)
  ElMessage.success(
    `对账完成：比对 ${report.checked} 行，差异 ${report.diff_count} 条，自动修复 ${report.fixed} 条`,
  )
  loadDiffs()
  load()
}

async function doRebuild() {
  const r = await rebuildStockCache()
  ElMessage.success(`缓存已重建 ${r.rebuilt} 行`)
}

async function doSnapshot() {
  const r = await makeStockSnapshot()
  ElMessage.success(`快照已生成 ${r.created} 条`)
}

onMounted(() => { load(); loadRefs(); loadDiffs() })
</script>

<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>库存余额（五口径）· 可用库存为派生值：store − freeze − defective − 锁定安全库存</span>
          <div>
            <el-input v-model="keyword" placeholder="搜索货号/物料名" size="small"
              style="width:160px;margin-right:8px" clearable @keyup.enter="load" />
            <el-select v-model="filterBranch" placeholder="按仓" size="small"
              style="width:120px;margin-right:8px" clearable @change="load">
              <el-option v-for="b in branches" :key="b.id" :label="b.shop_name" :value="b.id" />
            </el-select>
            <el-select v-model="filterOwner" placeholder="按货主" size="small"
              style="width:120px;margin-right:8px" clearable @change="load">
              <el-option v-for="o in owners" :key="o.id" :label="o.owner_name" :value="o.id" />
            </el-select>
            <el-button size="small" @click="load">查询</el-button>
          </div>
        </div>
      </template>

      <el-tabs v-model="tab">
        <el-tab-pane label="五口径余额" name="balance" />
        <el-tab-pane label="对账差异" name="diff" />
      </el-tabs>

      <el-table v-if="tab === 'balance'" v-loading="loading" :data="rows" stripe>
        <el-table-column prop="branch_id" label="仓ID" width="80" />
        <el-table-column prop="material_bn" label="货号" width="130" />
        <el-table-column prop="material_name" label="物料名称" min-width="140" />
        <el-table-column prop="owner_id" label="货主ID" width="90" />
        <el-table-column label="实际" width="90">
          <template #default="{ row }">{{ row.store }}</template>
        </el-table-column>
        <el-table-column label="锁定" width="90">
          <template #default="{ row }">{{ row.freeze }}</template>
        </el-table-column>
        <el-table-column label="在途" width="90">
          <template #default="{ row }">{{ row.arrive_store }}</template>
        </el-table-column>
        <el-table-column label="次品" width="90">
          <template #default="{ row }">{{ row.defective }}</template>
        </el-table-column>
        <el-table-column label="可用" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.available < 0 ? 'danger' : 'success'">
              {{ row.available }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="安全库存" width="110">
          <template #default="{ row }">
            {{ row.safe_store }}
            <el-tag v-if="row.is_locked === 1" size="small" type="warning" style="margin-left:4px">锁定</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="openAdjust(row)">调整</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div v-else>
        <div style="margin-bottom:10px;display:flex;gap:8px">
          <el-button size="small" type="primary" @click="doRecon">立即对账并修复</el-button>
          <el-button size="small" @click="doRebuild">重建缓存</el-button>
          <el-button size="small" @click="doSnapshot">生成日终快照</el-button>
          <el-button size="small" @click="loadDiffs">刷新差异</el-button>
        </div>
        <el-table :data="diffs" size="small" stripe>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="recon_date" label="对账日期" width="110" />
          <el-table-column label="口径" width="100">
            <template #default="{ row }">{{ STOCK_FIELD_LABEL[row.change_field] ?? row.change_field }}</template>
          </el-table-column>
          <el-table-column prop="oms_num" label="OMS值" width="90" />
          <el-table-column prop="peer_num" label="Redis值" width="90" />
          <el-table-column prop="diff_num" label="差异" width="90" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 2 ? 'success' : row.status === 1 ? 'warning' : 'info'">
                {{ DIFF_STATUS_LABEL[row.status] ?? row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="handle_remark" label="处理说明" min-width="200" />
        </el-table>
      </div>
    </el-card>

    <el-dialog v-model="adjustDialog.visible" title="人工库存调整" width="520px">
      <el-form label-width="100px">
        <el-form-item label="三元键">
          <div style="color:#666;font-size:12px">
            仓 {{ adjustDialog.form.branch_id }} / 物料 {{ adjustDialog.form.bm_id }} / 货主 {{ adjustDialog.form.owner_id }}
          </div>
        </el-form-item>
        <el-form-item label="调整口径">
          <el-select v-model="adjustDialog.form.field" style="width:100%">
            <el-option v-for="(label, val) in STOCK_FIELD_LABEL" :key="val" :label="label" :value="val" />
          </el-select>
        </el-form-item>
        <el-form-item label="调整数量" required>
          <el-input-number v-model="adjustDialog.form.adjust_num" :min="-999999" :max="999999" />
          <div style="color:#999;font-size:12px">盘盈为正，盘亏为负</div>
        </el-form-item>
        <el-form-item label="调整类型">
          <el-select v-model="adjustDialog.form.adjust_type" style="width:100%">
            <el-option v-for="t in ['盘盈', '盘亏', '报损', '退货修正', '系统纠错', '其他']" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="原因" required>
          <el-input v-model="adjustDialog.form.reason" type="textarea" :rows="2" placeholder="必填，用于审计" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adjustDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submitAdjust">提交（生效即记账）</el-button>
      </template>
    </el-dialog>
  </div>
</template>
