"""
纸面盈亏统计与"稳定盈利"门禁 (无 LLM)

门禁标准 (2026-10-05 用户拍板, paper 达标 → 用户给资金做小额实盘):
1. 样本数: 已平仓 paper 候选 ≥ 20 个
2. 胜率: 盈利单占比 ≥ 55% (4h 持有口径, 退出模拟已含时间止损)
3. 盈亏比: 总盈利 / 总亏损 ≥ 1.5 (已扣 1% 手续费×2 + 滑点, 见 exit_sim)

任一条不满足 → 继续跑、继续调, 不打扰用户。
"""
GATE_MIN_TRADES = 20
GATE_MIN_WIN_RATE = 0.55
GATE_MIN_PROFIT_FACTOR = 1.5


def gate_status(records: list[dict]) -> dict:
    """records: paper_pnl.jsonl 中的已平仓记录 (需含 pnl_usd)"""
    closed = [r for r in records
              if r.get("exit_reason") not in (None, "no_data", "skipped")
              and r.get("pnl_usd") is not None]
    n = len(closed)
    wins = [r for r in closed if r["pnl_usd"] > 0]
    gross_profit = sum(r["pnl_usd"] for r in wins)
    gross_loss = abs(sum(r["pnl_usd"] for r in closed if r["pnl_usd"] < 0))
    win_rate = len(wins) / n if n else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (
        float("inf") if gross_profit > 0 else 0.0)
    net = sum(r["pnl_usd"] for r in closed)
    checks = {
        "样本数≥20": n >= GATE_MIN_TRADES,
        "胜率≥55%": win_rate >= GATE_MIN_WIN_RATE,
        "盈亏比≥1.5": profit_factor >= GATE_MIN_PROFIT_FACTOR,
    }
    return {
        "n_closed": n, "n_wins": len(wins),
        "win_rate": round(win_rate * 100, 1),
        "gross_profit_usd": round(gross_profit, 2),
        "gross_loss_usd": round(gross_loss, 2),
        "profit_factor": round(profit_factor, 2)
        if profit_factor != float("inf") else "inf",
        "net_pnl_usd": round(net, 2),
        "checks": checks,
        "passed": all(checks.values()),
    }


def format_gate(st: dict) -> str:
    lines = [
        "[纸面门禁] 已平仓 %d 笔 | 胜 %d | 胜率 %.1f%% | 盈亏比 %s | 净盈亏 %+.2f USD"
        % (st["n_closed"], st["n_wins"], st["win_rate"],
           st["profit_factor"], st["net_pnl_usd"]),
    ]
    for name, ok in st["checks"].items():
        lines.append("  %s %s" % ("✅" if ok else "⬜", name))
    if st["passed"]:
        lines.append("  🎯 三条全过 → 可提醒用户注资小额实盘")
    else:
        lines.append("  继续跑纸面，不打扰用户")
    return "\n".join(lines)
