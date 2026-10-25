"""模拟器订单数据仓库（内存）—— 对齐淘系 trade 报文形状

字段按淘系开放平台 taobao.trade.sold.get / trade.detail.get 的结构裁剪，
够 canonical 映射消费（gw_order_buffer + gw_order_buffer_item 所需列）。
"""
from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime

# 淘系订单状态
TRADE_STATUS = {
    "WAIT_BUYER_PAY": "等待买家付款",
    "WAIT_SELLER_SEND_GOODS": "等待卖家发货",
    "WAIT_BUYER_CONFIRM_GOODS": "等待买家确认收货",
    "TRADE_FINISHED": "交易成功",
    "TRADE_CLOSED": "交易关闭",
}

# 收货人加密通道
RECEIVER_CHANNEL = {
    "none": "明文",
    "oaid": "平台密文",
    "virtual": "虚拟号",
}


@dataclass
class SubOrder:
    """子订单（对应 gw_order_buffer_item）"""
    oid: str
    item_id: str
    sku_id: str
    item_title: str
    sku_spec: str
    num: int = 1
    price: float = 0.0
    total_fee: float = 0.0
    divide_order_fee: float = 0.0
    refund_status: str = "NO_REFUND"
    gift: bool = False


@dataclass
class Trade:
    """主订单（对应 gw_order_buffer）"""
    tid: str
    status: str
    created: str
    modified: str
    pay_time: str
    buyer_nick: str
    receiver_name: str
    receiver_mobile: str
    receiver_state: str
    receiver_city: str
    receiver_district: str
    receiver_address: str
    receiver_zip: str
    buyer_message: str
    seller_memo: str
    total_fee: float = 0.0
    post_fee: float = 0.0
    buyer_pay_amount: float = 0.0
    platform_bear_amount: float = 0.0
    consign_time: str = ""
    logistics_type: str = "快递"
    shipping_type: str = "快递"
    warehouse_hint: str = ""
    logistics_hint: str = ""
    receiver_encrypted_channel: str = "none"
    oaid: str = ""
    orders: list[SubOrder] = field(default_factory=list)
    # 仿真专用
    _scenario: str = ""
    _shop_id: str = "SIM_SHOP_001"

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_scenario", None)
        d.pop("_shop_id", None)
        return d

    @property
    def scenario(self) -> str:
        return self._scenario

    @property
    def shop_id(self) -> str:
        return self._shop_id

    @property
    def modified_ts(self) -> float:
        return datetime.strptime(self.modified, "%Y-%m-%d %H:%M:%S").timestamp()


class TradeStore:
    """内存订单池（模拟平台侧落库）"""

    def __init__(self) -> None:
        self._trades: dict[str, Trade] = {}
        self._seq = 0

    def next_tid(self) -> str:
        self._seq += 1
        return f"SIM{self._seq:010d}"

    def add(self, trade: Trade) -> None:
        self._trades[trade.tid] = trade

    def get(self, tid: str) -> Trade | None:
        return self._trades.get(tid)

    def all(self) -> list[Trade]:
        return list(self._trades.values())

    def clear(self) -> int:
        n = len(self._trades)
        self._trades.clear()
        self._seq = 0
        return n

    def query(self, *, start_modified: str | None = None, end_modified: str | None = None,
              status: str | None = None, shop_id: str | None = None,
              page_no: int = 1, page_size: int = 50) -> tuple[list[Trade], int]:
        """增量窗口查询 + 分页（淘系 page_no/page_size 语义）"""
        items = list(self._trades.values())
        if shop_id:
            items = [t for t in items if t.shop_id == shop_id]
        if status:
            items = [t for t in items if t.status == status]
        if start_modified:
            st = datetime.strptime(start_modified, "%Y-%m-%d %H:%M:%S").timestamp()
            items = [t for t in items if t.modified_ts >= st]
        if end_modified:
            et = datetime.strptime(end_modified, "%Y-%m-%d %H:%M:%S").timestamp()
            items = [t for t in items if t.modified_ts <= et]
        items.sort(key=lambda t: t.modified_ts)
        total = len(items)
        begin = (page_no - 1) * page_size
        return items[begin:begin + page_size], total


# ---------------- 造单场景库（V1.1 计划 §2.2） ----------------

SCENARIOS = {
    "normal": "正常单（单商品）",
    "multi_item": "多商品单（跨行）",
    "out_of_stock": "缺货触发（商品超出可售）",
    "address_abnormal": "地址异常（缺省区）",
    "unbound_item": "未绑定商品（平台商品未建档）",
    "buyer_message": "买家留言单",
    "big_amount": "大额单（多商品高金额）",
    "refund_only": "仅退款（售后）",
    "return_refund": "退货退款（售后）",
    "defective_return": "质检不良退货（售后）",
}

ADDR_POOL = [
    ("上海市", "上海市", "黄浦区", "南京东路100号"),
    ("广东省", "深圳市", "南山区", "科技园路88号"),
    ("浙江省", "杭州市", "余杭区", "文一西路969号"),
    ("北京市", "北京市", "朝阳区", "建国路93号"),
]
ITEM_POOL = [
    ("ITEM_TSHIRT_001", "SKU_TSHIRT_S", "纯棉圆领T恤", "S/白色"),
    ("ITEM_TSHIRT_002", "SKU_TSHIRT_M", "纯棉圆领T恤", "M/黑色"),
    ("ITEM_PANTS_001", "SKU_PANTS_32", "休闲直筒长裤", "32/深蓝"),
    ("ITEM_JACKET_001", "SKU_JACKET_L", "防风夹克", "L/军绿"),
    ("ITEM_SOCKS_001", "SKU_SOCKS_35", "纯棉中筒袜", "35/均码"),
]
BUYERS = ["买家小林", "买家小王", "买家小陈", "买家小李"]


def build_trade(store: TradeStore, scenario: str, *, now: datetime | None = None,
                shop_id: str = "SIM_SHOP_001") -> Trade:
    """按场景生成一笔订单（对齐 gw_order_buffer 所需字段）"""
    now = now or datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    rnd = random.Random()

    if scenario == "multi_item" or scenario == "big_amount":
        item_count = 3 if scenario == "multi_item" else 5
    else:
        item_count = 1

    state, city, district, address = rnd.choice(ADDR_POOL)
    if scenario == "address_abnormal":
        district = ""
        address = "未知地区"

    subs: list[SubOrder] = []
    total = 0.0
    for i in range(item_count):
        item_id, sku_id, title, spec = ITEM_POOL[(i + rnd.randint(0, 2)) % len(ITEM_POOL)]
        price = round(rnd.uniform(39, 499), 2)
        num = rnd.randint(1, 3)
        if scenario == "big_amount":
            price = round(rnd.uniform(899, 2999), 2)
            num = rnd.randint(2, 5)
        line_total = round(price * num, 2)
        total += line_total
        subs.append(SubOrder(
            oid=f"{store.next_tid()}O{i + 1}",
            item_id=item_id,
            sku_id=sku_id,
            item_title=title,
            sku_spec=spec,
            num=num,
            price=price,
            total_fee=line_total,
            divide_order_fee=line_total,
            refund_status="NO_REFUND",
        ))

    if scenario == "out_of_stock":
        # 数量放大，模拟下单量超可售
        subs[0].num = 999
        subs[0].total_fee = round(subs[0].price * 999, 2)
        total = sum(s.total_fee for s in subs)

    post_fee = 0.0 if total > 99 else 10.0
    buyer_pay = round(total + post_fee, 2)
    platform_bear = round(total * 0.05, 2)

    if scenario == "unbound_item":
        subs[0].item_id = "ITEM_NOT_ONBOARD_999"
        subs[0].sku_id = "SKU_NOT_ONBOARD_999"

    trade = Trade(
        tid=store.next_tid(),
        status="WAIT_SELLER_SEND_GOODS",
        created=ts,
        modified=ts,
        pay_time=ts,
        buyer_nick=rnd.choice(BUYERS),
        receiver_name="张收货",
        receiver_mobile="13800000000",
        receiver_state=state,
        receiver_city=city,
        receiver_district=district,
        receiver_address=address,
        receiver_zip="200000",
        buyer_message="麻烦发顺丰，谢谢" if scenario == "buyer_message" else "",
        seller_memo="",
        total_fee=round(total, 2),
        post_fee=post_fee,
        buyer_pay_amount=buyer_pay,
        platform_bear_amount=platform_bear,
        consign_time=ts,
        logistics_type="快递",
        shipping_type="快递",
        warehouse_hint="",
        logistics_hint="",
        receiver_encrypted_channel=rnd.choice(list(RECEIVER_CHANNEL.keys())),
        oaid="oaid_sim_xxx" if rnd.random() < 0.3 else "",
        orders=subs,
        _scenario=scenario,
        _shop_id=shop_id,
    )
    return trade


def build_refund(tid: str, scenario: str, now: datetime | None = None) -> dict:
    """售后单报文（refund.get 消费，仅退款/退货退款两类）"""
    now = now or datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    is_return = scenario in ("return_refund", "defective_return")
    return {
        "refund_id": f"RF{int(time.time() * 1000) % 10**12}",
        "tid": tid,
        "status": "SUCCESS" if scenario != "refund_only" else "PROCESSING",
        "refund_type": "RETURN_GOODS" if is_return else "ONLY_REFUND",
        "reason": ("七天无理由退换" if is_return else "不想要了"),
        "refund_amount": 99.0,
        "item_id": ITEM_POOL[0][0],
        "sku_id": ITEM_POOL[0][1],
        "num": 1,
        "created": ts,
        "modified": ts,
        "refunded_time": ts if scenario != "refund_only" else "",
        "goods_condition": "QUALITY_DEFECTIVE" if scenario == "defective_return" else "NORMAL",
        "success_time": ts,
    }
