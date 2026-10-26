"""数据一致性体检（跨域数据体检 · 常驻门禁）

用**真实库数据**检查跨域引用的完整性 —— 静态检查（类型/覆盖率）看不出这类问题，
只有真数据体检才能发现。

体检项（每条都是「跨域引用完整性」）：
1.  缺货明细 → 异常单（引用不能悬空）
2.  缺货明细 → 应急批次（batch_id 引用）
3.  异常单 → 类型字典（类型不能悬空）
4.  异常单已解决 → 审单原因应已清零（标记不能泄漏）
5.  异常单未闭环 → 审单原因应有 open 记录（原因不能丢失）
6.  订单行 → 基础物料
7.  发货单 → 订单
8.  退款单已退款 → 订单 pay_status 应已联动
9.  售后单在途 → 订单应有「售后中」标记
10. 异常单 → 订单

用法：
    cd backend && .venv/bin/python -m app.scripts.data_consistency_check
    # CI 门禁里作为独立 Job（退出码非 0 = 有不一致）
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys

#: (体检项名, SQL)
CHECKS: list[tuple[str, str]] = [
    (
        "缺货明细指向不存在的异常单",
        "SELECT COUNT(*) FROM oms_order.ord_stockout s "
        "WHERE s.is_deleted=0 AND NOT EXISTS ("
        "  SELECT 1 FROM oms_order.ord_abnormal a "
        "  WHERE a.id=s.abnormal_id AND a.is_deleted=0)",
    ),
    (
        "缺货明细指向不存在的应急批次",
        "SELECT COUNT(*) FROM oms_order.ord_stockout s "
        "WHERE s.is_deleted=0 AND s.batch_id>0 AND NOT EXISTS ("
        "  SELECT 1 FROM oms_order.ord_oversold_batch b WHERE b.id=s.batch_id)",
    ),
    (
        "异常单类型不在字典（悬空类型）",
        "SELECT COUNT(*) FROM oms_order.ord_abnormal a "
        "WHERE a.is_deleted=0 AND NOT EXISTS ("
        "  SELECT 1 FROM oms_order.ord_abnormal_type_dict d "
        "  WHERE d.type_code=a.exc_type AND d.is_deleted=0)",
    ),
    (
        "异常单指向不存在的订单",
        "SELECT COUNT(*) FROM oms_order.ord_abnormal a "
        "WHERE a.is_deleted=0 AND a.order_id>0 AND NOT EXISTS ("
        "  SELECT 1 FROM oms_order.ord_order o "
        "  WHERE o.id=a.order_id AND o.is_deleted=0)",
    ),
    (
        "异常单已解决但审单原因仍 open（标记泄漏）",
        "SELECT COUNT(*) FROM oms_order.ord_abnormal a "
        "JOIN oms_order.ord_audit_reason r "
        "  ON r.order_id=a.order_id AND r.handle_status='open' "
        "WHERE a.is_deleted=0 AND a.status IN ('resolved','cancelled')",
    ),
    (
        "异常单未闭环但无 open 审单原因（原因丢失）",
        "SELECT COUNT(*) FROM oms_order.ord_abnormal a "
        "WHERE a.is_deleted=0 AND a.status NOT IN ('resolved','cancelled') "
        "  AND NOT EXISTS ("
        "    SELECT 1 FROM oms_order.ord_audit_reason r "
        "    WHERE r.order_id=a.order_id AND r.handle_status='open')",
    ),
    (
        "订单行指向不存在的物料",
        "SELECT COUNT(*) FROM oms_order.ord_order_item i "
        "WHERE i.is_deleted=0 AND i.bm_id>0 AND NOT EXISTS ("
        "  SELECT 1 FROM oms_stock.inv_material m "
        "  WHERE m.id=i.bm_id AND m.is_deleted=0)",
    ),
    (
        "发货单指向不存在的订单",
        "SELECT COUNT(*) FROM oms_order.ord_delivery d "
        "WHERE d.is_deleted=0 AND d.order_id>0 AND NOT EXISTS ("
        "  SELECT 1 FROM oms_order.ord_order o "
        "  WHERE o.id=d.order_id AND o.is_deleted=0)",
    ),
    (
        "退款单已退款但订单 pay_status 未联动",
        "SELECT COUNT(*) FROM oms_aftersale.aft_refund rf "
        "JOIN oms_order.ord_order o ON o.id=rf.order_id AND o.is_deleted=0 "
        "WHERE rf.status IN (3,5) "
        "  AND o.pay_status NOT IN ('refunded','part_refunded')",
    ),
    (
        "售后单在途但订单无售后中标记",
        "SELECT COUNT(*) FROM oms_aftersale.aft_return_apply a "
        "JOIN oms_order.ord_order o ON o.id=a.order_id AND o.is_deleted=0 "
        "WHERE a.status NOT IN (7,8,9) AND o.fulfill_status <> 'aftersale'",
    ),
    (
        "售后申请行指向不存在的申请单",
        "SELECT COUNT(*) FROM oms_aftersale.aft_return_apply_item i "
        "WHERE i.is_deleted=0 AND NOT EXISTS ("
        "  SELECT 1 FROM oms_aftersale.aft_return_apply a "
        "  WHERE a.id=i.apply_id)",
    ),
    (
        "退款单指向不存在的售后申请单（apply_id>0 时）",
        "SELECT COUNT(*) FROM oms_aftersale.aft_refund rf "
        "WHERE rf.apply_id>0 AND NOT EXISTS ("
        "  SELECT 1 FROM oms_aftersale.aft_return_apply a WHERE a.id=rf.apply_id)",
    ),
]


#: 目标 MySQL 容器（CI 复演用 ci_ci_mysql，本地默认 ktoms-mysql）
MYSQL_CONTAINER = os.environ.get("KTOMS_MYSQL_CONTAINER", "ktoms-mysql")


def _run(sql: str) -> int:
    r = subprocess.run(
        [
            "docker", "exec", MYSQL_CONTAINER, "mysql",
            "-uroot", "-pktoms_dev_2026", "-N", "-e", sql,
        ],
        capture_output=True,
        text=True,
    )
    out = (r.stdout or "").strip().splitlines()
    if not out:
        return -1
    try:
        return int(out[0])
    except ValueError:
        return -1


#: 可自动修复的数据不一致（孤儿记录：父表已删但子表残留）
FIXABLE: list[tuple[str, str]] = [
    (
        "孤儿缺货明细（异常单已删）",
        "DELETE FROM oms_order.ord_stockout WHERE is_deleted=0 AND abnormal_id NOT IN ("
        "SELECT id FROM oms_order.ord_abnormal WHERE is_deleted=0)",
    ),
    (
        "悬空异常单（订单已删）",
        "DELETE FROM oms_order.ord_abnormal WHERE is_deleted=0 AND order_id>0 "
        "AND order_id NOT IN (SELECT id FROM oms_order.ord_order WHERE is_deleted=0)",
    ),
    (
        "孤儿售后申请行（申请单已删）",
        "DELETE FROM oms_aftersale.aft_return_apply_item WHERE is_deleted=0 "
        "AND apply_id NOT IN (SELECT id FROM oms_aftersale.aft_return_apply)",
    ),
    (
        "孤儿售后日志（申请单已删）",
        "DELETE FROM oms_aftersale.aft_return_apply_log "
        "WHERE apply_id NOT IN (SELECT id FROM oms_aftersale.aft_return_apply)",
    ),
]


async def fix_orphans() -> int:
    """修复孤儿记录（父表已删但子表残留）—— 只删无主数据，不动业务数据"""
    fixed = 0
    for name, sql in FIXABLE:
        n = await asyncio.to_thread(_run, sql)
        if n > 0:
            print(f"  ↻ 已修复 {name}: {n} 条")
            fixed += n
    return fixed


async def main() -> int:
    print("===== 跨域数据一致性体检 =====")
    bad = 0
    for name, sql in CHECKS:
        n = await asyncio.to_thread(_run, sql)
        if n < 0:
            print(f"  ? {name}: 查询失败")
            bad += 1
        elif n == 0:
            print(f"  ✓ {name}: 0")
        else:
            print(f"  ✗ {name}: {n} 条不一致")
            bad += 1
    print(f"\n合计 {len(CHECKS)} 项体检，不一致 {bad} 项")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    if "--fix" in sys.argv:
        n = asyncio.run(fix_orphans())
        print(f"共修复 {n} 条孤儿记录")
    sys.exit(asyncio.run(main()))
