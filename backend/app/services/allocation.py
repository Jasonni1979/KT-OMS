"""优惠分摊算法（D03.01 §5.2 / FR-06b）

```
输入: 行集合 items(行原价 list_i), 单级优惠 D(商家 Ds + 平台 Dp), 平台行级分摊 P_i(可空)
1. 若平台自带 P_i 且 |ΣP_i − D| ≤ 0.01: 采用 P_i, 结束(勾稽通过记日志)
2. 否则比例分摊:
   base = Σ list_i
   for i in items: raw_i = D × list_i / base
   alloc_i = round_down(raw_i, 0.01)          # 逐行向下取整到分
   remainder = D − Σ alloc_i                  # 尾差(0 ≤ r < n×0.01)
   alloc_max = argmax(list_i)                 # 尾差归最大金额行
   alloc[alloc_max] += remainder
3. 双口径拆分: 每行 alloc_i 按 Ds:Dp 比例二次拆为 shop_i / platform_i(同尾差规则)
4. 行实付 paid_i = list_i − shop_i − platform_i
5. 校验: Σ paid_i == 订单实付(不含运费), 不等则整单落「金额勾稽异常」转人工
边界: 0 元行(赠品) list_i=0 → alloc_i=0, paid_i=0
```

纯函数实现（无 IO），便于单测与复用。
"""

from dataclasses import dataclass

#: 金额容差（元）
TOLERANCE = 0.01

#: 容差换算成「分」的整数（规避浮点尾数，见 _diff_cents）
_TOLERANCE_CENTS = int(round(TOLERANCE * 100))


def _diff_cents(a: float, b: float) -> int:
    """两金额之差（以「分」为单位的整数）

    ⚠ 不能直接用 `abs(a - b) > 0.01`：
    33435.54 - 33435.53 = 0.010000000002037268 > 0.01，
    「恰好差 1 分」会被浮点误差判成超差 → 金额正确的订单被误拒。
    """
    return abs(round(a * 100) - round(b * 100))


@dataclass
class LineAmount:
    """行级分摊结果"""

    line_no: int
    list_amount: float
    shop_discount: float
    platform_subsidy: float
    paid_amount: float


def _round_down(value: float, digits: int = 2) -> float:
    """向下取整到指定小数位（分摊用，避免累计偏差）"""
    factor = 10**digits
    return int(value * factor + 1e-9) / factor


def allocate(
    lines: list[tuple[int, float]],
    shop_discount: float,
    platform_subsidy: float,
    platform_line: dict[int, float] | None = None,
) -> tuple[list[LineAmount], list[str]]:
    """行级优惠分摊

    Args:
        lines: [(line_no, 行原价金额)]，行原价全为 0 的赠品行不参与分摊
        shop_discount: 单级商家承担优惠合计
        platform_subsidy: 单级平台承担优惠合计
        platform_line: 平台自带的行级分摊 {line_no: 金额}（FR-06b 平台值优先）

    Returns:
        (行级分摊结果, 告警列表)
    """
    warnings: list[str] = []
    result: dict[int, LineAmount] = {
        no: LineAmount(no, list_amt, 0.0, 0.0, list_amt)
        for no, list_amt in lines
    }
    total_discount = round(shop_discount + platform_subsidy, 2)
    base = round(sum(amt for _, amt in lines), 2)
    if total_discount <= 0 or base <= 0:
        return [result[no] for no, _ in lines], warnings

    # ---- 平台部分：平台自带行级值优先（FR-06b）----
    platform_alloc: dict[int, float] = {}
    if platform_line:
        p_sum = round(sum(platform_line.values()), 2)
        # ⚠ 按「分」整数比较：浮点下 1759.76 vs 1759.77 的差 = 0.010000000002037268
        #    > 0.01 → 会把「恰好差 1 分」误判为不符而回退比例分摊（复盘发现的真实缺陷）
        if _diff_cents(p_sum, platform_subsidy) <= _TOLERANCE_CENTS:
            platform_alloc = {no: float(v) for no, v in platform_line.items() if v}
        else:
            warnings.append(
                f"平台行级分摊合计({p_sum})与单级平台承担({platform_subsidy})不符，回退比例分摊"
            )
    if not platform_alloc:
        platform_alloc = _proportional(
            lines, platform_subsidy, warnings, "平台承担"
        )

    # ---- 商家部分：比例分摊 ----
    shop_alloc = _proportional(lines, shop_discount, warnings, "商家承担")

    # ---- 落行 ----
    for no, list_amt in lines:
        sa = round(shop_alloc.get(no, 0.0), 2)
        pa = round(platform_alloc.get(no, 0.0), 2)
        # 行优惠不得超过行原价（防负实付）
        # ⚠ 单边比较（sa+pa 是否**超过** list_amt），按「分」整数比较规避浮点尾数
        if round((sa + pa) * 100) > round(list_amt * 100) + _TOLERANCE_CENTS:
            scale = list_amt / (sa + pa) if (sa + pa) > 0 else 0
            sa = round(sa * scale, 2)
            pa = round(pa * scale, 2)
        result[no] = LineAmount(
            line_no=no,
            list_amount=list_amt,
            shop_discount=sa,
            platform_subsidy=pa,
            paid_amount=round(list_amt - sa - pa, 2),
        )
    return [result[no] for no, _ in lines], warnings


def _proportional(
    lines: list[tuple[int, float]],
    total: float,
    warnings: list[str],
    label: str,
) -> dict[int, float]:
    """比例分摊（向下取整到分 + 尾差归最大金额行）"""
    if total <= 0:
        return {}
    base = sum(amt for _, amt in lines)
    if base <= 0:
        return {}
    alloc: dict[int, float] = {}
    for no, amt in lines:
        alloc[no] = _round_down(total * amt / base)
    remainder = round(total - sum(alloc.values()), 2)
    # 尾差判定用「半分钱」阈值：舍入残差最多 n 行 × 0.01，
    # 用容差 TOLERANCE(0.01) 会把恰好 0.01 的尾差漏掉 → 分摊总额不平
    if abs(remainder) >= 0.005:
        # 尾差归最大金额行
        max_no = max(lines, key=lambda x: x[1])[0]
        alloc[max_no] = round(alloc[max_no] + remainder, 2)
        if remainder < 0:
            warnings.append(f"{label}分摊尾差 {remainder} 已归入最大金额行")
    return alloc


def check_amount_consistency(
    lines: list[LineAmount], customer_paid: float, freight: float
) -> tuple[bool, str]:
    """行实付勾稽校验（FR-04b：容差 0.01，超差拒单转人工）

    ⚠ **必须按「分」的整数比较**：直接用浮点 `abs(sum_paid - expect) > 0.01`
    会在「恰好差 0.01」时被浮点表示误差判成超差
    （如 33435.54 - 33435.53 = 0.010000000002037268 > 0.01），
    导致金额本身正确的订单被拒单——这是复盘发现的真实缺陷。
    """
    sum_paid = round(sum(line.paid_amount for line in lines), 2)
    expect = round(customer_paid - freight, 2)
    # 换算成「分」做整数比较，规避浮点尾数
    diff_cents = _diff_cents(sum_paid, expect)
    if diff_cents > _TOLERANCE_CENTS:
        return (
            False,
            f"金额勾稽超差: Σ行实付={sum_paid}，订单实付(不含运费)={expect}"
            f"（差 {diff_cents / 100:.2f} 元 > 容差 {TOLERANCE} 元）",
        )
    return True, ""
