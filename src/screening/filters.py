"""
初筛过滤器 — 用户手动经验的条件代码化 (规则实现, 无 LLM)

三阶段条件 (2026-10-05 用户确定):
- new_creation (新创建): txns>30, 总税≤4%, 喊单>1, holders>10, watchers>10
- near_completion (即将打满): age<30min, mcap>5K, txns>100, 总税≤4%,
  喊单>1, holders>20, watchers>50
- completed_hot (已开盘即热): age<300min, pool>3K, txns>800, 总税≤4%,
  喊单>5, holders>200, watchers>200

原则:
- 缺失字段 → 该条件判为 unknown, 整体 fail-closed (数据不全不开仓)
- 每个条件独立返回, 便于统计哪个条件过滤最多 (调参依据)
- "正在浏览人数" GMGN API 可能没有, 缺失时按 unknown 处理
"""
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    passed: bool
    failed: list[str] = field(default_factory=list)   # 未通过的条件名
    unknown: list[str] = field(default_factory=list)  # 数据缺失的条件名
    details: dict = field(default_factory=dict)       # 各条件实际值


def _get(t: dict, *keys):
    for k in keys:
        v = t.get(k)
        if v is not None:
            return v
    return None


def _check(cond_name, value, op, threshold, res: CheckResult):
    if value is None:
        res.unknown.append(cond_name)
        return False
    ok = op(value, threshold)
    res.details[cond_name] = value
    if not ok:
        res.failed.append(f"{cond_name}={value} (要求 {threshold})")
    return ok


def screen_new_creation(t: dict) -> CheckResult:
    """新创建阶段初筛"""
    r = CheckResult(passed=True)
    ok = True
    ok &= _check("txns", _get(t, "txns_1h", "txns"), lambda v, x: v > x, 30, r)
    tax = _get(t, "total_tax_pct")
    if tax is None:
        b = _get(t, "buy_tax_pct"); s = _get(t, "sell_tax_pct")
        tax = (b or 0) + (s or 0) if (b is not None or s is not None) else None
    ok &= _check("total_tax_pct", tax, lambda v, x: v <= x, 4, r)
    ok &= _check("call_count", _get(t, "call_count", "calls"), lambda v, x: v > x, 1, r)
    ok &= _check("holders", _get(t, "holders"), lambda v, x: v > x, 10, r)
    ok &= _check("watchers", _get(t, "watchers"), lambda v, x: v > x, 10, r)
    r.passed = ok and not r.unknown
    return r


def screen_near_completion(t: dict) -> CheckResult:
    """即将打满阶段初筛"""
    r = CheckResult(passed=True)
    ok = True
    ok &= _check("age_minutes", _get(t, "age_minutes"), lambda v, x: v < x, 30, r)
    ok &= _check("market_cap_usd", _get(t, "market_cap_usd", "mcap"), lambda v, x: v > x, 5000, r)
    ok &= _check("txns", _get(t, "txns_1h", "txns"), lambda v, x: v > x, 100, r)
    tax = _get(t, "total_tax_pct")
    if tax is None:
        b = _get(t, "buy_tax_pct"); s = _get(t, "sell_tax_pct")
        tax = (b or 0) + (s or 0) if (b is not None or s is not None) else None
    ok &= _check("total_tax_pct", tax, lambda v, x: v <= x, 4, r)
    ok &= _check("call_count", _get(t, "call_count", "calls"), lambda v, x: v > x, 1, r)
    ok &= _check("holders", _get(t, "holders"), lambda v, x: v > x, 20, r)
    ok &= _check("watchers", _get(t, "watchers"), lambda v, x: v > x, 50, r)
    r.passed = ok and not r.unknown
    return r


def screen_completed_hot(t: dict) -> CheckResult:
    """已开盘即热初筛 (注意: 300分钟仅用于识别"即热", 二段走生命周期状态机)"""
    r = CheckResult(passed=True)
    ok = True
    ok &= _check("age_minutes", _get(t, "age_minutes"), lambda v, x: v < x, 300, r)
    ok &= _check("pool_usd", _get(t, "pool_usd", "liquidity_usd"), lambda v, x: v > x, 3000, r)
    ok &= _check("txns", _get(t, "txns_1h", "txns"), lambda v, x: v > x, 800, r)
    tax = _get(t, "total_tax_pct")
    if tax is None:
        b = _get(t, "buy_tax_pct"); s = _get(t, "sell_tax_pct")
        tax = (b or 0) + (s or 0) if (b is not None or s is not None) else None
    ok &= _check("total_tax_pct", tax, lambda v, x: v <= x, 4, r)
    ok &= _check("call_count", _get(t, "call_count", "calls"), lambda v, x: v > x, 5, r)
    ok &= _check("holders", _get(t, "holders"), lambda v, x: v > x, 200, r)
    ok &= _check("watchers", _get(t, "watchers"), lambda v, x: v > x, 200, r)
    r.passed = ok and not r.unknown
    return r


SCREENS = {
    "new_creation": screen_new_creation,
    "near_completion": screen_near_completion,
    "completed_hot": screen_completed_hot,
}


def is_dead_for_benchmark(t: dict) -> bool:
    """死币判定 — 仅用于清洗估值基准 M50 的分母, 不直接筛掉任何币。

    规则 (2026-10-06 用户拍板):
    - 年龄 ≤10 分钟: 10 分钟内达不到"交易数>10 且 holder>5" → 发射失败, 已死
    - 年龄 >10 分钟: 24h 交易数<10 或 holder<5 → 已死 (宽松兜底口径)
    - 关键字段缺失 → 不判死 (保持旧口径, 宁可多算, 避免误杀)

    为什么: M50 原来用全量币(含大量死币, 实测 55% 市值<$5K) 做中位数,
    会把真正爆发的币衬托得"太贵"。死币不配当估值锚。
    """
    txns = t.get("txns_24h", t.get("txns"))
    holders = t.get("holders")
    if txns is None or holders is None:
        return False
    age = t.get("age_minutes")
    if age is not None and age <= 10:
        return txns <= 10 or holders <= 5
    return txns < 10 or holders < 5


def screen(token: dict, stage: str, ignore: set | None = None) -> CheckResult:
    """ignore: 跳过的条件名集合 (如 {'watchers'}), 用于两阶段筛选中
    第一阶段跳过需富化才能获得的字段"""
    fn = SCREENS.get(stage)
    if not fn:
        raise ValueError(f"unknown stage: {stage}")
    r = fn(token)
    if ignore:
        # 被忽略的条件从 unknown 中移除, 不计入 fail-closed
        r.unknown = [u for u in r.unknown if u not in ignore]
        r.passed = not r.failed and not r.unknown
    return r
