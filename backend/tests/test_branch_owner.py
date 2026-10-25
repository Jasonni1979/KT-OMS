"""仓 ↔ 可服务货主关系测试（D10.01 FR-07a：D09.01 消费 / D04.02 三元记账前提）

覆盖：建仓自动绑定 / 多货主仓批量绑定 / 单一归属仓拒绑其他货主 / 非管控仓拒绑 /
非合作中货主拒绑 / 绑定幂等 / 解绑 / 按货主反查仓。
"""
import pytest
from sqlalchemy import text

from app.core.db import engine

pytestmark = pytest.mark.asyncio

CLEANUP_SQL = [
    # 关系先删（引用仓节点与货主）
    "DELETE FROM oms_org.org_node_relation WHERE rel_type='branch_owner' "
    "AND node_id IN (SELECT id FROM oms_org.org_node WHERE org_code LIKE 'WH\\_%')",
    "DELETE FROM oms_org.org_node_relation WHERE rel_type='branch_owner' "
    "AND rel_id IN (SELECT id FROM oms_org.org_owner WHERE owner_code LIKE 'T\\_%')",
    "DELETE FROM oms_fulfill.ful_branch WHERE branch_name LIKE '测试%'",
    "DELETE FROM oms_org.org_node WHERE org_code LIKE 'WH\\_%' OR org_code LIKE 'T\\_%'",
    "DELETE FROM oms_org.org_owner WHERE owner_code LIKE 'T\\_%'",
]


async def _cleanup() -> None:
    async with engine.begin() as conn:
        for sql in CLEANUP_SQL:
            await conn.execute(text(sql))


@pytest.fixture(autouse=True, scope="module")
async def isolate_branch_owner_data():
    await _cleanup()
    yield
    await _cleanup()


async def _owner_co_node_id() -> int:
    async with engine.begin() as conn:
        r = await conn.execute(
            text("SELECT id FROM oms_org.org_node "
                 "WHERE node_type='owner_co' AND is_deleted=0 LIMIT 1")
        )
        return int(r.scalar())


async def _make_owner(auth_client, code: str, name: str, owner_type: str = "KC_BUYOUT") -> dict:
    """建测试货主"""
    node_id = await _owner_co_node_id()
    r = await auth_client.post("/api/v1/master/owners", json={
        "owner_code": code, "owner_name": name, "owner_type": owner_type,
        "org_node_id": node_id,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _make_branch(auth_client, name: str, owner_id: int | None, is_ctrl: int = 1) -> dict:
    """建测试仓（owner_id 为空 → 多货主仓）"""
    r = await auth_client.post("/api/v1/master/branches", json={
        "branch_name": name, "owner_id": owner_id, "is_ctrl": is_ctrl, "countable_flag": 1,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_single_owner_branch_auto_binds(auth_client):
    """建单一归属仓 → 自动绑定其归属货主（无需人工配置）"""
    owner = await _make_owner(auth_client, "T_BO_AUTO", "自动绑定货主")
    branch = await _make_branch(auth_client, "测试单一归属仓", owner["id"])

    r = await auth_client.get(f"/api/v1/master/branches/{branch['id']}/owners")
    assert r.status_code == 200, r.text
    rels = r.json()["data"]
    assert len(rels) == 1
    assert rels[0]["owner_id"] == owner["id"]
    assert rels[0]["owner_code"] == "T_BO_AUTO"
    assert rels[0]["status"] == 1
    assert rels[0]["is_primary"] == 1  # 单一归属仓 → 主关联


async def test_multi_owner_branch_bind_batch(auth_client):
    """多货主仓批量绑定多个货主"""
    o1 = await _make_owner(auth_client, "T_BO_M1", "多货主仓货主1")
    o2 = await _make_owner(auth_client, "T_BO_M2", "多货主仓货主2")
    branch = await _make_branch(auth_client, "测试多货主仓", None)

    r = await auth_client.post(f"/api/v1/master/branches/{branch['id']}/owners", json={
        "owner_ids": [o1["id"], o2["id"]], "operator": "tester",
    })
    assert r.status_code == 200, r.text
    rels = r.json()["data"]
    assert {x["owner_id"] for x in rels if x["status"] == 1} == {o1["id"], o2["id"]}


async def test_single_owner_branch_reject_other_owner(auth_client):
    """单一归属仓不可绑定其他货主"""
    o1 = await _make_owner(auth_client, "T_BO_S1", "单一归属货主")
    o2 = await _make_owner(auth_client, "T_BO_S2", "其他货主")
    branch = await _make_branch(auth_client, "测试单一归属仓2", o1["id"])

    r = await auth_client.post(f"/api/v1/master/branches/{branch['id']}/owners", json={
        "owner_ids": [o2["id"]],
    })
    assert r.status_code == 422
    assert "不可绑定其他货主" in r.json()["message"]


async def test_multi_owner_branch_requires_ctrl(auth_client):
    """多货主仓取消管控后不可配置可服务货主"""
    o1 = await _make_owner(auth_client, "T_BO_C1", "管控货主")
    branch = await _make_branch(auth_client, "测试多货主仓2", None, is_ctrl=1)

    # 先绑上（管控中，允许）
    r0 = await auth_client.post(f"/api/v1/master/branches/{branch['id']}/owners", json={
        "owner_ids": [o1["id"]],
    })
    assert r0.status_code == 200, r0.text

    # 关闭管控 → 再次绑定应被拒
    r_up = await auth_client.put(f"/api/v1/master/branches/{branch['id']}", json={
        "is_ctrl": 0, "version": branch["version"],
    })
    assert r_up.status_code == 200, r_up.text
    r = await auth_client.post(f"/api/v1/master/branches/{branch['id']}/owners", json={
        "owner_ids": [o1["id"]],
    })
    assert r.status_code == 422
    assert "管控库存" in r.json()["message"]


async def test_bind_reject_inactive_owner(auth_client):
    """非合作中货主（status!=1）不可绑定"""
    o1 = await _make_owner(auth_client, "T_BO_INA", "暂停货主")
    branch = await _make_branch(auth_client, "测试多货主仓3", None)

    # 直接改库把货主置为暂停（API 不开放 status 变更）
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE oms_org.org_owner SET status=2 WHERE id=:oid"), {"oid": o1["id"]}
        )

    r = await auth_client.post(f"/api/v1/master/branches/{branch['id']}/owners", json={
        "owner_ids": [o1["id"]],
    })
    assert r.status_code == 422
    assert "非合作中" in r.json()["message"]


async def test_bind_is_idempotent(auth_client):
    """重复绑定幂等：关系数不增，已停用关系重新启用"""
    o1 = await _make_owner(auth_client, "T_BO_IDM", "幂等货主")
    branch = await _make_branch(auth_client, "测试多货主仓4", None)

    r1 = await auth_client.post(f"/api/v1/master/branches/{branch['id']}/owners", json={
        "owner_ids": [o1["id"]],
    })
    assert r1.status_code == 200
    r2 = await auth_client.post(f"/api/v1/master/branches/{branch['id']}/owners", json={
        "owner_ids": [o1["id"]],
    })
    assert r2.status_code == 200
    active = [x for x in r2.json()["data"] if x["status"] == 1]
    assert len(active) == 1

    # 停用后再绑 → 重新启用（仍只有 1 条启用关系）
    rel_id = active[0]["id"]
    await auth_client.delete(f"/api/v1/master/branch-owner-rels/{rel_id}")
    r3 = await auth_client.post(f"/api/v1/master/branches/{branch['id']}/owners", json={
        "owner_ids": [o1["id"]],
    })
    assert r3.status_code == 200
    active3 = [x for x in r3.json()["data"] if x["status"] == 1]
    assert len(active3) == 1
    assert active3[0]["id"] == rel_id


async def test_unbind_sets_status_disabled(auth_client):
    """解绑：关系置停用而非物理删除（保留审计痕迹）"""
    o1 = await _make_owner(auth_client, "T_BO_UNB", "解绑货主")
    branch = await _make_branch(auth_client, "测试多货主仓5", None)

    r = await auth_client.post(f"/api/v1/master/branches/{branch['id']}/owners", json={
        "owner_ids": [o1["id"]],
    })
    rel = next(x for x in r.json()["data"] if x["status"] == 1)

    d = await auth_client.delete(f"/api/v1/master/branch-owner-rels/{rel['id']}")
    assert d.status_code == 200, d.text

    # 关系仍在库中但已停用
    async with engine.begin() as conn:
        rq = await conn.execute(
            text("SELECT status FROM oms_org.org_node_relation WHERE id=:rid"), {"rid": rel["id"]}
        )
        assert int(rq.scalar()) == 2

    # 该货主不再出现在启用关系中
    lr = await auth_client.get(f"/api/v1/master/branches/{branch['id']}/owners")
    assert all(x["status"] == 2 for x in lr.json()["data"] if x["id"] == rel["id"])


async def test_list_branches_by_owner(auth_client):
    """按货主反查可服务的仓（D04.02 按货主隔离记账用）"""
    o1 = await _make_owner(auth_client, "T_BO_Q1", "查询货主")
    branch = await _make_branch(auth_client, "测试多货主仓6", None)
    await auth_client.post(f"/api/v1/master/branches/{branch['id']}/owners", json={
        "owner_ids": [o1["id"]],
    })

    r = await auth_client.get(f"/api/v1/master/owners/{o1['id']}/branches")
    assert r.status_code == 200, r.text
    branches = r.json()["data"]
    assert any(b["branch_id"] == branch["id"] for b in branches)
    assert all(b["owner_id"] == o1["id"] for b in branches)


async def test_bind_branch_not_found(auth_client):
    """不存在/已删仓 → 404"""
    r = await auth_client.post("/api/v1/master/branches/99999999/owners", json={
        "owner_ids": [1],
    })
    assert r.status_code == 404
