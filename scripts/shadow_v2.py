#!/usr/bin/env python3
"""
影子对比 v2 (2026-10-06): 旧逻辑 vs 新逻辑, 只读不写生产数据。

对比维度 (每个走到打分的币):
  A = 旧打分(旧 M50=全量中位数, 旧估值 ratio>3 归零, net_buy 恒 0)
  B = 旧打分函数 + 新 M50(活币中位数)      → 隔离"M50 清洗"的效果
  C = 新打分 v2(新 M50 + 年龄/速度估值 + 字段修复) → 最终效果

管线: 初筛阶段一 → token info 富化浏览人数 → 初筛阶段二
      → trending 富化动量 → 打分 A/B/C
(跳过一票否决/生命周期/新闻确认: 它们不影响分项分数)

输出: logs/shadow_v2_<时间>.json + 终端汇总表
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from chains.gmgn_market import GmgnMarketClient, GmgnAuthError
from screening.filters import screen, is_dead_for_benchmark
from screening.scorer import (score_early, score_live,
                              score_early_v2, score_live_v2)

STAGE_MAP = {"near_completion": "near_completion", "completed": "completed_hot"}


def median(vals):
    vals = sorted(vals)
    return vals[len(vals) // 2] if vals else None


def main():
    client = GmgnMarketClient("bsc")
    if not client.check_auth():
        print("GMGN 未配置, 退出")
        raise SystemExit(2)

    out = {"ts": datetime.now(timezone.utc).isoformat(), "stages": {}}
    for stage in ["near_completion", "completed"]:
        screen_fn = STAGE_MAP[stage]
        tokens = client.get_trenches(stage, 80)
        mcaps_all = [t["market_cap_usd"] for t in tokens if t.get("market_cap_usd")]
        m50_old = median(mcaps_all)
        alive = [t for t in tokens if not is_dead_for_benchmark(t)]
        m50_new = median([t["market_cap_usd"] for t in alive
                          if t.get("market_cap_usd")]) or m50_old

        trending_cache = client.get_trending("1m", 200)
        rows = []
        n_s1 = n_s2 = 0
        for t in tokens:
            sr = screen(t, screen_fn, ignore={"watchers"})
            if not sr.passed:
                continue
            n_s1 += 1
            try:
                info = client.get_token_info(t["address"])
                if info and info.get("watchers") is not None:
                    t["watchers"] = info["watchers"]
            except Exception:
                pass
            sr2 = screen(t, screen_fn)
            if not sr2.passed:
                continue
            n_s2 += 1
            try:
                client.enrich_momentum(t, trending_cache)
            except Exception:
                pass
            if stage == "completed":
                a, pa = score_live(t, m50_old, 0)
                b, _ = score_live(t, m50_new, 0)
                c, pc = score_live_v2(t, m50_new, 0)
            else:
                a, pa = score_early(t, m50_old)
                b, _ = score_early(t, m50_new)
                c, pc = score_early_v2(t, m50_new)
            rows.append({
                "symbol": t.get("symbol"), "address": t.get("address"),
                "age_minutes": round(t.get("age_minutes") or -1, 1),
                "market_cap_usd": t.get("market_cap_usd"),
                "txns": t.get("txns"), "holders": t.get("holders"),
                "ratio_old": round(t["market_cap_usd"] / m50_old, 2) if m50_old and t.get("market_cap_usd") else None,
                "ratio_new": round(t["market_cap_usd"] / m50_new, 2) if m50_new and t.get("market_cap_usd") else None,
                "score_A_old": a, "score_B_m50only": b, "score_C_new": c,
                "parts_A": pa, "parts_C": pc,
                "rescued": a < 60 <= c,       # 旧判死刑, 新救回
                "regressed": a >= 60 > c,     # 旧能过, 新挂掉 (回归检查)
            })
        rows.sort(key=lambda r: r["score_C_new"], reverse=True)
        out["stages"][stage] = {
            "fetched": len(tokens),
            "m50_old": m50_old, "m50_new": m50_new,
            "dead_excluded": len(tokens) - len(alive),
            "screen1_pass": n_s1, "screen2_pass": n_s2,
            "scored": len(rows),
            "rescued": sum(1 for r in rows if r["rescued"]),
            "regressed": sum(1 for r in rows if r["regressed"]),
            "rows": rows,
        }

    logdir = os.path.expanduser("~/workspace/meme-trader/logs")
    os.makedirs(logdir, exist_ok=True)
    fn = f"{logdir}/shadow_v2_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json"
    with open(fn, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"影子结果 → {fn}\n")

    for stage, d in out["stages"].items():
        print(f"===== {stage} =====")
        print(f"拉取 {d['fetched']} | 死币剔除 {d['dead_excluded']} | "
              f"M50: {d['m50_old']} → {d['m50_new']} | 初筛通过 {d['screen2_pass']} | 打分 {d['scored']}")
        print(f"救回(rescued): {d['rescued']} | 回归(regressed): {d['regressed']}")
        for r in d["rows"][:15]:
            flag = " 🆘救回" if r["rescued"] else (" ⛔回归" if r["regressed"] else "")
            print(f"  {r['symbol']} mcap=${r['market_cap_usd']} age={r['age_minutes']}min "
                  f"ratio {r['ratio_old']}→{r['ratio_new']} "
                  f"A={r['score_A_old']} B={r['score_B_m50only']} C={r['score_C_new']}{flag}")
        print()


if __name__ == "__main__":
    main()
