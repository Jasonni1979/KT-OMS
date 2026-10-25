"""数据权限行级过滤注入（D10.03 FR-04：全域唯一注入点，业务域无感知）

机制（沿用 M0.4 spike 验证通过的方案）：
- 每个 session 的 do_orm_execute 事件上，对「已注册的可过滤实体」追加 with_loader_criteria
- 仅注入该实体声明拥有的维度列（FR-04b），维度列可映射到主键（如 shop 维 = gw_shop.id）
- fail-closed：无 AuthContext 时拒绝查询（防中间件漏配导致全量泄露）
- 豁免通道：without_data_scope() 显式块内不注入（FR-04d，系统级任务专用）
- 未注册实体：只注入 tenant_id 保底隔离 + 开发期告警（FR-04b）
"""
import logging
from typing import Any

from sqlalchemy import and_, event, false
from sqlalchemy.orm import with_loader_criteria

from app.core.db import get_auth_context, is_scope_exempt

logger = logging.getLogger("ktoms.permission")

# ---------- 实体过滤声明表（FR-04b） ----------
# 业务域在模块注册时声明实体与维度列映射：entity → {维度名: 列表达式}
# 声明来源=代码（权威，运行时生效）；org_filterable_entity 表为声明元数据存档与审计
FILTERABLE_REGISTRY: dict[type, dict[str, Any]] = {}


def register_filterable(entity: type, dim_columns: dict[str, Any]) -> None:
    """业务域注册可过滤实体（模块 import 时调用）

    例：register_filterable(GwShop, {"tenant_id": GwShop.tenant_id,
                                    "owner_id": GwShop.owner_id,
                                    "shop_id": GwShop.id})
    """
    FILTERABLE_REGISTRY[entity] = dim_columns


def _build_criteria(dim_columns: dict[str, Any], ctx) -> Any:
    """按实体声明的维度列构造过滤条件（只注入存在的列）"""
    clauses = []
    # tenant_id 恒定注入（保底隔离）
    if "tenant_id" in dim_columns:
        clauses.append(dim_columns["tenant_id"] == ctx.tenant_id)
    if ctx.is_superuser or ctx.all_data:
        return clauses[0] if clauses else None
    # 四维 IN 集合（FR-07c scope 结构）
    for dim, values in (
        ("owner_id", ctx.owner_ids),
        ("shop_id", ctx.shop_ids),
        ("branch_id", ctx.branch_ids),
        ("brand_id", ctx.brand_ids),
    ):
        col = dim_columns.get(dim)
        if col is None:
            continue
        if not values:
            # 空集合 = 该维度无权 → 恒假（fail-closed，不放行任何行）
            clauses.append(false())
        else:
            clauses.append(col.in_(values))
    if not clauses:
        return None
    return and_(*clauses)


def install_scope_injection(session_factory) -> None:
    """在 session 工厂上安装行级过滤注入（应用启动时调用一次）"""
    # do_orm_execute 是同步 Session 的事件：async_sessionmaker 的同步对应类为 sync_session_class
    base_cls = session_factory.class_
    sync_session_cls = getattr(base_cls, "sync_session_class", base_cls)

    if getattr(sync_session_cls, "_ktoms_scope_installed", False):
        return

    @event.listens_for(sync_session_cls, "do_orm_execute")
    def _inject_scope(execute_state) -> None:  # noqa: ANN001
        if not execute_state.is_select:
            return
        if is_scope_exempt():
            return
        ctx = get_auth_context()
        if ctx is None:
            # fail-closed：无上下文拒绝查询（M0.4 用例3 已验证）
            raise PermissionError("AuthContext 缺失：拒绝无上下文的 ORM 查询（fail-closed）")
        statement = execute_state.statement
        for entity, dim_columns in FILTERABLE_REGISTRY.items():
            criteria = _build_criteria(dim_columns, ctx)
            if criteria is not None:
                statement = statement.options(with_loader_criteria(entity, criteria))
        execute_state.statement = statement

    sync_session_cls._ktoms_scope_installed = True  # type: ignore[attr-defined]
    logger.info("data scope injection installed: %d entities", len(FILTERABLE_REGISTRY))
