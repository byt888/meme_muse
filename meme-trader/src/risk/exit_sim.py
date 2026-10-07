"""
纸面退出模拟 — 确定性退出规则回测 (无 LLM)

退出规则 (参数见 risk/limits.py, 与实盘蓝图一致):
- 硬止损 -30%: 全平
- +100%: 卖 50% (回本金)
- 剩余仓位: 25% 峰值回撤移动止盈
- +400%: 再卖剩余一半
- 月球仓: 40% 回撤移动止盈
- 时间止损: 4h 到期市价全平 (胜率按 4h 口径算, 用户 2026-10-05 拍板)

费用假设 (本文件常量, 待实盘验证):
- GMGN 每笔 swap 收 1%
- 滑点假设 2%/笔
即每笔成交按 3% 成本计。偏保守, 宁可低估收益。

触发判定用 K 线 high/low (保守: 同一根 K 线内先判止损再判止盈),
成交按触发价计, 不按收盘价。
"""
from .limits import (HARD_STOP_PCT, TAKE_PROFIT_1_PCT, TAKE_PROFIT_2_PCT,
                     TRAILING_DRAWDOWN, MOON_DRAWDOWN, TIME_STOP_HOURS)

FEE_PCT = 1.0        # GMGN 每笔 swap 手续费
SLIPPAGE_PCT = 2.0   # 滑点假设 (待实盘验证)
COST_PER_SIDE = (FEE_PCT + SLIPPAGE_PCT) / 100  # 0.03


def _sell(state, frac, px, ts, reason):
    """按比例卖出, 记录事件"""
    qty_sold = state["qty_total"] * frac
    proceeds = qty_sold * px * (1 - COST_PER_SIDE)
    state["proceeds"] += proceeds
    state["remaining"] -= frac
    state["events"].append({
        "ts": ts, "reason": reason,
        "price": px, "qty_pct": round(frac * 100, 1),
        "proceeds_usd": round(proceeds, 4),
    })


def simulate_exit(entry_ts: float, entry_price: float, amount_usd: float,
                  klines: list[dict]) -> dict:
    """模拟一笔纸面持仓的完整退出过程。

    klines: [{"ts": 秒, "open","high","low","close": float}] 按时间升序
    返回: {
      closed: bool,          # 是否已完全退出
      exit_reason: str|None, # hard_stop/tp_trailing/time_stop/no_data...
      events: [...],         # 每次卖出明细
      pnl_usd / pnl_pct,     # 已实现 (closed) 或未实现 (open)
      peak_pct,              # 相对入场价的最高涨幅 %
      hold_minutes,          # 持有时长 (到退出或到最后一根 K 线)
      n_candles,
    }
    """
    klines = sorted([k for k in klines if k["ts"] >= entry_ts - 1],
                    key=lambda k: k["ts"])
    if not klines or entry_price <= 0 or amount_usd <= 0:
        return {"closed": False, "exit_reason": "no_data", "events": [],
                "pnl_usd": None, "pnl_pct": None, "peak_pct": 0.0,
                "hold_minutes": 0.0, "n_candles": 0}

    eff_entry = entry_price * (1 + COST_PER_SIDE)  # 买入成本价
    state = {"qty_total": amount_usd / eff_entry, "remaining": 1.0,
             "proceeds": 0.0, "events": []}
    peak = entry_price
    tp1_done = tp2_done = False
    stop_px = entry_price * (1 + HARD_STOP_PCT / 100)
    tp1_px = entry_price * (1 + TAKE_PROFIT_1_PCT / 100)
    tp2_px = entry_price * (1 + TAKE_PROFIT_2_PCT / 100)
    deadline = entry_ts + TIME_STOP_HOURS * 3600
    exit_reason = None
    last_ts = klines[0]["ts"]

    for k in klines:
        t, h, l, c = k["ts"], k["high"], k["low"], k["close"]
        last_ts = t
        if state["remaining"] <= 0:
            break
        # 1. 硬止损 (同 K 线内优先于止盈, 保守)
        if l <= stop_px:
            _sell(state, state["remaining"], stop_px, t, "hard_stop")
            exit_reason = "hard_stop"
            break
        # 2. TP1 +100% 卖一半
        if not tp1_done and h >= tp1_px:
            _sell(state, state["remaining"] * 0.5, tp1_px, t, "tp1_+100%")
            tp1_done = True
        # 3. TP2 +400% 再卖剩余一半
        if tp1_done and not tp2_done and h >= tp2_px:
            _sell(state, state["remaining"] * 0.5, tp2_px, t, "tp2_+400%")
            tp2_done = True
        # 4. 移动止盈 (TP1 后才激活; 月球仓用 40%)
        if tp1_done and state["remaining"] > 0:
            thr = (MOON_DRAWDOWN if tp2_done else TRAILING_DRAWDOWN) / 100
            if peak > 0 and (peak - l) / peak >= thr:
                px = peak * (1 - thr)
                _sell(state, state["remaining"], px, t,
                      "moon_trailing" if tp2_done else "trailing")
                exit_reason = "moon_trailing" if tp2_done else "trailing"
                break
        # 5. 时间止损 4h
        if t >= deadline:
            _sell(state, state["remaining"], c, t, "time_stop_4h")
            exit_reason = "time_stop_4h"
            break
        peak = max(peak, h)

    closed = state["remaining"] <= 1e-9
    if closed:
        pnl_usd = state["proceeds"] - amount_usd
    else:
        # 未平仓: 按最后一根 K 线收盘价估算浮盈亏
        last_close = klines[-1]["close"]
        floating = state["qty_total"] * state["remaining"] * last_close * (1 - COST_PER_SIDE)
        pnl_usd = state["proceeds"] + floating - amount_usd
    return {
        "closed": closed,
        "exit_reason": exit_reason,
        "events": state["events"],
        "pnl_usd": round(pnl_usd, 4),
        "pnl_pct": round(pnl_usd / amount_usd * 100, 2),
        "peak_pct": round((peak - entry_price) / entry_price * 100, 1),
        "hold_minutes": round((last_ts - entry_ts) / 60, 1),
        "n_candles": len(klines),
        "remaining_pct": round(state["remaining"] * 100, 1),
    }
