"""退出模拟合成测试: python3 tests/test_exit_sim.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from risk.exit_sim import simulate_exit


def candles(prices, start_ts=1_000_000, step=300):
    """prices: 每根 K 线的 close; high/low 取相邻极值"""
    out = []
    prev = prices[0]
    for i, c in enumerate(prices):
        hi = max(prev, c)
        lo = min(prev, c)
        out.append({"ts": start_ts + i * step, "open": prev,
                    "high": hi, "low": lo, "close": c})
        prev = c
    return out


def show(name, res):
    print(f"[{name}] closed={res['closed']} reason={res['exit_reason']} "
          f"pnl={res['pnl_usd']:+.2f} ({res['pnl_pct']:+.1f}%) "
          f"peak={res['peak_pct']:+.1f}% hold={res['hold_minutes']:.0f}min "
          f"events={len(res['events'])}")


# 1. 直线下跌 40% → 硬止损 -30% 全平
r = simulate_exit(1_000_000, 1.0, 100.0,
                  candles([1.0, 0.9, 0.8, 0.7, 0.6]))
show("hard_stop", r)
assert r["closed"] and r["exit_reason"] == "hard_stop"
assert abs(r["pnl_pct"] - (-34.1)) < 0.5, r["pnl_pct"]

# 2. +150% 后回落 → TP1(+100%卖半) + 25% 移动止盈
r = simulate_exit(1_000_000, 1.0, 100.0,
                  candles([1.0, 1.5, 2.0, 2.5, 2.4, 2.0, 1.8, 1.8]))
show("tp1_trailing", r)
assert r["closed"] and r["exit_reason"] == "trailing"
assert r["events"][0]["reason"] == "tp1_+100%"
assert abs(r["pnl_pct"] - 82.4) < 1.0, r["pnl_pct"]

# 3. +500% 后腰斩 → TP1 + TP2(+400%) + 月球 40% 移动止盈
r = simulate_exit(1_000_000, 1.0, 100.0,
                  candles([1.0, 2.0, 3.0, 5.0, 6.0, 5.0, 4.0, 3.0]))
show("tp2_moon", r)
assert r["closed"] and r["exit_reason"] == "moon_trailing"
assert [e["reason"] for e in r["events"]] == ["tp1_+100%", "tp2_+400%", "moon_trailing"]
assert abs(r["pnl_pct"] - 196.6) < 1.0, r["pnl_pct"]

# 4. 横盘 5 小时 → 4h 时间止损, 只亏手续费
r = simulate_exit(1_000_000, 1.0, 100.0,
                  candles([1.0] * 61))  # 61 根 5m = 305min > 4h
show("time_stop", r)
assert r["closed"] and r["exit_reason"] == "time_stop_4h"
assert abs(r["pnl_pct"] - (-5.8)) < 0.5, r["pnl_pct"]

# 5. 数据中途结束 → 保持 open, 给浮盈亏
r = simulate_exit(1_000_000, 1.0, 100.0, candles([1.0, 1.2, 1.5]))
show("still_open", r)
assert not r["closed"] and r["pnl_usd"] is not None

# 6. 同 K 线内同时触发止损和止盈 → 止损优先 (保守)
k = [{"ts": 1_000_000, "open": 1.0, "high": 2.5, "low": 0.5, "close": 1.0}]
r = simulate_exit(1_000_000, 1.0, 100.0, k)
show("stop_priority", r)
assert r["exit_reason"] == "hard_stop"

print("\n全部通过 ✓")
