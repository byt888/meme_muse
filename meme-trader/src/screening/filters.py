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


# 初筛阈值表 (按链独立, 单一数据源)
# bsc: 2026-10-05 用户确定, 不可动 (动之前先说)
# sol: 2026-10-07 bootstrap 临时值 = 照抄 bsc, 仅用于启动数据收集;
#      跑 1-2 周 SOL 数据后按分布重定, 见 config/sol_thresholds.yaml
THRESHOLDS = {
    "bsc": {
        "new_creation": {"txns": 30, "total_tax_pct": 4, "call_count": 1,
                         "holders": 10, "watchers": 10},
        "near_completion": {"age_minutes": 30, "market_cap_usd": 5000,
                            "txns": 100, "total_tax_pct": 4, "call_count": 1,
                            "holders": 20, "watchers": 50},
        "completed_hot": {"age_minutes": 300, "pool_usd": 3000, "txns": 800,
                          "total_tax_pct": 4, "call_count": 5,
                          "holders": 200, "watchers": 200},
    },
    "sol": {
        # BOOTSTRAP (2026-10-07): 照抄 bsc, 数据收集期用, 不作为有效阈值
        "new_creation": {"txns": 30, "total_tax_pct": 4, "call_count": 1,
                         "holders": 10, "watchers": 10},
        "near_completion": {"age_minutes": 30, "market_cap_usd": 5000,
                            "txns": 100, "total_tax_pct": 4, "call_count": 1,
                            "holders": 20, "watchers": 50},
        "completed_hot": {"age_minutes": 300, "pool_usd": 3000, "txns": 800,
                          "total_tax_pct": 4, "call_count": 5,
                          "holders": 200, "watchers": 200},
    },
}


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


def _th(chain: str, stage: str, key: str):
    """取阈值; 未知链回退 bsc (保守)"""
    return THRESHOLDS.get(chain, THRESHOLDS["bsc"])[stage][key]


def screen_new_creation(t: dict, chain: str = "bsc") -> CheckResult:
    """新创建阶段初筛"""
    th = THRESHOLDS.get(chain, THRESHOLDS["bsc"])["new_creation"]
    r = CheckResult(passed=True)
    ok = True
    ok &= _check("txns", _get(t, "txns_1h", "txns"), lambda v, x: v > x, th["txns"], r)
    tax = _get(t, "total_tax_pct")
    if tax is None:
        b = _get(t, "buy_tax_pct"); s = _get(t, "sell_tax_pct")
        tax = (b or 0) + (s or 0) if (b is not None or s is not None) else None
    ok &= _check("total_tax_pct", tax, lambda v, x: v <= x, th["total_tax_pct"], r)
    ok &= _check("call_count", _get(t, "call_count", "calls"), lambda v, x: v > x, th["call_count"], r)
    ok &= _check("holders", _get(t, "holders"), lambda v, x: v > x, th["holders"], r)
    ok &= _check("watchers", _get(t, "watchers"), lambda v, x: v > x, th["watchers"], r)
    r.passed = ok and not r.unknown
    return r


def screen_near_completion(t: dict, chain: str = "bsc") -> CheckResult:
    """即将打满阶段初筛"""
    th = THRESHOLDS.get(chain, THRESHOLDS["bsc"])["near_completion"]
    r = CheckResult(passed=True)
    ok = True
    ok &= _check("age_minutes", _get(t, "age_minutes"), lambda v, x: v < x, th["age_minutes"], r)
    ok &= _check("market_cap_usd", _get(t, "market_cap_usd", "mcap"), lambda v, x: v > x, th["market_cap_usd"], r)
    ok &= _check("txns", _get(t, "txns_1h", "txns"), lambda v, x: v > x, th["txns"], r)
    tax = _get(t, "total_tax_pct")
    if tax is None:
        b = _get(t, "buy_tax_pct"); s = _get(t, "sell_tax_pct")
        tax = (b or 0) + (s or 0) if (b is not None or s is not None) else None
    ok &= _check("total_tax_pct", tax, lambda v, x: v <= x, th["total_tax_pct"], r)
    ok &= _check("call_count", _get(t, "call_count", "calls"), lambda v, x: v > x, th["call_count"], r)
    ok &= _check("holders", _get(t, "holders"), lambda v, x: v > x, th["holders"], r)
    ok &= _check("watchers", _get(t, "watchers"), lambda v, x: v > x, th["watchers"], r)
    r.passed = ok and not r.unknown
    return r


def screen_completed_hot(t: dict, chain: str = "bsc") -> CheckResult:
    """已开盘即热初筛 (注意: 300分钟仅用于识别"即热", 二段走生命周期状态机)"""
    th = THRESHOLDS.get(chain, THRESHOLDS["bsc"])["completed_hot"]
    r = CheckResult(passed=True)
    ok = True
    ok &= _check("age_minutes", _get(t, "age_minutes"), lambda v, x: v < x, th["age_minutes"], r)
    ok &= _check("pool_usd", _get(t, "pool_usd", "liquidity_usd"), lambda v, x: v > x, th["pool_usd"], r)
    ok &= _check("txns", _get(t, "txns_1h", "txns"), lambda v, x: v > x, th["txns"], r)
    tax = _get(t, "total_tax_pct")
    if tax is None:
        b = _get(t, "buy_tax_pct"); s = _get(t, "sell_tax_pct")
        tax = (b or 0) + (s or 0) if (b is not None or s is not None) else None
    ok &= _check("total_tax_pct", tax, lambda v, x: v <= x, th["total_tax_pct"], r)
    ok &= _check("call_count", _get(t, "call_count", "calls"), lambda v, x: v > x, th["call_count"], r)
    ok &= _check("holders", _get(t, "holders"), lambda v, x: v > x, th["holders"], r)
    ok &= _check("watchers", _get(t, "watchers"), lambda v, x: v > x, th["watchers"], r)
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


def screen(token: dict, stage: str, ignore: set | None = None,
         chain: str = "bsc") -> CheckResult:
    """ignore: 跳过的条件名集合 (如 {'watchers'}), 用于两阶段筛选中
    第一阶段跳过需富化才能获得的字段
    chain: 按链取阈值 (bsc/sol), 默认 bsc 保持旧行为"""
    fn = SCREENS.get(stage)
    if not fn:
        raise ValueError(f"unknown stage: {stage}")
    r = fn(token, chain=chain)
    if ignore:
        # 被忽略的条件从 unknown 中移除, 不计入 fail-closed
        r.unknown = [u for u in r.unknown if u not in ignore]
        r.passed = not r.failed and not r.unknown
    return r
