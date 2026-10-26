"""M7 WMS 路由服务（D09.01 FR-04a：路由四元组）"""

from __future__ import annotations

import json
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.wms import (
    WmsRoute,
)
from app.core.exceptions import NotFoundError


class WmsRouteService:
    """WMS 路由服务（D09.01 FR-04a：路由四元组）"""

    def __init__(self, session: AsyncSession):
        self.s = session

    async def route(
        self, branch_id: int, owner_id: int, direction: str = "OUT"
    ) -> WmsRoute:
        """路由决策（幂等只读）

        查有效 wms_binding（按 branch + owner 匹配、优先级降序、有效期），
        返回四元组；无绑定 → 结构化失败（ValueError）。
        """
        rows = await self.s.execute(
            text(
                "SELECT b.id, b.wms_id, b.protocol, b.adapter_code, b.wms_branch_code, "
                "       COALESCE(b.wms_owner_code, '') AS wms_owner_code, "
                "       COALESCE(b.app_key, '') AS app_key, "
                "       b.endpoint, b.timeout_ms, b.capability_json, b.priority "
                "FROM oms_fulfill.ful_wms_binding b "
                "JOIN oms_fulfill.ful_wms w ON w.id = b.wms_id "
                "WHERE b.branch_id = :bid AND b.is_deleted = 0 AND b.status = 'active' "
                "  AND w.status = 'enabled' AND w.is_deleted = 0 "
                "  AND (b.owner_id IS NULL OR b.owner_id = :oid) "
                "  AND (b.effective_from IS NULL OR b.effective_from <= NOW(3)) "
                "  AND (b.effective_to IS NULL OR b.effective_to > NOW(3)) "
                "ORDER BY b.priority ASC, b.id ASC LIMIT 1"
            ),
            {"bid": branch_id, "oid": owner_id},
        )
        row = rows.mappings().first()
        if not row:
            raise NotFoundError(
                f"无 WMS 绑定（仓 {branch_id} · 货主 {owner_id} · 方向 {direction}）"
            )
        cap = row["capability_json"]
        if isinstance(cap, str):
            try:
                cap = json.loads(cap)
            except (TypeError, ValueError):
                cap = {}
        return WmsRoute(
            wms_id=int(row["wms_id"]),
            binding_id=int(row["id"]),
            adapter_code=str(row["adapter_code"] or ""),
            app_key=str(row["app_key"] or ""),
            # secret：生产从 secret_enc 解密；仿真期取环境变量默认值
            secret=os.environ.get("MOCK_WMS_SECRET", "mock_wms_secret"),
            wms_branch_code=str(row["wms_branch_code"] or ""),
            wms_owner_code=str(row["wms_owner_code"] or ""),
            protocol=str(row["protocol"] or "qimen"),
            endpoint=str(row["endpoint"] or ""),
            timeout_ms=int(row["timeout_ms"] or 10000),
            capability=cap or {},
        )
