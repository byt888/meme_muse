#!/usr/bin/env python3
"""
SOL 分布统计 — bootstrap 数据收集期的调参依据。

读 logs/sol_scan_history.jsonl, 按阶段输出关键字段的分位数分布,
用于 1-2 周后制定 SOL 正式初筛阈值 (替代照抄 BSC 的临时值)。

用法: python3 scripts/sol_dist_stats.py [--days 7]
输出: 每个阶段 txns/holders/call_count/watchers/market_cap/age 的
      p10/p25/p50/p75/p90, 以及各淘汰原因计数。
"""
import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

HISTORY = os.path.expanduser("~/workspace/meme-trader/logs/sol_scan_history.jsonl")
FIELDS = ["txns", "holders", "call_count", "watchers", "market_cap_usd",
          "age_minutes"]


def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    i = min(int(len(sorted_vals) * q / 100), len(sorted_vals) - 1)
    return sorted_vals[i]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=14,
                    help="统计最近 N 天 (默认 14)")
    args = ap.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    by_stage = defaultdict(lambda: defaultdict(list))
    drop_counter = Counter()
    n_total = 0

    if not os.path.exists(HISTORY):
        print(f"无数据: {HISTORY} 不存在, 先跑 paper_scan_sol.sh 攒数据")
        return
    with open(HISTORY) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            try:
                ts = datetime.fromisoformat(
                    r["ts"].replace("Z", "+00:00"))
            except Exception:
                continue
            if ts < cutoff:
                continue
            n_total += 1
            st = r.get("stage", "?")
            for fld in FIELDS:
                v = r.get(fld)
                if isinstance(v, (int, float)):
                    by_stage[st][fld].append(v)
            dr = r.get("drop_reason")
            if isinstance(dr, list):
                for d in dr:
                    drop_counter[d.split("=")[0].split(":")[0]] += 1
            elif dr:
                drop_counter[str(dr)[:40]] += 1

    print(f"=== SOL 分布统计 (最近 {args.days} 天, {n_total} 条记录) ===")
    for st in ["new_creation", "near_completion", "completed_hot"]:
        d = by_stage.get(st)
        if not d:
            print(f"\n[{st}] 无数据")
            continue
        print(f"\n[{st}] {sum(len(v) for v in d.values()) // max(len(d), 1)} 条/字段")
        for fld in FIELDS:
            vals = sorted(d.get(fld, []))
            if not vals:
                print(f"  {fld}: 无数据")
                continue
            print(f"  {fld}: n={len(vals)} "
                  f"p10={pct(vals,10):.1f} p25={pct(vals,25):.1f} "
                  f"p50={pct(vals,50):.1f} p75={pct(vals,75):.1f} "
                  f"p90={pct(vals,90):.1f}")
    print("\n[淘汰原因 top10]")
    for k, v in drop_counter.most_common(10):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
