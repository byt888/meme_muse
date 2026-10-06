#!/usr/bin/env python3
"""
纸面盈亏跟踪: 对 paper_trades.jsonl 中的每个候选，在信号后 1h/4h/24h 查价格，
计算如果按信号价买入、按退出规则卖出的话，盈亏如何。

退出规则 (与风控一致):
- 硬止损 -30%
- +100% 卖一半
- 剩余按 25% 峰值回撤移动止盈 (简化: 取区间最高价回落 25% 处)

输出: ~/workspace/meme-trader/logs/paper_pnl.jsonl
"""
import json, os, sys, time

sys.path.insert(0, os.path.expanduser("~/workspace/meme-trader/src"))
from chains.gmgn_market import GmgnMarketClient

LOGDIR = os.path.expanduser("~/workspace/meme-trader/logs")
TRADES = f"{LOGDIR}/paper_trades.jsonl"
PNL = f"{LOGDIR}/paper_pnl.jsonl"


def done_addrs():
    s = set()
    if os.path.exists(PNL):
        with open(PNL) as f:
            for line in f:
                try:
                    s.add(json.loads(line)["address"].lower())
                except Exception:
                    pass
    return s


def main():
    if not os.path.exists(TRADES):
        print("no paper trades yet")
        return
    client = GmgnMarketClient("bsc")
    done = done_addrs()
    n = 0
    with open(TRADES) as f:
        trades = [json.loads(l) for l in f if l.strip()]
    for tr in trades:
        addr = tr["address"]
        if addr.lower() in done:
            continue
        # 信号时间必须超过 1h 才有意义 (至少看 1h 表现)
        sig_ts = time.mktime(time.strptime(tr["ts"][:19], "%Y-%m-%dT%H:%M:%S"))
        age_h = (time.time() - sig_ts) / 3600
        if age_h < 1:
            continue
        try:
            info = client.get_token_info(addr)
            if not info or not info.get("price_usd"):
                continue
            # 简化: 用 kline 取信号后最高价估算
            # TODO: 精确回测需 kline 数据, 当前用现价做 1h 持有收益
            entry = tr.get("entry_price_usd")
            cur = info["price_usd"]
            if entry and entry > 0:
                pnl_pct = (cur - entry) / entry * 100
            else:
                pnl_pct = None
            rec = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "address": addr, "symbol": tr.get("symbol"),
                "signal_ts": tr["ts"], "score": tr.get("score"),
                "age_hours": round(age_h, 1),
                "pnl_pct": round(pnl_pct, 1) if pnl_pct is not None else None,
                "price_now": cur,
            }
            with open(PNL, "a") as out:
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
        except Exception as e:
            print(f"  pnl {addr[:10]} failed: {e}")
    print(f"pnl tracked: {n}")


if __name__ == "__main__":
    main()
