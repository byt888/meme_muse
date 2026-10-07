"""
一票否决 — 满足任一条直接淘汰, 不进入打分 (规则实现, 无 LLM)

否决项 (2026-10-05 用户确定):
1. dev 或捆绑钱包簇正在净卖出
2. holder 一小时流失 >20%
3. 无新催化时从高点回撤 >60%
4. wash trading 检出
5. 安全复检失败 (honeypot / 高 rug_ratio / top10 过度集中)
"""
from dataclasses import dataclass, field


@dataclass
class VetoResult:
    vetoed: bool
    reasons: list[str] = field(default_factory=list)


def check_veto(t: dict, has_fresh_catalyst: bool = False) -> VetoResult:
    r = VetoResult(vetoed=False)

    # 1. dev/捆绑净卖出
    if t.get("dev_net_selling"):
        r.reasons.append("dev/捆绑钱包正在净卖出")

    # 2. holder 1h 流失 >20%
    hc = t.get("holder_change_1h_pct")
    if hc is not None and hc < -20:
        r.reasons.append(f"holder 1h 流失 {hc:.1f}%")

    # 3. 无新催化 + 从高点回撤 >60%
    dd = t.get("drawdown_from_high_pct")
    if dd is not None and dd > 60 and not has_fresh_catalyst:
        r.reasons.append(f"无催化回撤 {dd:.1f}%")

    # 4. wash trading
    if t.get("wash_trading") or (t.get("wash_ratio") or 0) > 0.3:
        r.reasons.append("wash trading 检出")

    # 5. 安全复检
    if t.get("is_honeypot"):
        r.reasons.append("honeypot")
    rug = t.get("rug_ratio")
    if rug is not None and rug > 0.3:
        r.reasons.append(f"rug_ratio {rug:.2f} 过高")
    top10 = t.get("top10_holder_pct")
    if top10 is not None and top10 > 50:
        r.reasons.append(f"top10 持仓 {top10:.1f}% 过度集中")
    dev_hold = t.get("dev_hold_pct")
    if dev_hold is not None and dev_hold > 20:
        r.reasons.append(f"dev 持仓 {dev_hold:.1f}% 过高")

    r.vetoed = bool(r.reasons)
    return r
