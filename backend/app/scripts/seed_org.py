"""FR-08a default 运营组织初始化（幂等，可重跑）

创建：group 根「凯淳集团」(KC_ROOT) + 货主公司节点「凯淳贸易主体」+ 默认货主 owner_KC（凯淳买断，FR-03c）。
以 org_code/owner_code 判重实现幂等。用法：
    .venv/bin/python -m app.scripts.seed_org
"""
import asyncio

from sqlalchemy import select

from app.core.db import SessionFactory, engine, without_data_scope
from app.models.org import OrgNode, OrgOwner


async def seed() -> None:
    # 豁免通道登记点③：系统级初始化脚本（无用户上下文，fail-closed 下需显式豁免）
    with without_data_scope():
        await _seed_impl()


async def _seed_impl() -> None:
    async with SessionFactory() as s:
        # 1) group 根节点（唯一根，FR-01e）
        root = await s.scalar(select(OrgNode).where(OrgNode.org_code == "KC_ROOT"))
        if not root:
            root = OrgNode(
                tenant_id=1, org_code="KC_ROOT", org_name="凯淳集团", node_type="group",
                parent_id=0, cat_path="", node_level=1, sort_no=1, source="local",
            )
            s.add(root)
            await s.flush()
            root.cat_path = f",{root.id},"
            print(f"[seed] group 根节点创建: id={root.id}")
        else:
            print(f"[seed] group 根节点已存在: id={root.id}（幂等跳过）")

        # 2) 货主公司节点「凯淳贸易主体」
        owner_co = await s.scalar(select(OrgNode).where(OrgNode.org_code == "KC_TRADE_CO"))
        if not owner_co:
            owner_co = OrgNode(
                tenant_id=1, org_code="KC_TRADE_CO", org_name="凯淳贸易主体", node_type="owner_co",
                parent_id=root.id, cat_path="", node_level=root.node_level + 1, sort_no=1, source="local",
            )
            s.add(owner_co)
            await s.flush()
            owner_co.cat_path = f"{root.cat_path}{owner_co.id},"
            print(f"[seed] owner_co 节点创建: id={owner_co.id}")
        else:
            print(f"[seed] owner_co 节点已存在: id={owner_co.id}（幂等跳过）")

        # 3) 唯一默认货主 owner_KC（凯淳买断，FR-03c，不可停用）
        owner = await s.scalar(select(OrgOwner).where(OrgOwner.owner_code == "owner_KC"))
        if not owner:
            owner = OrgOwner(
                tenant_id=1, owner_code="owner_KC", owner_name="凯淳自营（默认货主）",
                owner_type="KC_BUYOUT", org_node_id=owner_co.id, source="local",
            )
            s.add(owner)
            await s.flush()
            print(f"[seed] 默认货主创建: id={owner.id}")
        else:
            print(f"[seed] 默认货主已存在: id={owner.id}（幂等跳过）")

        await s.commit()
        print("[seed] 完成")


if __name__ == "__main__":
    async def _main():
        await seed()
        await engine.dispose()

    asyncio.run(_main())
