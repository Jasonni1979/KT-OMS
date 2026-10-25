#!/usr/bin/env python3
"""演示数据装配脚本（走 HTTP API，验证 API 层真实可用）

用途：为前端界面提供可见的演示数据（档案/物料/库存/单据/导入任务），
让 Jason 在浏览器里体验到"有内容"的真实界面，而不是空表。

**约束**：只调用后端 HTTP API，不直接写库 → 顺带验证 API 契约与权限链路。

用法：
    cd KT-OMS/backend && .venv/bin/python -m app.scripts.seed_demo
    # 或指定后端地址
    KTOMS_DEMO_API=http://127.0.0.1:8000 .venv/bin/python -m app.scripts.seed_demo
"""
from __future__ import annotations

import os
import sys

import httpx

API = os.getenv("KTOMS_DEMO_API", "http://127.0.0.1:8000").rstrip("/")
PREFIX = f"{API}/api/v1"
LOGIN_NAME = os.getenv("KTOMS_DEMO_USER", "admin")
LOGIN_PWD = os.getenv("KTOMS_DEMO_PWD", "Ktoms@2026")

_client: httpx.Client | None = None


def _c() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=30.0)
    return _client


def api(method: str, path: str, **kw) -> object:
    """调 API 并断言 code=0"""
    r = _c().request(method, f"{PREFIX}{path}", **kw)
    try:
        body = r.json()
    except Exception as e:
        raise SystemExit(
            f"[FAIL] {method} {path} → HTTP {r.status_code} 非 JSON: {r.text[:200]}"
        ) from e
    if body.get("code") != 0:
        raise SystemExit(f"[FAIL] {method} {path} → {body.get('message')}")
    return body.get("data")


def get(path: str, **kw):
    return api("GET", path, **kw)


def post(path: str, json=None, **kw):
    return api("POST", path, json=json, **kw)


def put(path: str, json=None):
    return api("PUT", path, json=json)


def step(n: str, msg: str) -> None:
    print(f"  [{n}] {msg}")


def _find_owner_co_node() -> dict | None:
    """找 owner_co 组织节点（货主公司层，shop 的合法父节点）"""
    roots = get("/master/org-nodes", params={"parent_id": 0})
    for r in roots:
        for child in get("/master/org-nodes", params={"parent_id": r["id"]}):
            if child["node_type"] == "owner_co":
                return child
    return None


def login() -> None:
    data = post("/auth/login", json={"login_name": LOGIN_NAME, "password": LOGIN_PWD})
    token = data["access_token"]
    _c().headers["Authorization"] = f"Bearer {token}"
    step("auth", f"登录成功（{LOGIN_NAME}），token 已注入")


def seed_master() -> dict:
    """档案域：货主 / 店铺 / 仓库 + 仓货主关系"""
    print("\n▶ 档案域（D10.01）")
    owners = get("/master/owners")
    owner_map: dict[str, int] = {o["owner_code"]: o["id"] for o in owners}

    # 品牌代销货主
    if "DEMO_BRAND_001" not in owner_map:
        owner_co = _find_owner_co_node()
        if owner_co is None:
            raise SystemExit("[FAIL] 找不到 owner_co 节点，先跑 seed_org")
        o = post("/master/owners", json={
            "owner_code": "DEMO_BRAND_001",
            "owner_name": "演示品牌方（代销）",
            "owner_type": "BRAND_CONSIGN",
            "org_node_id": owner_co["id"],
            "contact_name": "王品牌",
        })
        owner_map["DEMO_BRAND_001"] = o["id"]
        step("owner", f"新建品牌代销货主 id={o['id']}")
    else:
        step("owner", "品牌代销货主已存在，幂等跳过")

    kc_id = owner_map.get("owner_KC") or next(iter(owner_map.values()))
    owner_co_node = _find_owner_co_node()
    if owner_co_node is None:
        raise SystemExit("[FAIL] 找不到 owner_co 节点，先跑 seed_org")

    # 店铺（API 自动联动挂组织树 shop 节点，父节点 = owner_co）
    shops = get("/master/shops")
    shop_map = {s["shop_name"]: s for s in shops}
    demo_shops = [
        ("演示天猫旗舰店", "taobao", "flagship", "direct_sale"),
        ("演示京东自营店", "jd", "direct", "direct_sale"),
        ("演示抖音品牌店", "douyin", "flagship", "direct_sale"),
    ]
    shop_ids: list[int] = []
    for name, plat, stype, btype in demo_shops:
        if name in shop_map:
            shop_ids.append(shop_map[name]["id"])
            continue
        s = post("/master/shops", params={"parent_node_id": owner_co_node["id"]}, json={
            "shop_name": name, "owner_id": kc_id, "platform": plat,
            "platform_shop_id": f"demo_{plat}_{len(shop_ids) + 1}",
            "shop_type": stype, "business_type": btype,
        })
        shop_ids.append(s["id"])
        step("shop", f"新建店铺 {name} id={s['id']}")

    # 仓库
    branches = get("/master/branches")
    bmap = {b["branch_name"]: b for b in branches}
    demo_branches = [
        # (名称, 类型, 省, 市, 地址, owner_id：None=多货主共享仓，>0=单一归属仓)
        ("演示共享中心仓", "entity", "上海市", "上海市", "浦东新区世纪大道100号", None),
        ("演示杭州前置仓", "cloud", "浙江省", "杭州市", "余杭区文一西路969号", kc_id),
        ("演示次品处理仓", "defective", "上海市", "上海市", "嘉定区马陆镇工业园8号", kc_id),
    ]
    branch_ids: list[int] = []
    shared_branch_id = 0
    for name, btype, prov, city, addr, b_owner in demo_branches:
        if name in bmap:
            branch_ids.append(bmap[name]["id"])
            if b_owner is None:
                shared_branch_id = bmap[name]["id"]
            continue
        payload = {
            "branch_name": name, "branch_type": btype,
            "is_ctrl": 1, "countable_flag": 1,
            "province": prov, "city": city, "address": addr,
        }
        if b_owner is not None:
            payload["owner_id"] = b_owner
        b = post("/master/branches", json=payload)
        branch_ids.append(b["id"])
        if b_owner is None:
            shared_branch_id = b["id"]
        step("branch", f"新建仓库 {name} id={b['id']}")

    # 仓 ↔ 可服务货主（共享仓批量绑多货主；单一归属仓自动绑定）
    if shared_branch_id:
        rels = post(f"/master/branches/{shared_branch_id}/owners", json={
            "owner_ids": sorted({kc_id, owner_map["DEMO_BRAND_001"]}), "operator": "demo",
        })
        step("bind", f"共享中心仓绑定 {len(rels)} 个可服务货主")

    return {
        "kc_owner_id": kc_id,
        "brand_owner_id": owner_map["DEMO_BRAND_001"],
        "shop_ids": shop_ids,
        "branch_ids": branch_ids,
    }


def seed_material(master: dict) -> dict:
    """物料域：分类树 / 品牌 / 基础物料 / 销售物料 + BOM / 条码"""
    print("\n▶ 物料域（D04.01）")
    owner_id = master["kc_owner_id"]
    cats = get("/material/categories/all")
    cat_map = {c["cat_name"]: c for c in cats}

    def ensure_cat(name: str, parent_id: int) -> int:
        if name in cat_map:
            return cat_map[name]["id"]
        c = post("/material/categories", json={"cat_name": name, "parent_id": parent_id})
        cat_map[name] = c
        step("cat", f"新建分类 {name} id={c['id']}")
        return c["id"]

    root = ensure_cat("服装", 0)
    top = ensure_cat("上装", root)
    tee = ensure_cat("T恤", top)
    bottom = ensure_cat("下装", root)
    trouser = ensure_cat("长裤", bottom)
    acc = ensure_cat("配件", 0)

    brands = get("/material/brands")
    brand_map = {b["brand_name"]: b for b in brands}
    brand_ids: dict[str, int] = {}
    for bname, ben in [("凯淳自有品牌", "KECHUN"), ("优衣库联名", "UNIQLO"), ("无印良品", "MUJI")]:
        if bname in brand_map:
            brand_ids[bname] = brand_map[bname]["id"]
            continue
        b = post("/material/brands", json={"brand_name": bname, "brand_name_en": ben, "owner_id": 0})
        brand_ids[bname] = b["id"]
        step("brand", f"新建品牌 {bname} id={b['id']}")

    mats = get("/material/materials")
    mat_map = {m["material_bn"]: m for m in mats}
    demo_mats = [
        ("KC-TS-001", "纯棉圆领T恤", tee, "凯淳自有品牌", "白色", "S", 199.0),
        ("KC-TS-002", "纯棉圆领T恤", tee, "凯淳自有品牌", "黑色", "M", 199.0),
        ("KC-PT-001", "休闲直筒长裤", trouser, "无印良品", "深蓝", "32", 299.0),
        ("KC-JK-001", "防风夹克", top, "优衣库联名", "军绿", "L", 599.0),
        ("KC-SK-001", "纯棉中筒袜", acc, "凯淳自有品牌", "均码", "35", 39.0),
        ("KC-PT-002", "直筒休闲西裤", trouser, "凯淳自有品牌", "灰色", "30", 359.0),
    ]
    mat_ids: list[int] = []
    for bn, name, cid, brand, color, size, price in demo_mats:
        if bn in mat_map:
            mat_ids.append(mat_map[bn]["id"])
            continue
        m = post("/material/materials", json={
            "material_bn": bn, "material_name": name, "owner_id": owner_id,
            "type": 3, "cat_id": cid, "brand_id": brand_ids[brand],
            "color": color, "size": size,
            "kingdee_material_code": f"KD-{bn}", "tax_rate": 13.0,
            "tax_name": "增值税", "remark": f"演示物料（{price}元）",
        })
        mat_ids.append(m["id"])
        step("mat", f"新建基础物料 {bn} {name}")

    # 销售物料 + BOM（绑定到基础物料）
    sms = get("/material/sales-materials")
    sm_map = {s["sales_material_bn"]: s for s in sms}
    sm_ids: list[int] = []
    shop_id = get("/master/shops")[0]["id"]
    for i, (bn, name, *_rest) in enumerate(demo_mats):
        sm_bn = f"SKU_{bn.replace('KC-', '')}"
        if sm_bn in sm_map:
            sm_ids.append(sm_map[sm_bn]["id"])
            continue
        sm = post("/material/sales-materials", json={
            "shop_id": shop_id, "sales_material_bn": sm_bn,
            "sales_material_name": name, "sales_material_type": 1,
            "spec_text": f"{demo_mats[i][4]}/{demo_mats[i][5]}",
        })
        sm_ids.append(sm["id"])
        # 绑定 BOM（基础物料）
        post(f"/material/sales-materials/{sm['id']}/bom", json={
            "items": [{"bm_id": mat_ids[i], "bind_num": 1, "rate": 100, "fixed_price": 0}],
            "operator": "demo",
        })
        step("sm", f"新建销售物料 {sm_bn} + BOM → 基础物料 {bn}")

    # 条码
    bcs = get("/material/barcodes")
    bc_map = {b["barcode"] for b in bcs}
    for i, (bn, *_r) in enumerate(demo_mats):
        code = f"69{abs(hash(bn)) % 10**12:012d}"
        if code in bc_map:
            continue
        post("/material/barcodes", json={
            "barcode": code, "bm_id": mat_ids[i], "barcode_type": 1, "shop_id": 0,
        })
    step("barcode", f"登记条码 {len(demo_mats)} 条")

    return {
        "cat_ids": {"tee": tee, "trouser": trouser, "acc": acc},
        "brand_ids": brand_ids,
        "mat_ids": mat_ids,
        "sm_ids": sm_ids,
        "mat_map": {bn: mat_ids[i] for i, (bn, *_r) in enumerate(demo_mats)},
    }


def seed_stock(master: dict, material: dict) -> dict:
    """库存域：期初记账 + 出入库单据 + 冻结/次品口径"""
    print("\n▶ 库存域（D04.02 / D04.04）")
    branch_id = master["branch_ids"][0]
    owner_id = master["kc_owner_id"]
    mats = material["mat_ids"]

    # 期初入库（走 /stock/ledger/change，幂等键防重复）
    opening_qty = [120, 80, 60, 45, 300, 40]
    balances = []
    for i, bm_id in enumerate(mats):
        qty = opening_qty[i]
        r = post("/stock/ledger/change", json={
            "branch_id": branch_id, "bm_id": bm_id, "owner_id": owner_id,
            "changes": [{"field": "store", "delta": qty}],
            "bill_type": "opening_in", "bill_bn": f"DEMO_OPEN_{i + 1:03d}",
            "bill_item_id": i + 1, "action": "inbound",
            "operator": "demo", "source": "migration", "remark": "演示期初",
        })
        balances.append(r["balances"])
        step("opening", f"期初入库 物料#{bm_id} × {qty}")

    # 次品库存（第 3 个物料）
    post("/stock/ledger/change", json={
        "branch_id": branch_id, "bm_id": mats[2], "owner_id": owner_id,
        "changes": [{"field": "defective", "delta": 5}],
        "bill_type": "defect_in", "bill_bn": "DEMO_DEFECT_001",
        "bill_item_id": 1, "action": "inbound", "operator": "demo", "source": "manual",
    })
    step("defect", "登记次品库存 5 件")

    # 在途库存（第 4 个物料）—— 让五口径都有数据
    post("/stock/ledger/change", json={
        "branch_id": branch_id, "bm_id": mats[3], "owner_id": owner_id,
        "changes": [{"field": "arrive_store", "delta": 12}],
        "bill_type": "arrive_in", "bill_bn": "DEMO_ARRIVE_001",
        "bill_item_id": 1, "action": "inbound", "operator": "demo", "source": "manual",
    })
    step("arrive", "登记在途库存 12 件")

    # 出入库单据（sale_out 口径模板为 action=settle → 必须先有预占才能核销）
    # 核销定位键 = 预占台账.obj_item_id == 单据行.source_item_id（真实链路里是订单行 ID）
    bill_types = get("/stock/bill/types")
    type_codes = [t["type_code"] for t in bill_types]
    bill_id = 0
    existing_bills = get("/stock/bills")
    already = {b["bill_bn"] for b in existing_bills}
    if "sale_out" in type_codes and not any("sale_out" in bn for bn in already):
        src_line_ids = [9001, 9002]
        # ① 先预占（Redis Lua 原子防超卖）
        post("/stock/freeze/reserve", json={
            "obj_type": 1, "obj_bn": "DEMO_SO_001",
            "items": [
                {"branch_id": branch_id, "bm_id": mats[0], "owner_id": owner_id,
                 "num": 3, "obj_item_id": src_line_ids[0]},
                {"branch_id": branch_id, "bm_id": mats[1], "owner_id": owner_id,
                 "num": 2, "obj_item_id": src_line_ids[1]},
            ],
        })
        step("freeze", "预占 3+2 件（Redis Lua 原子防超卖）")

        # ② 建单 → 下发 → 回传 → 确认即记账
        b = post("/stock/bills", json={
            "bill_type": "sale_out", "branch_id": branch_id, "owner_id": owner_id,
            "source_bill_type": "manual", "source_bill_bn": "DEMO_SO_001",
            "items": [
                {"bm_id": mats[0], "issued_num": 3, "confirmed_num": 3,
                 "unit_cost": 88.0, "source_item_id": src_line_ids[0]},
                {"bm_id": mats[1], "issued_num": 2, "confirmed_num": 2,
                 "unit_cost": 88.0, "source_item_id": src_line_ids[1]},
            ],
            "operator": "demo", "memo": "演示销售出库单",
        })
        bill_id = b["id"]
        post(f"/stock/bills/{bill_id}/push-wms", json={"wms_code": "WMS_DEMO_001"})
        post(f"/stock/bills/{bill_id}/callback", json={
            "wms_bill_no": "WMS_DEMO_001",
            "items": [
                {"bm_id": mats[0], "confirmed_num": 3},
                {"bm_id": mats[1], "confirmed_num": 2},
            ],
            "operator": "wms",
        })
        confirmed = post(f"/stock/bills/{bill_id}/confirm", json={"operator": "demo"})
        step("bill", f"销售出库单 {confirmed['bill_bn']} → 状态 {confirmed['status']}（确认即记账+核销预占）")

        # ③ 再来一张不需预占的调拨出库单，让单据列表有多态
        if "transfer_out" in type_codes and not any("transfer_out" in bn for bn in already):
            b2 = post("/stock/bills", json={
                "bill_type": "transfer_out", "branch_id": branch_id, "owner_id": owner_id,
                "source_bill_type": "manual", "source_bill_bn": "DEMO_TO_001",
                "items": [{"bm_id": mats[2], "issued_num": 10, "confirmed_num": 10, "unit_cost": 120.0}],
                "operator": "demo", "memo": "演示调拨出库单",
            })
            step("bill2", f"调拨出库单 {b2['bill_bn']} 已创建（草稿）")
    else:
        reason = (
            "单据类型目录无 sale_out"
            if "sale_out" not in type_codes
            else "销售出库单已存在，幂等跳过"
        )
        step("bill", f"{reason}（现有类型：{type_codes}）")

    return {"branch_id": branch_id, "owner_id": owner_id, "bill_id": bill_id}


def seed_import() -> None:
    """导入中心：登记模板（幂等）"""
    print("\n▶ 导入中心（D01.06）")
    try:
        tpls = get("/import/templates")
        step("tpl", f"已登记导入模板 {len(tpls)} 个：{[t['template_code'] for t in tpls]}")
    except SystemExit:
        step("tpl", "导入模板查询失败（该接口需要模板登记脚本 seed_import）")


def main() -> int:
    print("=== KT-OMS 演示数据装配（走 HTTP API）===\n")
    print(f"后端地址：{API}")
    try:
        r = httpx.get(f"{API}/healthz", timeout=5)
        print(f"健康检查：HTTP {r.status_code}")
    except Exception as e:
        raise SystemExit(f"[FAIL] 后端不可达：{e}") from e

    login()
    master = seed_master()
    material = seed_material(master)
    stock = seed_stock(master, material)
    seed_import()

    print("\n=== 完成 ===")
    print(f"货主：KC={master['kc_owner_id']} 品牌方={master['brand_owner_id']}")
    print(f"店铺：{master['shop_ids']}")
    print(f"仓库：{master['branch_ids']}")
    print(f"基础物料：{material['mat_ids']}")
    print(f"销售物料：{material['sm_ids']}")
    print(f"库存三元键基准：branch={stock['branch_id']} owner={stock['owner_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
