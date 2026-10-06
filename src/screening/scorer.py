"""
动量打分 — 分阶段权重打分, 0-100 (规则实现, 无 LLM)

权重为纸面跑初始值, 必须依据实测数据调参。
打分映射仓位 (待验证):
  90+   → 阶段额度满格
  75-90 → 约七成
  60-75 → 约四成
  <60   → 不开仓
"""

# 新创建/即将打满阶段权重
WEIGHTS_EARLY = {
    "curve_speed": 0.25,      # 曲线增速 (市值/价格增速)
    "net_buy": 0.20,          # 净买入 (买入量-卖出量)
    "dev_behavior": 0.15,     # dev/捆绑行为 (无砸盘=高分)
    "smart_money": 0.15,      # 聪明钱参与度
    "valuation": 0.15,        # 相对估值 (相对 M50 越低分越高)
    "call_heat": 0.10,        # 喊单热度
}

# 已开盘阶段权重
WEIGHTS_LIVE = {
    "price_momentum": 0.25,   # 价格动量
    "net_inflow": 0.20,       # 净流入
    "rel_valuation": 0.15,    # 相对估值
    "holder_growth": 0.15,    # holder 增长
    "turnover_liq": 0.15,     # 换手/流动性
    "narrative": 0.10,        # 催化叙事 (新闻确认器强度映射)
}


def _clamp01(x):
    return max(0.0, min(1.0, x))


def score_early_legacy(t: dict, m50: float | None = None) -> tuple[float, dict]:
    """新创建/即将打满打分【旧版, 2026-10-06 前生产版本】。
    保留用于影子对比与回滚。已知问题: net_buy 读 buys_1h 恒为 0;
    相对估值 ratio>3 直接 0 分。m50: 同阶段市值中位数 (相对估值锚)"""
    s = {}
    # 曲线增速: 用 5m/1h 涨幅映射
    mom = t.get("price_change_5m_pct") or 0
    s["curve_speed"] = _clamp01(mom / 50)
    # 净买入: buy/sell 比
    buys = t.get("buys_1h") or 0
    sells = t.get("sells_1h") or 1
    s["net_buy"] = _clamp01((buys - sells) / max(buys + sells, 1) * 2)
    # dev 行为: 无 dev 持仓/无砸盘=1
    dev = t.get("dev_hold_pct") or 0
    s["dev_behavior"] = _clamp01(1 - dev / 20)
    # 聪明钱
    sm = t.get("smart_money_count") or 0
    s["smart_money"] = _clamp01(sm / 10)
    # 相对估值: 相对 m50 越低分越高; >3x m50 追高禁区直接 0
    mcap = t.get("market_cap_usd") or 0
    if m50 and m50 > 0 and mcap > 0:
        ratio = mcap / m50
        s["valuation"] = 0.0 if ratio > 3 else _clamp01(1.5 - ratio / 2)
    else:
        s["valuation"] = 0.5
    # 喊单热度
    calls = t.get("call_count") or 0
    s["call_heat"] = _clamp01(calls / 20)

    total = sum(s[k] * w for k, w in WEIGHTS_EARLY.items())
    return round(total * 100, 1), {k: round(v * 100, 1) for k, v in s.items()}


def score_live_legacy(t: dict, m50: float | None = None,
               catalyst_strength: float = 0) -> tuple[float, dict]:
    """已开盘打分【旧版, 2026-10-06 前生产版本】。
    保留用于影子对比与回滚。已知问题: net_inflow/holder_growth/
    turnover_liq 三个维度因字段缺失恒为 0。"""
    s = {}
    mom = t.get("price_change_1h_pct") or 0
    s["price_momentum"] = _clamp01(mom / 100)
    inflow = t.get("net_inflow_usd_1h") or 0
    liq = t.get("liquidity_usd") or 1
    s["net_inflow"] = _clamp01(inflow / liq * 5)
    mcap = t.get("market_cap_usd") or 0
    if m50 and m50 > 0 and mcap > 0:
        ratio = mcap / m50
        s["rel_valuation"] = 0.0 if ratio > 3 else _clamp01(1.5 - ratio / 2)
    else:
        s["rel_valuation"] = 0.5
    hg = t.get("holder_change_1h_pct") or 0
    s["holder_growth"] = _clamp01(hg / 50)
    s["turnover_liq"] = _clamp01((t.get("volume_ratio_vs_avg") or 0) / 5)
    s["narrative"] = _clamp01(catalyst_strength / 100)

    total = sum(s[k] * w for k, w in WEIGHTS_LIVE.items())
    return round(total * 100, 1), {k: round(v * 100, 1) for k, v in s.items()}


def size_for_score(score: float, stage_max_usd: float) -> float:
    """打分映射仓位"""
    if score >= 90:
        return stage_max_usd
    if score >= 75:
        return round(stage_max_usd * 0.7, 2)
    if score >= 60:
        return round(stage_max_usd * 0.4, 2)
    return 0.0


# ================= 打分 v2 (2026-10-06 起为生产版本) =================
# 改动:
#  1. net_buy 字段修复: 旧代码读 buys_1h/sells_1h, 但数据映射只提供
#     buys_24h/sells_24h, 导致 net_buy(20%权重) 在生产中恒为 0。
#     v2 优先用 1h, 缺失时回退 24h (早盘币 24h≈生命周期, 可做代理)。
#  2. 相对估值改为"年龄/速度双维度": 旧逻辑 ratio>3 直接 0 分, 会系统性
#     错杀在扫描盲区内已完成第一波爆发的真金狗 (用户 2026-10-06 指出,
#     数据验证: 13 条 valuation=0 的淘汰记录市值 $14K-$31K)。
#     v2: 年轻(默认≤30min)+强动量 的币, ratio>3 时不归零, 改为平滑衰减;
#     年老或无动量的高比值仍判追高, 0 分。
#  3. score_live 补代理字段: net_inflow_usd_1h / volume_ratio_vs_avg /
#     holder_change_1h_pct 在 trenches 映射中不存在, 旧代码下三个维度
#     (共 50% 权重) 恒为 0。v2 用 24h 买卖笔数不平衡度代理净流入,
#     用 24h成交额/池子 代理换手; holder 增长暂无数据源, 仍为 0 (已知缺口)。
# 权重结构不变。

def _valuation_v2(ratio: float, age_minutes, momentum_pct,
                  young_minutes: float = 30,
                  hot_momentum: float = 30.0) -> float:
    """相对估值 v2。

    ratio ≤ 3 或 (年老/无动量): 与旧逻辑一致 —
      ratio 越低分越高, ratio>3 追高判 0。
    年轻(≤young_minutes) 且 强动量(≥hot_momentum):
      爆发中的金狗, 估值改为平滑缓衰, 不惩罚动量本身 —
      ratio=1→1.0, 3→0.83, 7→0.5, 13→0, 之后为 0。
      (旧逻辑在 ratio>3 直接 0, 且在 ratio=3 处有一个 0→0.6 的断崖;
       本曲线连续, 无断崖。)
    全确定性规则, 无 LLM。
    """
    young = age_minutes is not None and age_minutes <= young_minutes
    hot = (momentum_pct or 0) >= hot_momentum
    if young and hot:
        return _clamp01(1.0 - (ratio - 1) / 12)
    if ratio <= 3:
        return _clamp01(1.5 - ratio / 2)
    return 0.0


def _net_buy_ratio(t: dict) -> float:
    """买卖不平衡度 (-1~1)。优先 1h, 缺失回退 24h。"""
    buys = t.get("buys_1h")
    if buys is None:
        buys = t.get("buys_24h") or 0
    sells = t.get("sells_1h")
    if sells is None:
        sells = t.get("sells_24h") or 0
    tot = buys + sells
    if tot <= 0:
        return 0.0
    return (buys - sells) / tot


def score_early(t: dict, m50: float | None = None) -> tuple[float, dict]:
    """新创建/即将打满打分 (v2, 2026-10-06 起生产版本)。
    m50: 活币市值中位数 (已剔除死币, 见 filters.is_dead_for_benchmark)"""
    s = {}
    mom = t.get("price_change_5m_pct") or 0
    s["curve_speed"] = _clamp01(mom / 50)
    s["net_buy"] = _clamp01(_net_buy_ratio(t) * 2)
    dev = t.get("dev_hold_pct") or 0
    s["dev_behavior"] = _clamp01(1 - dev / 20)
    sm = t.get("smart_money_count") or 0
    s["smart_money"] = _clamp01(sm / 10)
    mcap = t.get("market_cap_usd") or 0
    if m50 and m50 > 0 and mcap > 0:
        s["valuation"] = _valuation_v2(mcap / m50, t.get("age_minutes"), mom)
    else:
        s["valuation"] = 0.5
    calls = t.get("call_count") or 0
    s["call_heat"] = _clamp01(calls / 20)

    total = sum(s[k] * w for k, w in WEIGHTS_EARLY.items())
    return round(total * 100, 1), {k: round(v * 100, 1) for k, v in s.items()}


def score_live(t: dict, m50: float | None = None,
                  catalyst_strength: float = 0) -> tuple[float, dict]:
    """已开盘打分 (v2, 2026-10-06 起生产版本)。
    m50: 活币市值中位数 (已剔除死币, 见 filters.is_dead_for_benchmark)"""
    s = {}
    mom = t.get("price_change_1h_pct") or 0
    s["price_momentum"] = _clamp01(mom / 100)
    # 净流入: 优先真实 1h 净流入, 缺失时用买卖笔数不平衡度代理
    inflow = t.get("net_inflow_usd_1h")
    liq = t.get("liquidity_usd") or t.get("pool_usd") or 1
    if inflow is not None:
        s["net_inflow"] = _clamp01(inflow / liq * 5)
    else:
        s["net_inflow"] = _clamp01(_net_buy_ratio(t) * 2)
    mcap = t.get("market_cap_usd") or 0
    if m50 and m50 > 0 and mcap > 0:
        s["rel_valuation"] = _valuation_v2(mcap / m50, t.get("age_minutes"),
                                          mom, young_minutes=60,
                                          hot_momentum=50.0)
    else:
        s["rel_valuation"] = 0.5
    # holder 1h 变化: 暂无数据源, 缺失为 0 (已知缺口, 见 STRATEGY.md)
    hg = t.get("holder_change_1h_pct") or 0
    s["holder_growth"] = _clamp01(hg / 50)
    # 换手/流动性: 优先 volume_ratio_vs_avg, 缺失时用 24h成交额/池子代理
    vr = t.get("volume_ratio_vs_avg")
    if vr is not None:
        s["turnover_liq"] = _clamp01(vr / 5)
    else:
        vol = t.get("volume_usd") or 0
        s["turnover_liq"] = _clamp01((vol / liq) / 10) if liq else 0.0
    s["narrative"] = _clamp01(catalyst_strength / 100)

    total = sum(s[k] * w for k, w in WEIGHTS_LIVE.items())
    return round(total * 100, 1), {k: round(v * 100, 1) for k, v in s.items()}
