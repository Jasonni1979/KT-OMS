"""schema ↔ DDL 可空性一致性测试（防「声明必填但 DDL 可空 → 接口 500」）

**背景（W8-3 复盘发现）**：
`OrderOut.buyer_nick / warehouse_memo / buyer_memo` 与
`OrderItemOut.platform_oid / bm_name / bom_version` 在 DDL 里都是
**可空列**（is_nullable=YES，无默认值），但 pydantic schema 声明为非空 `str`
→ 遇到带 NULL 的真实数据时 `model_validate` 抛 ValidationError
→ **整个列表/详情接口 500，页面完全不可用**。

这类缺陷靠单测很难发现（测试造的数据往往都填了值），故用**真实库数据**做守门：
遍历所有「Out 型」schema，逐条 model_validate 库里的真实 ORM 行，
任何一个字段为 NULL 而 schema 声明为必填 → 直接失败。

⚠ 只校验**响应模型**（`model_config.from_attributes=True` 且有 model_validate
的真实数据路径）；Create/Update 等请求模型不用 ORM 数据校验（误报）。
"""
from __future__ import annotations

import importlib
import pkgutil

import pytest
from sqlalchemy import select

import app.models  # noqa: F401  （触发 ORM 注册）
import app.schemas as schemapskg
from app.core.db import AuthContext, SessionFactory, set_auth_context
from app.models.base import Base

pytestmark = pytest.mark.asyncio

#: 只校验响应模型（请求模型 Create/Update 用 ORM 数据校验会误报）
_RESPONSE_SUFFIXES = ("Out", "View", "Info", "Detail", "Row")


@pytest.fixture(autouse=True)
async def _ctx():
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    yield


def _collect_response_schemas() -> list[tuple[str, type]]:
    """收集所有响应型 pydantic 模型"""
    out: list[tuple[str, type]] = []
    for mi in pkgutil.iter_modules(schemapskg.__path__):
        mod = importlib.import_module(f"app.schemas.{mi.name}")
        for sname in dir(mod):
            s = getattr(mod, sname)
            if not isinstance(s, type) or not hasattr(s, "model_fields"):
                continue
            if not sname.endswith(_RESPONSE_SUFFIXES):
                continue
            # 必须声明 from_attributes（才能 model_validate ORM 行）
            cfg = getattr(s, "model_config", None)
            if not cfg or not cfg.get("from_attributes"):
                continue
            out.append((f"{mi.name}.{sname}", s))
    return out


def _match_orm(schema: type) -> type | None:
    """按字段名重合度匹配对应的 ORM 类"""
    fields = set(schema.model_fields.keys())
    if not fields:
        return None
    best, best_score = None, 0.0
    for mapper in Base.registry.mappers:
        cols = {c.name for c in mapper.local_table.columns}
        score = len(fields & cols) / len(fields)
        if score > best_score:
            best, best_score = mapper.class_, score
    return best if best_score > 0.7 else None


async def test_response_schemas_accept_real_db_rows():
    """所有响应 schema 都能校验库里的真实行（含 NULL 字段的行）

    这是「接口 500」类缺陷的守门测试：schema 声明必填但 DDL 可空的字段，
    在这里会直接暴露。
    """
    problems: list[str] = []
    checked = 0
    async with SessionFactory() as s:
        for label, S in _collect_response_schemas():
            C = _match_orm(S)
            if C is None:
                continue
            rows = list(await s.scalars(select(C).limit(200)))
            if not rows:
                continue
            checked += 1
            for r in rows:
                try:
                    S.model_validate(r)
                except Exception:  # noqa: BLE001 —— 收集全部问题再报
                    bad = []
                    for f, info in S.model_fields.items():
                        if not info.is_required():
                            continue
                        if getattr(r, f, None) is None:
                            bad.append(f)
                    problems.append(
                        f"{label} ← {C.__name__}(id={getattr(r, 'id', '?')}) "
                        f"必填字段为 NULL: {', '.join(bad) or '(类型不匹配)'}"
                    )
                    break
    assert not problems, (
        "以下响应 schema 声明必填、但 DDL 列可空 → 真实数据触发 500：\n  "
        + "\n  ".join(problems)
    )
    assert checked > 0, "未匹配到任何响应 schema（匹配逻辑可能失效）"


async def test_order_out_nullable_fields_declared_optional():
    """回归锁定：OrderOut / OrderItemOut 的可空字段必须声明为可选"""
    import app.schemas.order as sc

    for fname in ("buyer_nick", "warehouse_memo", "buyer_memo"):
        info = sc.OrderOut.model_fields[fname]
        assert not info.is_required(), f"OrderOut.{fname} 必须声明为可选（DDL 可空）"
    for fname in ("platform_oid", "bm_name", "bom_version"):
        info = sc.OrderItemOut.model_fields[fname]
        assert not info.is_required(), f"OrderItemOut.{fname} 必须声明为可选（DDL 可空）"


async def test_order_api_returns_200_with_nullable_rows():
    """回归锁定：带 NULL 字段的订单也能正常返回（接口不 500）"""
    import httpx
    from httpx import ASGITransport

    from app.main import app

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t"
    ) as c:
        r = await c.post(
            "/api/v1/auth/login",
            json={"login_name": "admin", "password": "Ktoms@2026"},
        )
        token = r.json()["data"]["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        rr = await c.get("/api/v1/orders", headers=h, params={"limit": 200})
        assert rr.status_code == 200, rr.text
        data = rr.json()["data"]
        assert isinstance(data, list)
        for row in data[:5]:
            d = await c.get(f"/api/v1/orders/{row['id']}", headers=h)
            assert d.status_code == 200, d.text
