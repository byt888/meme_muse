#!/bin/bash
# SOL 纸面扫描: 三阶段全跑, 每 5 分钟一次 (cron 调用)
# 只记录、不交易。GMGN_ALLOW_AUTOMATED_TRADES 保持关闭。
#
# 注意 (2026-10-07): SOL 处于 bootstrap 数据收集期, 阈值为临时值
# (照抄 BSC, 见 src/screening/filters.py THRESHOLDS["sol"])。
# 数据写入 logs/sol_*.jsonl (与 BSC 独立), 候选不触发用户告警,
# 只用于攒分布数据 (1-2 周后按数据定正式阈值)。
export PATH="$HOME/workspace/.npm-global/bin:$PATH"
cd "$HOME/workspace/meme-trader" || exit 1
PY="$HOME/workspace/web3/venv/bin/python"
TS=$(date -u +%Y%m%dT%H%M%SZ)
RUNLOG="$HOME/workspace/meme-trader/logs/sol_scan_runlog.txt"
# runlog 由脚本自己追加 (沿用 2026-10-06 BSC 侧的修复)
{
for stage in new_creation near_completion completed; do
  echo "[$TS] === $stage ==="
  timeout 280 $PY scripts/scan_trenches.py --chain sol --stage "$stage" --limit 80 --paper 2>&1 | tail -3
done
echo "[$TS] done"
} 2>&1 | tee -a "$RUNLOG"
