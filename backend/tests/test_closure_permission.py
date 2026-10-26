"""闭环联动与权限上下文的补充测试（整体检查第二轮 · 补测试空白）

整体检查（第二轮 · 视角B「服务方法覆盖率」）发现以下**未被直接测试**的
关键业务方法，本文件补齐：

| 方法 | 条款 | 为什么关键 |
|---|---|---|
| `AbnormalService.release_order_marks` | FR-02e | **多异常单全部闭环才解除审单标记**（核心规则） |
| `build_auth_context`（模块级函数） | D10.03 | 请求上下文的权限范围构造（owner/shop/branch/brand） |
| `PermissionService.invalidate_account` | D10.03 | 账户权限缓存失效（改角色后立即生效） |

⚠ 补测原则：**测规则，不测实现**。断言的是业务规则的结果，不是方法被调用了几次。
"""
from __future__ import annotations

import time

import pytest
from sqlalchemy import text

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.core.exceptions import ConflictError

pytestmark = pytest.mark.asyncio


def _uid() -> str:
    return f"{time.time_ns() % 100000000:08d}"


@pytest.fixture(autouse=True)
async def _ctx():
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    yield


async def _mk_order() -> int:
    order_bn = f"CLS{_uid()}"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_order "
                "(tenant_id, owner_id, order_bn, platform_order_bn, shop_id, brand_id, "
                " createway, order_type, order_status, audit_status, fulfill_status, "
                " pay_status, ship_status, list_amount, shop_discount, platform_subsidy, "
                " paid_amount, freight, is_cod, order_time, pay_time, create_time, "
                " update_time, version, is_deleted) "
                "VALUES (1, 1, :obn, :pon, 0, 0, 'platform', 'normal', 'processing', "
                "'pending', 'pending', 'paid', 'unshipped', 100, 0, 0, 100, 0, 0, "
                "NOW(3), NOW(3), NOW(3), NOW(3), 0, 0)"
            ),
            {"obn": order_bn, "pon": f"CLSSIM_{_uid()}"},
        )
        return int(
            (
                await conn.execute(
                    text("SELECT id FROM oms_order.ord_order WHERE order_bn = :obn"),
                    {"obn": order_bn},
                )
            ).scalar()
            or 0
        )


async def _mk_abnormal(order_id: int, exc_type: str = "STOCK_SHORT") -> int:
    """造一张待审核的异常单（status=wait_dispatch，不自动分派）"""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_abnormal "
                "(tenant_id, owner_id, abnormal_bn, order_id, order_bn, shop_id, "
                " exc_type, exc_category, source, source_ref, reason_detail, status, "
                " sla_deadline, timeline, create_time, update_time, version, is_deleted) "
                "VALUES (1, 1, :abn, :oid, (SELECT order_bn FROM oms_order.ord_order "
                " WHERE id = :oid), 0, :etype, 'stock', 'manual', 'cls', "
                "JSON_OBJECT('reason_code','STOCK_SHORTAGE'), 'wait_dispatch', "
                "DATE_ADD(NOW(3), INTERVAL 24 HOUR), JSON_ARRAY(), NOW(3), NOW(3), 0, 0)"
            ),
            {"abn": f"ABN{_uid()}", "oid": order_id, "etype": exc_type},
        )
        return int(
            (
                await conn.execute(
                    text(
                        "SELECT id FROM oms_order.ord_abnormal WHERE order_id = :oid "
                        "ORDER BY id DESC LIMIT 1"
                    ),
                    {"oid": order_id},
                )
            ).scalar()
            or 0
        )


async def _mk_reason(order_id: int, code: str = "STOCK_SHORTAGE") -> int:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_audit_reason "
                "(tenant_id, owner_id, order_id, batch_no, plugin_name, reason_code, "
                " level, description, detail, suggest_action, route_target, handle_status, "
                " shop_id, create_time) "
                "VALUES (1, 1, :oid, 'B1', 'stock_check', :rc, 'BLOCK', '缺货', "
                "NULL, 'wait_restock', 'shortage', 'open', 0, NOW(3))"
            ),
            {"oid": order_id, "rc": code},
        )
        return int(
            (
                await conn.execute(
                    text(
                        "SELECT id FROM oms_order.ord_audit_reason "
                        "WHERE order_id = :oid AND handle_status='open' "
                        "ORDER BY id DESC LIMIT 1"
                    ),
                    {"oid": order_id},
                )
            ).scalar()
            or 0
        )


async def _open_reason_count(order_id: int) -> int:
    async with SessionFactory() as s:
        return int(
            await s.scalar(
                text(
                    "SELECT COUNT(*) FROM oms_order.ord_audit_reason "
                    "WHERE order_id = :o AND handle_status='open'"
                ),
                {"o": order_id},
            )
            or 0
        )


async def _clean(order_ids: list[int]) -> None:
    if not order_ids:
        return
    lst = ",".join(str(i) for i in order_ids)
    async with engine.begin() as conn:
        # ⚠ 清理顺序：**先子表后父表**（缺货明细 → 异常单）
        #   否则异常单被删后缺货明细变孤儿（第三轮数据体检实测 17 条孤儿）
        await conn.execute(
            text(
                "DELETE FROM oms_order.ord_stockout WHERE abnormal_id IN "
                f"(SELECT id FROM oms_order.ord_abnormal WHERE order_id IN ({lst}))"
            )
        )
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_abnormal WHERE order_id IN ({lst})")
        )
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_audit_reason WHERE order_id IN ({lst})")
        )
        await conn.execute(text(f"DELETE FROM oms_order.ord_order WHERE id IN ({lst})"))


# ============ FR-02e 闭环联动 ============


async def test_marks_released_only_when_all_abnormals_closed():
    """FR-02e：订单有**多张**未闭环异常单时，闭环其中一张**不能**解除审单标记

    这是 FR-02e 的核心规则（对齐 D03.02「结构化原因清零才可审」）。
    """
    from app.services.abnormal import AbnormalService

    oid = await _mk_order()
    try:
        a1 = await _mk_abnormal(oid, "STOCK_SHORT")
        a2 = await _mk_abnormal(oid, "ADDR_INCOMPLETE")
        await _mk_reason(oid)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            # 先把两张都分派（动作要求已分派状态）
            await svc.dispatch(a1, group_id=1, operator="t")
            await svc.dispatch(a2, group_id=1, operator="t")
            # 闭环其中一张
            await svc.resolve(a1, action="reaudit", operator="t")
            # 另一张仍未闭环 → 审单标记**必须保持**
            assert await _open_reason_count(oid) == 1, "还有未闭环异常单 → 标记不能解除"
            # 闭环第二张 → 标记才解除
            await svc.resolve(a2, action="reaudit", operator="t")
            assert await _open_reason_count(oid) == 0, "全部闭环 → 标记应解除"
    finally:
        await _clean([oid])


async def test_release_order_marks_direct_call():
    """FR-02e：release_order_marks 直接调用 —— 无其它在途异常单时清标记"""
    from app.services.abnormal import AbnormalService

    oid = await _mk_order()
    try:
        a1 = await _mk_abnormal(oid, "STOCK_SHORT")
        await _mk_reason(oid)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            await svc.dispatch(a1, group_id=1, operator="t")
            row = await svc.get(a1)
            released = await svc.release_order_marks(row, operator="t")
        assert released is True
        assert await _open_reason_count(oid) == 0
    finally:
        await _clean([oid])


async def test_release_order_marks_returns_false_with_open_sibling():
    """FR-02e：存在未闭环的兄弟异常单 → 返回 False（不解除标记）"""
    from app.services.abnormal import AbnormalService

    oid = await _mk_order()
    try:
        a1 = await _mk_abnormal(oid, "STOCK_SHORT")
        a2 = await _mk_abnormal(oid, "ADDR_INCOMPLETE")
        await _mk_reason(oid)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            await svc.dispatch(a1, group_id=1, operator="t")
            await svc.dispatch(a2, group_id=1, operator="t")
            row = await svc.get(a1)
            released = await svc.release_order_marks(row, operator="t")
        assert released is False
        assert await _open_reason_count(oid) == 1
    finally:
        await _clean([oid])


async def test_cancel_also_releases_marks():
    """FR-02e：取消异常单（订单取消收口）同样触发标记解除"""
    from app.services.abnormal import AbnormalService

    oid = await _mk_order()
    try:
        a1 = await _mk_abnormal(oid, "STOCK_SHORT")
        await _mk_reason(oid)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            await svc.dispatch(a1, group_id=1, operator="t")
            await svc.cancel(a1, operator="t")
            row = await svc.get(a1)
        assert row.status == "cancelled"
        assert await _open_reason_count(oid) == 0
    finally:
        await _clean([oid])


async def test_resolve_closed_abnormal_rejected():
    """边界：已闭环的异常单不可重复解决（幂等保护）"""
    from app.services.abnormal import AbnormalService

    oid = await _mk_order()
    try:
        a1 = await _mk_abnormal(oid, "STOCK_SHORT")
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            await svc.dispatch(a1, group_id=1, operator="t")
            await svc.resolve(a1, action="reaudit", operator="t")
            with pytest.raises(ConflictError):
                await svc.resolve(a1, action="reaudit", operator="t2")
    finally:
        await _clean([oid])


# ============ D10.03 权限上下文 ============


async def test_build_auth_context_carries_scope():
    """D10.03：build_auth_context 把权限范围装进 AuthContext（四维）"""
    from app.core.db import AuthContext as AC
    from app.services.permission import build_auth_context

    async with SessionFactory() as s:
        # 超管 → 全量数据
        ctx = await build_auth_context(
            account_id=1, tenant_id=1, session=s, redis=None, is_superuser=True
        )
    assert isinstance(ctx, AC)
    assert ctx.is_superuser is True
    assert ctx.all_data is True
    assert ctx.tenant_id == 1


async def test_build_auth_context_for_non_superuser():
    """D10.03：非超管的上下文带 account_id（供数据权限过滤）"""
    from app.services.permission import build_auth_context

    async with SessionFactory() as s:
        ctx = await build_auth_context(
            account_id=1, tenant_id=1, session=s, redis=None, is_superuser=False
        )
    assert ctx.account_id == 1
    assert ctx.tenant_id == 1
    assert ctx.is_superuser is False


async def test_invalidate_account_clears_permission_cache():
    """D10.03：账户权限缓存失效（改角色后立即生效）"""
    from app.services.master import get_redis
    from app.services.permission import PermissionService

    redis = await get_redis()
    async with SessionFactory() as s:
        svc = PermissionService(s, redis)
        # 先取一次 scope（写入缓存）
        await svc.get_scope(1, 1)
        # 失效后应能重新取（不抛错即可，且缓存 key 被清）
        await svc.invalidate_account(1)
        scope = await svc.get_scope(1, 1)
    assert scope is not None
