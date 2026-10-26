"""履约监控看板服务（SRS-D11.03 最小可用版 · W8-3）

D11.03 完整形态包含指标注册表 + Redis 实时埋点 + 分钟级时序表 + 8 大域指标
（FR-01a~FR-05b），W8 只做**评审可看的最小闭环**：

| 指标 | 口径 | 数据源 |
|---|---|---|
| 拉单水位落后 | 水位表 `last_download_time` 距今秒数 vs `lag_alert_threshold_sec` | `gw_pull_watermark` |
| 审单积压 | 未完成审单任务数（按 SLA 超期分级） | `ord_audit_task` |
| 回传失败 | 平台回传失败未处理 + WMS 指令失败未处理 | `gw_api_fail` + `ful_cmd_fail` |
| 异常单实时 | 未闭环异常单按类型/超期分级 | `ord_abnormal`（FR-08a 供数） |

⚠ **口径说明**（FR-01d：看板口径与经营口径差异必须明示）：
- 本看板为**实时快照**（直查业务表），非 D11.01 报表口径（按投审日/统计周期）
- 拉单水位用「水位表记录的最近拉单时间」计算，**不含** Redis 埋点分钟桶
  （D02.03 FR-07 的 Redis 埋点在 W10 统一接入）
- 审单积压按 `task_status` 未完成态统计，SLA 以 `sla_deadline` 为准
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import utcnow

#: SLA 超期分级（小时）—— 与 D03.09 §5.2 缺货账龄分级同口径
AGE_BUCKETS = (24, 48, 72)


class MonitorService:
    """监控看板聚合服务（D11.03）"""

    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    # ============ ① 拉单水位 ============

    async def pull_watermark(self) -> dict[str, Any]:
        """拉单水位（FR-01b：D02.03 域）

        每店铺一行：水位落后秒数 + 是否超阈值。
        """
        rows = (
            await self.s.execute(
                text(
                    "SELECT shop_id, channel, last_download_time, "
                    "       lag_alert_threshold_sec, poll_interval_sec "
                    "FROM oms_gateway.gw_pull_watermark ORDER BY shop_id"
                )
            )
        ).mappings().all()
        now = utcnow()
        items: list[dict[str, Any]] = []
        lagged = 0
        for r in rows:
            last = r["last_download_time"]
            lag = int((now - last).total_seconds()) if last else -1
            threshold = int(r["lag_alert_threshold_sec"] or 0)
            over = bool(threshold > 0 and lag >= 0 and lag > threshold)
            if over:
                lagged += 1
            items.append(
                {
                    "shop_id": int(r["shop_id"] or 0),
                    "channel": str(r["channel"] or ""),
                    "last_download_time": last.isoformat() if last else "",
                    "lag_seconds": lag,
                    "lag_alert_threshold_sec": threshold,
                    "poll_interval_sec": int(r["poll_interval_sec"] or 0),
                    "over_threshold": over,
                }
            )
        return {
            "total_shops": len(items),
            "lagged_shops": lagged,
            "items": items,
        }

    # ============ ② 审单积压 ============

    async def audit_backlog(self) -> dict[str, Any]:
        """审单积压（FR-01b：D03.02 域）

        未完成审单任务数 + SLA 超期分级（>24h/>48h/>72h）。
        """
        rows = (
            await self.s.execute(
                text(
                    "SELECT task_status, sla_deadline, create_time "
                    "FROM oms_order.ord_audit_task "
                    "WHERE is_deleted = 0 AND is_active = 1"
                )
            )
        ).mappings().all()
        now = utcnow()
        pending = 0
        overdue = 0
        buckets = {f"gt_{h}h": 0 for h in AGE_BUCKETS}
        by_status: dict[str, int] = {}
        for r in rows:
            status = str(r["task_status"] or "")
            by_status[status] = by_status.get(status, 0) + 1
            if status in ("done", "closed", "cancelled", "approved", "rejected"):
                continue
            pending += 1
            sla = r["sla_deadline"]
            if sla and sla < now:
                overdue += 1
                age_h = int((now - sla).total_seconds() // 3600)
                for h in AGE_BUCKETS:
                    if age_h >= h:
                        buckets[f"gt_{h}h"] += 1
        return {
            "pending": pending,
            "overdue": overdue,
            "age_buckets": buckets,
            "by_status": by_status,
        }

    # ============ ③ 回传失败 ============

    async def writeback_failures(self) -> dict[str, Any]:
        """回传失败（FR-01b：D02.05 + D09.02 域）

        平台回传失败（gw_api_fail）+ WMS 指令失败（ful_cmd_fail），均只统计
        **未处理**（未 dead / 未解决）的记录。
        """
        api_fail = int(
            await self.s.scalar(
                text(
                    "SELECT COUNT(*) FROM oms_gateway.gw_api_fail "
                    "WHERE is_dead = 0 AND status = 'waiting'"
                )
            )
            or 0
        )
        api_dead = int(
            await self.s.scalar(
                text(
                    "SELECT COUNT(*) FROM oms_gateway.gw_api_fail "
                    "WHERE is_dead = 1"
                )
            )
            or 0
        )
        cmd_fail = int(
            await self.s.scalar(
                text(
                    "SELECT COUNT(*) FROM oms_fulfill.ful_cmd_fail "
                    "WHERE status = 'waiting'"
                )
            )
            or 0
        )
        cmd_dead = int(
            await self.s.scalar(
                text(
                    "SELECT COUNT(*) FROM oms_fulfill.ful_cmd_fail "
                    "WHERE status = 'dead'"
                )
            )
            or 0
        )
        # 按错误级别分布（平台侧：RETRYABLE/RATE_LIMITED/AUTH/MANUAL/FATAL）
        levels = (
            await self.s.execute(
                text(
                    "SELECT err_level, COUNT(*) c FROM oms_gateway.gw_api_fail "
                    "WHERE is_dead = 0 AND status = 'waiting' "
                    "GROUP BY err_level"
                )
            )
        ).mappings().all()
        # 按 WMS 错误分类分布（通道侧：RETRYABLE/FATAL/BIZ_REJECT）
        classes = (
            await self.s.execute(
                text(
                    "SELECT err_class, COUNT(*) c FROM oms_fulfill.ful_cmd_fail "
                    "WHERE status = 'waiting' GROUP BY err_class"
                )
            )
        ).mappings().all()
        return {
            "platform_pending": api_fail,
            "platform_dead": api_dead,
            "wms_pending": cmd_fail,
            "wms_dead": cmd_dead,
            "total_pending": api_fail + cmd_fail,
            "by_err_level": {str(r["err_level"] or ""): int(r["c"]) for r in levels},
            "by_err_class": {str(r["err_class"] or ""): int(r["c"]) for r in classes},
        }

    # ============ ④ 异常单实时（FR-08a 供数）============

    async def abnormal_realtime(self) -> dict[str, Any]:
        """异常单实时监控（FR-08a：D03.09 域供数）

        未闭环异常单按类型分布 + SLA 超期分级 + 账龄分级。
        """
        rows = (
            await self.s.execute(
                text(
                    "SELECT exc_type, exc_category, status, sla_deadline, create_time "
                    "FROM oms_order.ord_abnormal WHERE is_deleted = 0"
                )
            )
        ).mappings().all()
        closed = ("resolved", "cancelled")
        now = utcnow()
        open_total = 0
        overdue = 0
        by_type: dict[str, int] = {}
        by_category: dict[str, int] = {}
        age_buckets = {f"gt_{h}h": 0 for h in AGE_BUCKETS}
        for r in rows:
            if str(r["status"]) in closed:
                continue
            open_total += 1
            et = str(r["exc_type"] or "")
            by_type[et] = by_type.get(et, 0) + 1
            cat = str(r["exc_category"] or "")
            by_category[cat] = by_category.get(cat, 0) + 1
            sla = r["sla_deadline"]
            if sla and sla < now:
                overdue += 1
            created = r["create_time"]
            if created:
                age_h = int((now - created).total_seconds() // 3600)
                for h in AGE_BUCKETS:
                    if age_h >= h:
                        age_buckets[f"gt_{h}h"] += 1
        return {
            "open_total": open_total,
            "overdue": overdue,
            "by_type": by_type,
            "by_category": by_category,
            "age_buckets": age_buckets,
        }

    # ============ 汇总 ============

    async def overview(self) -> dict[str, Any]:
        """看板总览（顶部指标卡 + 各域明细）"""
        watermark = await self.pull_watermark()
        backlog = await self.audit_backlog()
        failures = await self.writeback_failures()
        abnormal = await self.abnormal_realtime()
        return {
            "generated_at": utcnow().isoformat(),
            "cards": [
                {
                    "key": "pull_lag",
                    "title": "拉单水位落后店铺",
                    "value": watermark["lagged_shops"],
                    "total": watermark["total_shops"],
                    "unit": "家",
                    "level": "danger" if watermark["lagged_shops"] > 0 else "ok",
                },
                {
                    "key": "audit_backlog",
                    "title": "审单积压",
                    "value": backlog["pending"],
                    "total": backlog["overdue"],
                    "unit": "单",
                    "level": "warning" if backlog["overdue"] > 0 else "ok",
                    "hint": "总数 / 其中 SLA 超期",
                },
                {
                    "key": "writeback_fail",
                    "title": "回传失败未处理",
                    "value": failures["total_pending"],
                    "total": failures["platform_dead"] + failures["wms_dead"],
                    "unit": "条",
                    "level": "danger" if failures["total_pending"] > 0 else "ok",
                    "hint": "未处理 / 其中已死信",
                },
                {
                    "key": "abnormal_open",
                    "title": "未闭环异常单",
                    "value": abnormal["open_total"],
                    "total": abnormal["overdue"],
                    "unit": "单",
                    "level": "warning" if abnormal["overdue"] > 0 else "ok",
                    "hint": "未闭环 / 其中 SLA 超期",
                },
            ],
            "pull_watermark": watermark,
            "audit_backlog": backlog,
            "writeback_failures": failures,
            "abnormal_realtime": abnormal,
            "caliber_note": (
                "实时快照口径（直查业务表），非 D11.01 报表口径；"
                "拉单水位未含 Redis 分钟埋点（W10 统一接入）"
            ),
        }
