#!/usr/bin/env python3
"""
Trenches 扫描编排器 — 策略 2/3/4 的主循环 (第1层采集 → 第4层决策)

流程 (全规则, 无 LLM):
  GMGN trenches(新创建/即将打满/已完成)
    → 初筛 filters → 一票否决 veto → 生命周期 lifecycle
    → 新闻确认器 (路径2: 币→新闻查催化剂)
    → 动量打分 scorer → 风控 limits → 纸面记录/候选输出

用法:
  python3 scripts/scan_trenches.py --stage new_creation [--limit 50] [--paper]
  无 GMGN API Key 时: --mock 用内置模拟数据跑全链路 (测试用)

输出: JSONL 候选记录 → logs/paper_trades.jsonl (纸面)
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from chains.gmgn_market import GmgnMarketClient, GmgnAuthError
from screening.filters import screen, is_dead_for_benchmark
from screening.veto import check_veto
from screening.lifecycle import classify, can_open, describe
from screening.scorer import score_early, score_live, size_for_score
from screening import filters as _f  # noqa
from risk.limits import RiskState, can_open as risk_can_open, STAGE_PARAMS

STAGE_MAP = {
    "new_creation": "new_creation",
    "near_completion": "near_completion",
    "completed": "completed_hot",
}


def mock_tokens(stage: str) -> list[dict]:
    """模拟数据 (无 API Key 时测试全链路)"""
    base = {"chain": "bsc", "buy_tax_pct": 1, "sell_tax_pct": 1,
            "call_count": 3, "watchers": 30, "age_minutes": 12,
            "dev_hold_pct": 2, "is_honeypot": False, "rug_ratio": 0.05,
            "top10_holder_pct": 15, "wash_trading": False,
            "price_change_5m_pct": 25, "price_change_1h_pct": 45,
            "holder_change_1h_pct": 18, "buys_1h": 90, "sells_1h": 25,
            "smart_money_count": 2, "volume_ratio_vs_avg": 2.0,
            "drawdown_from_high_pct": 5}
    if stage == "new_creation":
        return [{**base, "address": f"0xmock{i:040d}",
                 "symbol": f"MOCK{i}", "txns": 40 + i * 10,
                 "holders": 15 + i * 5, "market_cap_usd": 6000 + i * 2000}
                for i in range(3)]
    if stage == "near_completion":
        return [{**base, "address": f"0xmock{i:040d}",
                 "symbol": f"MOCK{i}", "txns": 150 + i * 20,
                 "holders": 30 + i * 5, "market_cap_usd": 20000 + i * 5000,
                 "call_count": 2}
                for i in range(2)]
    return [{**base, "address": f"0xmock{i:040d}",
             "symbol": f"MOCK{i}", "txns": 900 + i * 50,
             "holders": 250 + i * 20, "pool_usd": 5000,
             "market_cap_usd": 80000, "call_count": 8, "age_minutes": 60}
            for i in range(2)]


def run_stage(stage: str, limit: int, client, paper: bool,
              news_confirm_fn=None) -> list[dict]:
    gmgn_stage = stage
    if client is None:
        tokens = mock_tokens(stage)
        print(f"[mock] {stage}: {len(tokens)} tokens")
    else:
        tokens = client.get_trenches(gmgn_stage, limit)
        print(f"[gmgn] {stage}: {len(tokens)} tokens")

    screen_fn = STAGE_MAP[stage]
    candidates = []
    # 活币 M50: 剔除死币后再取中位数 (2026-10-06 起; 死币不配当估值锚)。
    # 死币判定见 filters.is_dead_for_benchmark (年龄分档: ≤10min 未达
    # "交易数>10 且 holder>5" 即判死)。
    m50 = None
    alive_tokens = [t for t in tokens if not is_dead_for_benchmark(t)]
    mcaps = sorted(t.get("market_cap_usd") for t in alive_tokens
                   if t.get("market_cap_usd"))
    if mcaps:
        m50 = mcaps[len(mcaps) // 2]
    if m50 is None:
        # 兜底: 活币为空时回退全量中位数, 避免打分无锚
        mcaps_all = sorted(t.get("market_cap_usd") for t in tokens
                           if t.get("market_cap_usd"))
        if mcaps_all:
            m50 = mcaps_all[len(mcaps_all) // 2]
    stats = {"fetched": len(tokens), "screen_pass": 0, "veto_pass": 0,
             "lifecycle_pass": 0, "risk_pass": 0,
             "dead_excluded_for_m50": len(tokens) - len(alive_tokens)}

    risk_state = RiskState()  # 纸面模式每轮独立; 实盘需持久化
    seen = set()
    scan_records = []  # 调参数据: 每个币的完整轨迹

    def handle(t: dict):
        """单个代币完整管线: 初筛→富化→否决→生命周期→新闻→打分→风控"""
        addr = t.get("address", "?")
        if addr in seen:
            return
        seen.add(addr)
        # 调参数据: 记录每个币走到哪一步、关键字段值
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": screen_fn, "address": addr, "symbol": t.get("symbol"),
            "txns": t.get("txns"), "holders": t.get("holders"),
            "call_count": t.get("call_count"),
            "total_tax_pct": t.get("total_tax_pct"),
            "watchers": t.get("watchers"),
            "market_cap_usd": t.get("market_cap_usd"),
            "age_minutes": t.get("age_minutes"),
            "reached": "fetched", "drop_reason": None,
            "score": None, "lifecycle": None,
        }
        scan_records.append(rec)
        # 1. 初筛 (阶段一: 跳过 watchers, 需 token info 富化)
        sr = screen(t, screen_fn, ignore={"watchers"})
        if not sr.passed:
            rec["reached"] = "screen1"
            rec["drop_reason"] = sr.failed
            return
        # 1b. 富化: token info 取 visiting_count(正在浏览人数)
        # mock 模式 client 为 None, 跳过富化
        if client is not None:
            try:
                info = client.get_token_info(addr)
                if info and info.get("watchers") is not None:
                    t["watchers"] = info["watchers"]
            except Exception as e:
                print(f"  enrich {addr[:10]} failed: {e}")
        sr2 = screen(t, screen_fn)  # 阶段二: 全条件 (fail-closed)
        if not sr2.passed:
            rec["reached"] = "screen2"
            rec["drop_reason"] = sr2.failed + ["unknown:" + u for u in sr2.unknown]
            rec["watchers"] = t.get("watchers")
            return
        stats["screen_pass"] += 1
        # 2. 一票否决 (新闻催化剂后置传入, 这里先用 False)
        # 安全复核: trenches 的 is_honeypot 有误报, 用 security 接口二次确认
        if client is not None:
            try:
                sec = client.get_token_security(addr)
                if sec is not None:
                    t["is_honeypot"] = sec["is_honeypot"]
                    if t.get("top10_holder_pct") is None:
                        t["top10_holder_pct"] = sec.get("top10_holder_pct")
            except Exception as e:
                print(f"  security {addr[:10]} failed: {e}")
        vr = check_veto(t, has_fresh_catalyst=False)
        if vr.vetoed:
            rec["reached"] = "veto"
            rec["drop_reason"] = vr.reasons
            return
        stats["veto_pass"] += 1
        # 3. 生命周期 (先补动量数据, trenches 没有 1h/5m 涨跌)
        if client is not None:
            try:
                if not hasattr(run_stage, "_tc"):
                    run_stage._tc = client.get_trending("1m", 200)
                client.enrich_momentum(t, run_stage._tc)
            except Exception as e:
                print(f"  momentum {addr[:10]} failed: {e}")
        st = classify(t)
        rec["lifecycle"] = st.value
        if not can_open(st):
            rec["reached"] = "lifecycle"
            rec["drop_reason"] = st.value
            return
        stats["lifecycle_pass"] += 1
        # 4. 新闻确认 (路径2)
        catalyst = 0
        if news_confirm_fn:
            try:
                nc = news_confirm_fn(t.get("symbol") or "", t.get("address"))
                catalyst = nc.get("catalyst_strength", 0)
                if nc.get("verdict") == "no_catalyst" and vr.reasons:
                    pass  # 已在 veto 处理
            except Exception as e:
                print(f"  news confirmer error for {addr[:10]}: {e}")
        # 5. 打分
        if stage == "completed":
            score, parts = score_live(t, m50, catalyst)
        else:
            score, parts = score_early(t, m50)
        rec["score"] = score
        rec["score_parts"] = parts
        if score < 60:
            rec["reached"] = "score"
            rec["drop_reason"] = f"score={score}<60"
            return
        # 6. 风控
        amount = size_for_score(score, STAGE_PARAMS[screen_fn]["per_trade"])
        ok, msg = risk_can_open(risk_state, screen_fn, amount, addr)
        if not ok:
            rec["reached"] = "risk"
            rec["drop_reason"] = msg
            return
        stats["risk_pass"] += 1
        risk_state.positions.append(
            {"stage": screen_fn, "amount_usd": amount, "address": addr})
        rec["reached"] = "candidate"
        candidates.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": screen_fn, "address": addr, "symbol": t.get("symbol"),
            "score": score, "score_parts": parts,
            "lifecycle": st.value, "catalyst_strength": catalyst,
            "amount_usd": amount, "paper": paper,
            "entry_price_usd": t.get("price_usd"),
            "entry_mcap_usd": t.get("market_cap_usd"),
        })
        print(f"  ✅ {t.get('symbol')} score={score} lifecycle={st.value} "
              f"catalyst={catalyst} amount=${amount}")

    for t in tokens:
        handle(t)

    # 0 候选兜底: 主排序没筛出时, 按交易数降序再拉一遍 (API 上限 80/类, 无更多可拉)
    # 若仍为 0, 接受市场无机会的结论, 不再重复查询
    if client is not None and stats["screen_pass"] == 0:
        print(f"[gmgn] {stage}: 主排序 0 通过, 按 swaps_24h 降序重试")
        try:
            extra = client.get_trenches(gmgn_stage, limit, sort_by="swaps_24h")
            stats["fetched"] += len(extra)
            for t in extra:
                handle(t)
        except Exception as e:
            print(f"  fallback sort failed: {e}")

    print(f"[{stage}] stats: {stats}")
    return candidates, scan_records


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="new_creation",
                    choices=["new_creation", "near_completion", "completed"])
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--paper", action="store_true", default=True)
    ap.add_argument("--mock", action="store_true",
                    help="无 API Key 时用模拟数据")
    args = ap.parse_args()

    client = None
    if not args.mock:
        client = GmgnMarketClient("bsc")
        if not client.check_auth():
            print("GMGN 未配置 (gmgn-cli config --check 失败)。")
            print("用 --mock 跑模拟, 或等用户提供 API Key 后重跑。")
            raise SystemExit(2)

    # 新闻确认器 (可选, 路径2)
    news_confirm_fn = None
    try:
        sys.path.insert(0, os.path.expanduser("~/workspace/web3/j7"))
        from news_confirmer import confirm as _nc
        news_confirm_fn = lambda sym, ca: _nc(sym, ca)  # noqa
        print("[intel] news confirmer loaded")
    except Exception as e:
        print(f"[intel] news confirmer unavailable: {e}")

    try:
        cands, records = run_stage(args.stage, args.limit, client, args.paper,
                                   news_confirm_fn)
    except GmgnAuthError as e:
        print(f"GMGN 认证失败: {e}")
        raise SystemExit(2)

    logdir = os.path.expanduser("~/workspace/meme-trader/logs")
    os.makedirs(logdir, exist_ok=True)
    # 全量扫描轨迹 (调参用: 每个币走到哪一步、为什么被筛掉)
    with open(f"{logdir}/scan_history.jsonl", "a") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"扫描轨迹 {len(records)} 条 → logs/scan_history.jsonl")

    if args.paper and cands:
        logdir = os.path.expanduser("~/workspace/meme-trader/logs")
        os.makedirs(logdir, exist_ok=True)
        with open(f"{logdir}/paper_trades.jsonl", "a") as f:
            for c in cands:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        print(f"纸面记录 {len(cands)} 条 → logs/paper_trades.jsonl")
    print(f"done. candidates: {len(cands)}")


if __name__ == "__main__":
    main()
