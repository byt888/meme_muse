#!/usr/bin/env python3
"""晨报: 汇总过去约10小时的纸面运行状况"""
import json
import os
from collections import Counter
from datetime import datetime, timezone, timedelta

LOGDIR = os.path.expanduser("~/workspace/meme-trader/logs")

def load(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out

def main():
    since = datetime.now(timezone.utc) - timedelta(hours=10)
    cutoff = since.isoformat()[:16]
    scans = [r for r in load(LOGDIR + "/scan_history.jsonl") if r.get("ts", "") >= cutoff]
    trades = [r for r in load(LOGDIR + "/paper_trades.jsonl") if r.get("ts", "") >= cutoff]
    pnls = load(LOGDIR + "/paper_pnl.jsonl")
    print("=" * 50)
    print("Meme 纸面昨夜运行报告")
    print("统计窗口: 过去约10小时 (UTC %s 起)" % since.strftime("%m-%d %H:%M"))
    print("=" * 50)
    print("")
    print("[扫描] 共 %d 条币记录" % len(scans))
    reached = Counter(r.get("reached", "?") for r in scans)
    for k, v in reached.most_common():
        print("  %s: %d" % (k, v))
    drops = Counter()
    for r in scans:
        dr = r.get("drop_reason")
        if isinstance(dr, list):
            for d in dr:
                drops[str(d).split("=")[0].split(":")[0]] += 1
        elif dr:
            drops[str(dr)[:30]] += 1
    if drops:
        print("  主要淘汰原因 top5:")
        for k, v in drops.most_common(5):
            print("    %s: %d" % (k, v))
    print("")
    print("[候选] %d 个纸面信号" % len(trades))
    for t in trades[:10]:
        print("  %s score=%s %s..." % (t.get("symbol"), t.get("score"), t.get("address", "")[:14]))
    print("")
    scored = [p for p in pnls if p.get("pnl_pct") is not None]
    if scored:
        wins = sum(1 for p in scored if p["pnl_pct"] > 0)
        total = sum(p["pnl_pct"] for p in scored)
        print("[盈亏] %d 个已跟踪: 胜率 %d/%d, 累计 %+.1f%%" % (len(scored), wins, len(scored), total))
        need = 20 - len(scored)
        print("  距20个样本还差 %d 个" % max(need, 0))
    else:
        print("[盈亏] 暂无跟踪数据 (候选不足或未满1h)")
    print("=" * 50)

if __name__ == "__main__":
    main()
