"""可过滤实体注册（D10.03 FR-04b：各业务域在模块注册时声明实体与维度列映射）

新增业务实体接入数据权限 = 在此登记一行，零过滤代码。
登记同时写入 org_filterable_entity 表（声明元数据存档与审计，由 seed 脚本同步）。
"""
from app.core.permission import register_filterable
from app.models.abnormal import (
    OrdAbnormal,
    OrdAbnormalTypeDict,
    OrdReasonCodeDict,
    OrdStockout,
)
from app.models.audit import (
    OrdAuditBatchLog,
    OrdAuditGroup,
    OrdAuditPluginPerf,
    OrdAuditReason,
    OrdAuditRule,
    OrdAuditTask,
    OrdAuditWorkLog,
    OrdDispatchRule,
    OrdFulfillPlan,
)
from app.models.branch import FulBranch
from app.models.fulfill import (
    OrdBranchChangeLog,
    OrdBranchDispatchRule,
    OrdDelivery,
    OrdDeliveryDiff,
    OrdDeliveryItem,
    OrdDeliveryItemDetail,
    OrdDeliveryLog,
    OrdDeliveryPackage,
    OrdDispatchPlan,
    OrdRoutingDecisionLog,
    OrdSplitRule,
    OrdSplitTrace,
)
from app.models.gateway import (
    GwApiLog,
    GwOrderBuffer,
    GwPullWatermark,
    GwShopAuth,
)
from app.models.material import InvBarcode, InvMaterial
from app.models.order import (
    OrdOrder,
    OrdOrderFail,
    OrdOrderItem,
    OrdOrderPmt,
    OrdReceiver,
    OrdStatusLog,
)
from app.models.org import OrgOwner
from app.models.shop import GwShop
from app.models.stock import InvIoBill, InvIoBillItem, InvStockLedger

# 货主档案：tenant_id + owner 维（货主维即主键）
register_filterable(OrgOwner, {"tenant_id": OrgOwner.tenant_id, "owner_id": OrgOwner.id})

# 店铺：tenant_id + owner 维 + shop 维（店铺维即主键 gw_shop.id）
register_filterable(GwShop, {
    "tenant_id": GwShop.tenant_id,
    "owner_id": GwShop.owner_id,
    "shop_id": GwShop.id,
})

# 仓库：tenant_id + branch 维（仓库维即主键 ful_branch.id）
# 注：owner_id 允许为 NULL（多货主共用仓），按 owner 维过滤会误杀多货主仓，
#     MVP 阶段仓以 branch 维为访问轴；owner 维过滤在 D04 记账域按三元键实现
register_filterable(FulBranch, {
    "tenant_id": FulBranch.tenant_id,
    "branch_id": FulBranch.id,
})


# 基础物料（SRS-D04.01 FR-02）：tenant_id + owner 维（货主维即 owner_id 列）
# 注：品牌/分类无 owner 维（品牌可公共、分类全局共享），按 tenant 隔离即可
# 销售物料（inv_sales_material）暂不注册 owner 维：未绑定时 owner_id=0（尚未归属任何货主），
#     按 owner 维过滤会让「待绑定清单」（FR-01c）不可见 → 待绑定阶段须按 tenant + shop 维可见
register_filterable(InvMaterial, {
    "tenant_id": InvMaterial.tenant_id,
    "owner_id": InvMaterial.owner_id,
})

# 条码（SRS-D04.01 FR-04）：tenant_id + owner 维（冗余自基础物料）
register_filterable(InvBarcode, {
    "tenant_id": InvBarcode.tenant_id,
    "owner_id": InvBarcode.owner_id,
})

# 库存域（SRS-D04.02/D04.04）：三元键 = 仓 + 物料 + 货主 → owner 维 + branch 维
register_filterable(InvStockLedger, {
    "tenant_id": InvStockLedger.tenant_id,
    "owner_id": InvStockLedger.owner_id,
    "branch_id": InvStockLedger.branch_id,
})
register_filterable(InvIoBill, {
    "tenant_id": InvIoBill.tenant_id,
    "owner_id": InvIoBill.owner_id,
    "branch_id": InvIoBill.branch_id,
})
register_filterable(InvIoBillItem, {
    "tenant_id": InvIoBillItem.tenant_id,
    "owner_id": InvIoBillItem.owner_id,
})

# ============ D02 网关域（D02.03 缓冲池 + 水位 + 授权 + api_log）============
register_filterable(GwOrderBuffer, {
    "tenant_id": GwOrderBuffer.tenant_id,
    "owner_id": GwOrderBuffer.owner_id,
    "shop_id": GwOrderBuffer.shop_id,
})
register_filterable(GwPullWatermark, {
    "tenant_id": GwPullWatermark.tenant_id,
})
register_filterable(GwShopAuth, {
    "tenant_id": GwShopAuth.tenant_id,
    "owner_id": GwShopAuth.owner_id,
    "shop_id": GwShopAuth.shop_id,
})
register_filterable(GwApiLog, {
    "tenant_id": GwApiLog.tenant_id,
})

# ============ D03 订单域（D03.01 订单接入）============
# 注：订单头 owner_id 取「店铺归属货主」（跨货主订单的货主归属在行级 owner_id）
register_filterable(OrdOrder, {
    "tenant_id": OrdOrder.tenant_id,
    "owner_id": OrdOrder.owner_id,
    "shop_id": OrdOrder.shop_id,
})
register_filterable(OrdOrderItem, {
    "tenant_id": OrdOrderItem.tenant_id,
    "owner_id": OrdOrderItem.owner_id,
})
register_filterable(OrdReceiver, {
    "tenant_id": OrdReceiver.tenant_id,
    "owner_id": OrdReceiver.owner_id,
})
register_filterable(OrdOrderPmt, {
    "tenant_id": OrdOrderPmt.tenant_id,
    "owner_id": OrdOrderPmt.owner_id,
})
register_filterable(OrdStatusLog, {
    "tenant_id": OrdStatusLog.tenant_id,
    "owner_id": OrdStatusLog.owner_id,
})
register_filterable(OrdOrderFail, {
    "tenant_id": OrdOrderFail.tenant_id,
    "owner_id": OrdOrderFail.owner_id,
})

# ============ D03 审单域（D03.02 审单引擎 + D03.03 人工审单工作台）============
# 审单规则：tenant + owner 维（规则可按货主隔离）
register_filterable(OrdAuditRule, {
    "tenant_id": OrdAuditRule.tenant_id,
    "owner_id": OrdAuditRule.owner_id,
})
# 结构化原因：tenant + owner + shop 维（工作台按店铺筛）
register_filterable(OrdAuditReason, {
    "tenant_id": OrdAuditReason.tenant_id,
    "owner_id": OrdAuditReason.owner_id,
    "shop_id": OrdAuditReason.shop_id,
})
# 履约方案：tenant + owner + shop 维
register_filterable(OrdFulfillPlan, {
    "tenant_id": OrdFulfillPlan.tenant_id,
    "owner_id": OrdFulfillPlan.owner_id,
    "shop_id": OrdFulfillPlan.shop_id,
})
# 审单任务：tenant + owner + shop 维
register_filterable(OrdAuditTask, {
    "tenant_id": OrdAuditTask.tenant_id,
    "owner_id": OrdAuditTask.owner_id,
    "shop_id": OrdAuditTask.shop_id,
})
# 审核组 / 分派规则：DDL 无 owner_id 列 → 仅 tenant 维
register_filterable(OrdAuditGroup, {
    "tenant_id": OrdAuditGroup.tenant_id,
})
register_filterable(OrdDispatchRule, {
    "tenant_id": OrdDispatchRule.tenant_id,
})
# 插件耗时 / 批次日志：tenant 维（追加型日志无 owner/shop 维）
register_filterable(OrdAuditPluginPerf, {
    "tenant_id": OrdAuditPluginPerf.tenant_id,
})
register_filterable(OrdAuditBatchLog, {
    "tenant_id": OrdAuditBatchLog.tenant_id,
})
register_filterable(OrdAuditWorkLog, {
    "tenant_id": OrdAuditWorkLog.tenant_id,
})

# ============ W6 履约域（D03.06 分仓 / D03.04 拆单 / D03.07 发货单）============

# 分仓方案：tenant + owner + shop 维
register_filterable(OrdDispatchPlan, {
    "tenant_id": OrdDispatchPlan.tenant_id,
    "owner_id": OrdDispatchPlan.owner_id,
    "shop_id": OrdDispatchPlan.shop_id,
})
# 选仓规则：tenant + owner 维
register_filterable(OrdBranchDispatchRule, {
    "tenant_id": OrdBranchDispatchRule.tenant_id,
    "owner_id": OrdBranchDispatchRule.owner_id,
})
# 拆单规则：tenant + owner 维
register_filterable(OrdSplitRule, {
    "tenant_id": OrdSplitRule.tenant_id,
    "owner_id": OrdSplitRule.owner_id,
})
# 发货单：tenant + owner + shop 维
register_filterable(OrdDelivery, {
    "tenant_id": OrdDelivery.tenant_id,
    "owner_id": OrdDelivery.owner_id,
    "shop_id": OrdDelivery.shop_id,
})
# 发货单行 / 差异：tenant + owner 维（无 shop 列）
register_filterable(OrdDeliveryItem, {
    "tenant_id": OrdDeliveryItem.tenant_id,
    "owner_id": OrdDeliveryItem.owner_id,
})
register_filterable(OrdDeliveryDiff, {
    "tenant_id": OrdDeliveryDiff.tenant_id,
    "owner_id": OrdDeliveryDiff.owner_id,
})
# 追加型表（无 owner/shop 列或仅 tenant 维）
register_filterable(OrdBranchChangeLog, {
    "tenant_id": OrdBranchChangeLog.tenant_id,
    "owner_id": OrdBranchChangeLog.owner_id,
    "shop_id": OrdBranchChangeLog.shop_id,
})
register_filterable(OrdRoutingDecisionLog, {
    "tenant_id": OrdRoutingDecisionLog.tenant_id,
    "owner_id": OrdRoutingDecisionLog.owner_id,
    "shop_id": OrdRoutingDecisionLog.shop_id,
})
register_filterable(OrdSplitTrace, {
    "tenant_id": OrdSplitTrace.tenant_id,
    "owner_id": OrdSplitTrace.owner_id,
    "shop_id": OrdSplitTrace.shop_id,
})
register_filterable(OrdDeliveryItemDetail, {
    "tenant_id": OrdDeliveryItemDetail.tenant_id,
})
register_filterable(OrdDeliveryPackage, {
    "tenant_id": OrdDeliveryPackage.tenant_id,
})
register_filterable(OrdDeliveryLog, {
    "tenant_id": OrdDeliveryLog.tenant_id,
})

# ============ 异常单域（D03.09）============
# 异常单：tenant + owner + shop 三维（FR-02f 数据权限四维行级过滤）
register_filterable(OrdAbnormal, {
    "tenant_id": OrdAbnormal.tenant_id,
    "owner_id": OrdAbnormal.owner_id,
    "shop_id": OrdAbnormal.shop_id,
})
# 缺货明细：tenant + owner 维
register_filterable(OrdStockout, {
    "tenant_id": OrdStockout.tenant_id,
    "owner_id": OrdStockout.owner_id,
})
# 异常类型字典：tenant 维（配置类，仅租户隔离）
register_filterable(OrdAbnormalTypeDict, {
    "tenant_id": OrdAbnormalTypeDict.tenant_id,
})
# 审单原因码字典：tenant 维
register_filterable(OrdReasonCodeDict, {
    "tenant_id": OrdReasonCodeDict.tenant_id,
})
