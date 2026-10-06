#!/usr/bin/env python3
"""
纸面盈亏跟踪 v2 (2026-10-06 重写):
对 paper_trades.jsonl 中的每个候选, 用 GMGN kline(5m) 回补信号后价格,
跑确定性退出模拟 (src/risk/exit_sim.py), 得到扣费后的真实盈亏。

状态机 (logs/paper_positions.json):
  新候选 → open → 每轮拉 kline 跑模拟 → 退出触发/4h到期 → closed → 写 paper_pnl.jsonl
无效地址 (如 MOCK0) / 缺入场价 → skipped, 不再重试。

每 30 分钟由 cron `meme-paper-pnl-tracker` 运行, 幂等, 只追加不覆盖。
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from chains.gmgn_market import GmgnMarketClient, GmgnError
from risk.exit_sim import simulate_exit
from risk.pnl_stats import gate_status, format_gate

LOGDIR = os.path.expanduser("~/workspace/meme-trader/logs")
TRADES = f"{LOGDIR}/paper_trades.jsonl"
PNL = f"{LOGDIR}/paper_pnl.jsonl"
POSITIONS = f"{LOGDIR}/paper_positions.json"

ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
MAX_OPEN_HOURS = 6  # 超过 6h 仍无 kline 数据 → 标记 unknown, 不再重试


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def parse_ts(s):
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return None


def main():
    os.makedirs(LOGDIR, exist_ok=True)
    positions = {}
    if os.path.exists(POSITIONS):
        with open(POSITIONS) as f:
            positions = json.load(f)

    # 1. 新候选 → 建仓
    for tr in load_jsonl(TRADES):
        addr = (tr.get("address") or "")
        key = addr.lower()
        if key in positions:
            continue
        if not ADDR_RE.match(addr):
            positions[key] = {"status": "skipped", "reason": "invalid_address",
                              "symbol": tr.get("symbol")}
            continue
        entry_ts = parse_ts(tr.get("ts") or "")
        entry_price = tr.get("entry_price_usd")
        if not entry_ts or not entry_price or entry_price <= 0:
            positions[key] = {"status": "skipped", "reason": "no_entry_price",
                              "symbol": tr.get("symbol")}
            continue
        positions[key] = {
            "status": "open", "address": addr, "symbol": tr.get("symbol"),
            "stage": tr.get("stage"), "score": tr.get("score"),
            "entry_ts": entry_ts, "entry_price": entry_price,
            "amount_usd": tr.get("amount_usd"),
        }

    # 2. open 持仓 → kline 回补 → 退出模拟
    client = GmgnMarketClient("bsc")
    now = time.time()
    n_closed = 0
    for key, pos in positions.items():
        if pos.get("status") != "open":
            continue
        age_h = (now - pos["entry_ts"]) / 3600
        try:
            klines = client.get_kline(pos["address"], "5m",
                                      pos["entry_ts"], now)
        except Exception as e:
            print(f"  kline {pos['symbol']} failed: {e}")
            continue
        if not klines:
            if age_h > MAX_OPEN_HOURS:
                pos["status"] = "closed"
                pos["exit_reason"] = "no_data"
                pos["pnl_usd"] = None
                pos["pnl_pct"] = None
            continue
        res = simulate_exit(pos["entry_ts"], pos["entry_price"],
                            pos["amount_usd"], klines)
        pos["last_check"] = datetime.now(timezone.utc).isoformat()
        pos["unrealized_pnl_pct"] = res["pnl_pct"]
        pos["peak_pct"] = res["peak_pct"]
        if res["closed"]:
            pos["status"] = "closed"
            pos.update({k: res[k] for k in
                        ("exit_reason", "events", "pnl_usd", "pnl_pct",
                         "peak_pct", "hold_minutes", "n_candles")})
            rec = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "address": pos["address"], "symbol": pos["symbol"],
                "stage": pos.get("stage"), "score": pos.get("score"),
                "signal_ts": datetime.fromtimestamp(
                    pos["entry_ts"], timezone.utc).isoformat(),
                "entry_price": pos["entry_price"],
                "amount_usd": pos["amount_usd"],
                **{k: pos[k] for k in
                   ("exit_reason", "events", "pnl_usd", "pnl_pct",
                    "peak_pct", "hold_minutes", "n_candles")},
            }
            with open(PNL, "a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_closed += 1
            print(f"  closed {pos['symbol']} {res['exit_reason']} "
                  f"pnl={res['pnl_usd']:+.2f} USD ({res['pnl_pct']:+.1f}%)")

    with open(POSITIONS, "w") as f:
        json.dump(positions, f, ensure_ascii=False, indent=1)

    n_open = sum(1 for p in positions.values() if p.get("status") == "open")
    print(f"positions: open={n_open} closed_this_run={n_closed}")
    st = gate_status(load_jsonl(PNL))
    print(format_gate(st))


if __name__ == "__main__":
    main()
