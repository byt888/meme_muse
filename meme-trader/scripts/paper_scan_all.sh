#!/bin/bash
# 纸面扫描: 三阶段全跑, 每 5 分钟一次 (cron 调用)
# 只记录、不交易。GMGN_ALLOW_AUTOMATED_TRADES 保持关闭。
export PATH="$HOME/workspace/.npm-global/bin:$PATH"
cd "$HOME/workspace/meme-trader" || exit 1
PY="$HOME/workspace/web3/venv/bin/python"
TS=$(date -u +%Y%m%dT%H%M%SZ)
RUNLOG="$HOME/workspace/meme-trader/logs/paper_scan_runlog.txt"
# runlog 由脚本自己追加 (2026-10-06 修复: 之前靠 worker 手工追加, 06:34Z 后断更)
{
for stage in new_creation near_completion completed; do
  echo "[$TS] === $stage ==="
  timeout 280 $PY scripts/scan_trenches.py --stage "$stage" --limit 80 --paper 2>&1 | tail -3
done
echo "[$TS] done"
} 2>&1 | tee -a "$RUNLOG"
