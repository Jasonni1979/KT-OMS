"""可过滤实体注册（D10.03 FR-04b：各业务域在模块注册时声明实体与维度列映射）

新增业务实体接入数据权限 = 在此登记一行，零过滤代码。
登记同时写入 org_filterable_entity 表（声明元数据存档与审计，由 seed 脚本同步）。
"""
from app.core.permission import register_filterable
from app.models.branch import FulBranch
from app.models.org import OrgOwner
from app.models.shop import GwShop

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
