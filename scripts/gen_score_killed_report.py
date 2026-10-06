#!/usr/bin/env python3
"""
打分淘汰报告生成器 (2026-10-06 重写):
读 logs/scan_history.jsonl → 取 reached=="score" 的记录 → 按地址去重(取最新)
→ 生成 score_killed_report.html。

要求 (用户 2026-10-06):
- 时间全部 UTC+8
- 打分维度用中文 (英文原名附注)
- CA 完整显示
"""
import json
import os
from datetime import datetime, timezone, timedelta

LOGDIR = os.path.expanduser("~/workspace/meme-trader/logs")
HISTORY = f"{LOGDIR}/scan_history.jsonl"
OUT = os.path.expanduser("~/workspace/meme-trader/score_killed_report.html")

UTC8 = timezone(timedelta(hours=8))

DIM_CN = {
    "curve_speed": "价格动量", "net_buy": "净买入",
    "dev_behavior": "开发者行为", "smart_money": "聪明钱",
    "valuation": "相对估值", "call_heat": "喊单热度",
    "price_momentum": "价格动量", "net_inflow": "净流入",
    "rel_valuation": "相对估值", "holder_growth": "持币增长",
    "turnover_liq": "换手流动性", "narrative": "新闻催化",
}
STAGE_CN = {"new_creation": "新创建", "near_completion": "即将打满",
            "completed_hot": "已开盘"}
LIFE_CN = {"uptrend": "上涨趋势", "second_wave": "第二波",
           "topping": "滞涨顶部", "death_spiral": "死亡螺旋",
           "stabilizing": "超跌企稳"}


def fmt_ts(s):
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC8)
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return "?"


def fmt_age(v):
    return "?" if v is None else "%d分钟" % round(v)


def money(v):
    if v is None:
        return "-"
    return "$%s" % f"{v:,.0f}"


def main():
    recs = []
    if os.path.exists(HISTORY):
        with open(HISTORY) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("reached") == "score":
                    recs.append(r)
    # 按地址去重, 取最新一条
    latest = {}
    for r in recs:
        a = (r.get("address") or "").lower()
        if a not in latest or r.get("ts", "") > latest[a].get("ts", ""):
            latest[a] = r
    rows = sorted(latest.values(), key=lambda r: r.get("score") or 0,
                  reverse=True)

    # 统计: 哪个维度最拖后腿
    dim_sum, dim_n = {}, {}
    for r in rows:
        for k, v in (r.get("score_parts") or {}).items():
            dim_sum[k] = dim_sum.get(k, 0) + v
            dim_n[k] = dim_n.get(k, 0) + 1
    dim_avg = sorted(((k, dim_sum[k] / dim_n[k]) for k in dim_sum),
                     key=lambda x: x[1])

    now8 = datetime.now(UTC8).strftime("%m-%d %H:%M")
    head = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
__TITLE__
<style>
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:16px}
h1{font-size:20px} .sub{color:#8b949e;font-size:13px;margin-bottom:16px}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{border:1px solid #30363d;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#161b22;position:sticky;top:0}
tr:nth-child(even){background:#0d111744}
.mono{font-family:monospace;font-size:10px;word-break:break-all}
.score{font-weight:bold;color:#f0883e;font-size:14px}
.parts{font-size:11px;color:#8b949e;white-space:nowrap}
a{color:#58a6ff;text-decoration:none}
.note{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:12px;margin-bottom:16px;font-size:13px}
.bottleneck{color:#f0883e}
</style></head><body>""".replace(
        "__TITLE__", f"<title>打分淘汰代币复盘 ({len(rows)}个)</title>")
    html = [head]
    html.append(f"<h1>打分淘汰代币复盘 ({len(rows)} 个)</h1>")
    html.append(f"<div class='sub'>生成时间(北京时间): {now8} ｜ "
                "这些代币通过了初筛→否决→生命周期，但打分 &lt;60 被淘汰。点击币名跳转 GMGN 查看详情。</div>")
    if dim_avg:
        bott = "、".join(
            f"<span class='bottleneck'>{DIM_CN.get(k, k)}({k})</span> 平均{v:.0f}分"
            for k, v in dim_avg[:3])
        html.append(f"<div class='note'><b>最拖后腿的三个维度：</b>{bott}<br>"
                    "<b>复盘指引：</b>在 GMGN 上查看每个币在\"通过筛选时间\"之后 1-4 小时的走势——"
                    "如果涨了，说明打分太严（漏掉了好币）；如果跌了或横盘，说明打分正确。</div>")
    html.append("""<table><tr>
<th>#</th><th>币名</th><th>合约地址(CA)</th><th>阶段</th><th>通过筛选时间<br>(北京时间)</th><th>币龄</th>
<th>交易数</th><th>持有人</th><th>喊单</th><th>税率</th><th>浏览</th><th>市值</th>
<th>生命周期</th><th>得分</th><th>打分明细</th>
</tr>""")
    for i, r in enumerate(rows, 1):
        addr = r.get("address") or ""
        sym = r.get("symbol") or "?"
        parts = r.get("score_parts") or {}
        parts_html = "<br>".join(
            f"{DIM_CN.get(k, k)}({k}): {v:.1f}" for k, v in parts.items())
        tax = r.get("total_tax_pct")
        html.append("<tr>")
        html.append(f"<td>{i}</td>")
        html.append(f"<td><a href='https://gmgn.ai/bsc/token/{addr}' target='_blank'><b>{sym}</b></a></td>")
        html.append(f"<td class='mono'>{addr}</td>")
        html.append(f"<td>{STAGE_CN.get(r.get('stage'), r.get('stage'))}</td>")
        html.append(f"<td>{fmt_ts(r.get('ts') or '')}</td>")
        html.append(f"<td>{fmt_age(r.get('age_minutes'))}</td>")
        html.append(f"<td>{r.get('txns') or '-'}</td>")
        html.append(f"<td>{r.get('holders') or '-'}</td>")
        html.append(f"<td>{r.get('call_count') or '-'}</td>")
        html.append(f"<td>{f'{tax:.1f}%' if tax is not None else '-'}</td>")
        html.append(f"<td>{r.get('watchers') if r.get('watchers') is not None else '-'}</td>")
        html.append(f"<td>{money(r.get('market_cap_usd'))}</td>")
        html.append(f"<td>{LIFE_CN.get(r.get('lifecycle'), r.get('lifecycle'))}</td>")
        html.append(f"<td class='score'>{r.get('score')}</td>")
        html.append(f"<td class='parts'>{parts_html}</td>")
        html.append("</tr>")
    html.append("</table></body></html>")
    with open(OUT, "w") as f:
        f.write("\n".join(html))
    print(f"报告已生成: {OUT} ({len(rows)} 个)")


if __name__ == "__main__":
    main()
