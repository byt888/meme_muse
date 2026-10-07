# 策略逻辑变更日志

> 按时间倒序。每条记录：改了什么 / 为什么改 / 解决了什么问题 / 数据依据。
> 当前策略逻辑见 `STRATEGY.md`，决策过程见 `OPTIMIZATION_LOG.md`。
> 时间均为 UTC+8。

---

## 2026-10-07 — SOL Phase B 启动: 纸面扫描并行＋bootstrap 数据收集

**改了什么**:
1. `src/screening/filters.py`: 初筛阈值重构为 `THRESHOLDS[chain][stage]` 查表,
   `screen()` 新增 `chain` 参数 (默认 bsc, 旧调用行为不变, 11 个单元测试全过)。
   SOL 当前为 bootstrap 临时值 (照抄 BSC), 仅用于数据收集。
2. `scripts/scan_trenches.py`: 新增 `--chain bsc|sol`;
   sol 走 `SolAdapter`, 日志独立 (`logs/sol_scan_history.jsonl` /
   `logs/sol_paper_trades.jsonl`, bsc 沿用历史文件名);
   trending 缓存按链隔离; 候选记录新增 `chain` 字段;
   富化后回填 `rec["watchers"]` (调参数据完整性)。
3. `src/chains/sol.py`: 补 `check_auth` / `enrich_momentum` (管线需要);
   `get_trenches` 支持 `sort_by` 透传 (0 候选兜底逻辑)。
4. 新增 `scripts/paper_scan_sol.sh` (每 5 分钟三阶段, runlog 自写)。
5. 新增 `scripts/sol_dist_stats.py`: 按阶段输出 txns/holders/call/watchers/
   mcap/age 的 p10-p90 分布 ＋ 淘汰原因 top10 (转正定阈值的依据)。
6. 新增 `config/sol_thresholds.yaml`: 阈值文档 (当前 BOOTSTRAP, 含转正计划)。
7. 定时任务 `meme-sol-paper-scan` (每 5 分钟, goal-owned):
   bootstrap 期**静默**, 不因 score≥75 告警 (阈值未验证), 只攒数据;
   连续 3 次失败才通知。

**首轮实测** (40 条): SOL new_creation txns p50=9 / holders p50=3 /
喊单 p50=0 —— BSC 阈值在 SOL 上偏严 (符合预期, 数据收集期可接受);
near_completion txns p50=796 / holders p50=131 —— txns/holders 阈值偏松,
喊单 p50=0 偏严。转正时按完整分布重定, 需用户确认。

**没做的**: SOL 正式阈值 (等 1-2 周数据)；SOL 纸面盈亏跟踪 (候选攒够后建)；
SOL 独立纸面门禁。

**背景**: 用户拍板多链总体规划 (SOL/BSC/ETH/Robinhood), SOL 为下一个。
BSC 纸面不停, 两条链并行不互斥。

**实测结论** (gmgn-cli --chain sol):
- trenches/token info/security/kline/trending/search 六个接口全通,
  字段结构与 BSC 基本一致, 可复用 `GmgnMarketClient(chain="sol")`。
- SOL trenches 多给 `is_wash_trading` / `rug_ratio` (BSC 没有);
  security 多给 `renounced_mint` / `renounced_freeze_account` / `burn_ratio` /
  `lock_summary.is_locked`。
- 差异: 地址 base58; trenches 无 honeypot 字段 (记 unknown, 否决以 security 为准);
  SOL 代币多为 0 税, BSC 的"总税率≤4%"在 SOL 上恒过 → **阈值不可照抄, 必须独立定**;
  发射平台 Pump.fun 占主导 (~80%)。
- 技术坑: token info 的 price 可能是 dict; security 的 is_honeypot 常为 null。

**改了什么**:
- 新增 `src/chains/sol.py`: `SolAdapter` (委托 GmgnMarketClient + SOL 字段修正),
  冒烟测试 22 个统一字段全绿 (除 trenches is_honeypot 本来就没有)。
- 新增 `src/chains/CAPABILITY_SOL.md`: 能力边界手册。
- GOAL.md 更新多链总体规划 (各链定位/三阶段上线流程/诚实说明:
  Robinhood 无 meme 管线不硬套; ETH 主网 gas 贵, 现实落点是 Base)。

**没做的** (Phase B, 待用户确认): SOL 纸面扫描脚本、独立阈值配置、
1–2 周数据跑分布、SOL 独立纸面门禁。策略层零改动。

**改了什么：**
1. 新增 `scripts/gen_score_killed_report.py`：打分淘汰报告一键生成。
   时间全部 UTC+8（北京时间）；打分维度中英对照（价格动量/净买入/开发者行为/
   聪明钱/相对估值/喊单热度…）；CA 完整显示；阶段/生命周期中文化；
   顶部增加"最拖后腿的三个维度"瓶颈分析。报告 HTML 为生成物，不进版本库。
2. `scan_trenches.py`：扫描轨迹多记 `age_minutes`（报告新增"币龄"列）。
3. `paper_scan_all.sh` 自己追加 runlog（修复之前靠 worker 手工追加、
   06:34Z 后断更的问题；真正的告警链未受影响）。

**为什么改：** 用户 2026-10-06 早上要求报告中文化＋UTC+8＋完整 CA；
瓶颈分析用于复盘"哪个维度最拖后腿"。

---

## 2026-10-06 — Paper PnL 真实退出模拟上线

**改了什么：**
1. 新增 `src/risk/exit_sim.py`：确定性退出模拟引擎（无 LLM）。规则与风控蓝图一致 ——
   硬止损 -30% 全平 / +100% 卖一半 / 剩余 25% 峰值回撤移动止盈 /
   +400% 再卖剩余一半 / 月球仓 40% 移动止盈 / 4h 时间止损。
   触发判定用 kline high/low（同 K 线内止损优先，保守），成交按触发价；
   费用按每笔 3%（GMGN 1% 手续费＋2% 滑点假设，偏保守）。
2. `chains/gmgn_market.py` 新增 `get_kline()`（5m/1m 等分辨率，时间范围回补）。
3. `risk/limits.py` 新增 `TIME_STOP_HOURS = 4`（把已拍板的"胜率按 4h 口径"代码化）。
4. 重写 `scripts/paper_pnl_tracker.py`：持仓状态机（open→closed），每 30 分钟用
   kline 回补信号后价格、跑退出模拟，平仓后写 `paper_pnl.jsonl`（完整事件明细＋
   扣费后盈亏）；无效地址/缺入场价标记 skipped。
5. 新增 `src/risk/pnl_stats.py`："稳定盈利"门禁三标准自动判定
   （样本≥20 / 胜率≥55% / 盈亏比≥1.5），晨报直接引用。
6. 新增 `tests/test_exit_sim.py`：6 个合成场景测试。

**为什么改：**
旧跟踪器只在信号 1 小时后查一次现价，没有止损、没有分批止盈、没有手续费滑点 ——
"稳定盈利"三标准根本验证不了，而这是用户注资实盘的唯一前提。没有裁判，优化没有意义。

**解决了什么问题：**
- 每一笔纸面候选现在都有"如果真按规则交易，扣完费到底赚多少"的答案。
- 门禁三标准可自动判定；达标时小乐会主动提醒用户注资，不达标继续静默跑。

**数据依据：**
- 6 个合成场景全过：硬止损 -34.1%（-30%＋费用）/ TP1+移动止盈 +82.5% /
  TP1+TP2+月球仓 +196.7% / 横盘 4h 时间止损 -5.8%（纯费用）/
  数据中途结束保持 open / 同 K 线止损优先。
- 真实 kline 端到端验证：bibi（0x7906…）100 根 5m K 线，信号后 8h，
  4h 时间止损平仓 ＋$0.13（+2.3%），事件明细完整；测试数据已清理。

**回滚：** 旧版 tracker 逻辑简单，无需保留；`paper_pnl.jsonl` 格式向后兼容
（保留 `pnl_pct` 字段）。Git 可回滚。

---

## 2026-10-06 — 打分 v2 上线（死币清洗 M50＋年龄/速度双维度估值＋字段修复）

**改了什么（3 件）：**

1. **活币 M50**（`filters.is_dead_for_benchmark`＋`scan_trenches.py`）：
   计算相对估值锚 M50 时，先剔除死币。死币判定按年龄分档 ——
   年龄 ≤10 分钟且 10 分钟内达不到"交易数>10 且 holder>5"判死；
   年龄更大用宽松兜底（24h 交易<10 或 holder<5）。
2. **相对估值 v2**（`scorer._valuation_v2`）：年轻＋强动量（早盘：≤30min 且
   5 分钟涨幅≥30%；已开盘：≤60min 且 1 小时涨幅≥50%）的币，估值改用平滑缓衰
   曲线（比值 1→1.0、3→0.83、7→0.5、13→0），不再"比值>3 直接 0 分"；
   年老或无动量的币保持旧逻辑（>3 倍判追高，0 分）。
3. **字段修复**（`scorer.py`）：`net_buy` 旧代码读 `buys_1h/sells_1h`，
   但数据映射只提供 `buys_24h/sells_24h`，导致 20% 权重在生产中**恒为 0**；
   v2 优先用 1h、缺失回退 24h。已开盘 `net_inflow`/`turnover_liq`
   用 24h 买卖笔数不平衡度 / 24h 成交额÷池子做代理（此前合计 50% 权重恒为 0）。

**为什么改：**
用户 2026-10-06 指出两点：①"24h 交易<10 或 holder<5"的死币线对
near_completion 阶段太宽松 —— 10 分钟没起量的币已经毫无价值；
② 真金狗市值爆发极快（几十 K→几百 K→几 M 在数小时内），离散扫描有盲区，
首次被看到时市值可能已是中位数十几倍，静态">3×M50 归零"会系统性错杀金狗。

**解决了什么问题：**
- M50 不再被 55% 的死币（市值<$5K）拉低，估值锚反映"活币"真实水平。
- 爆发型金狗不再因"涨得快"被惩罚：合成测试（14 分钟币龄、市值 300K、
  买盘碾压）旧打分 58.8 被淘汰 → v2 打分 78.8 通过；年老滞涨的追高币
  （180 分钟、比值 50、无动量）v2 仍只有 54.8，不过线 —— 该拦的照样拦。
- `net_buy` 修复让早盘打分恢复 20% 权重的真实信号。

**数据依据：**
- 2026-10-06 实测：22,293 条扫描记录市值中位数 $4,635，55.3% 市值<$5K，
  13 条 `valuation=0` 的淘汰记录市值 $14K–$31K（中位数 $25,402）。
- 影子对比（`scripts/shadow_v2.py`，真实数据）：near_completion 拉取 60，
  死币剔除 7，M50 $5,465→$5,742；回归数 0（旧能过的，新全部能过）。
- 合成场景验证：金狗极端场景被救回，追高陷阱不被救回（见 STRATEGY.md 第 8 节）。

**回滚：** 旧函数保留为 `score_early_legacy`/`score_live_legacy`；
M50 改回全量只需删掉 `alive_tokens` 过滤。Git 提交可整体回滚。

---

## 2026-10-05 — 纸面扫描提速＋晨报

- 扫描从每 15 分钟改为每 5 分钟（cron `meme-paper-scan`），加快数据积累。
- 新增每日 07:00（UTC+8）晨报（cron `meme-morning-report`）。
- 新增纸面盈亏跟踪（cron `meme-paper-pnl-tracker`，每 30 分钟）。
- 原因：行情冷清、候选稀少，需要更快积累样本验证策略。

## 2026-10-05 — trenches 数据口径对账

- 确认 trenches API 是**热门列表**不是全量注册表；不再追求与前端名单 1:1 对齐，
  改为"API 筛出的币能在前端反向验证"。
- 确认 `callout_count`＝前端小喇叭喊单数（用 ZACHXBT 对账：API=9=前端 9）。
- 确认 trenches 的 `is_honeypot` 有误报（AGENTIAL/DOODROP），否决前必须用
  security 接口二次确认。
- 原因：用户要求筛选口径对账；解决"API 与前端名单对不上"的困惑。

## 2026-10-05 — 删除发射平台打分

- 打分中去掉 launchpad（fourmeme/flap）平台加分项。
- 原因：用户指出平台只是部署工具，差异应看税率、池子、持仓等代币自身配置。
- 解决：避免给"平台"贴标签导致系统性偏见。

## 2026-10-05 — 初筛阈值确定＋坚持不放水

- 三阶段阈值拍板（见 STRATEGY.md 第 3 节）；用户明确：行情冷清也不放宽生产阈值，
  等行情，接受空仓。
- 原因：用户的手动经验代码化；放水等于用噪音换虚假的"有产出"。

## 2026-10-05 — 风控改百分比为绝对金额＋并发数为上限

- 废弃"单笔≤2% 账户"百分比风控，改分阶段绝对金额上限；
  并发数明确为上限而非目标，绝不为凑数开仓。
- 原因：用户用数学指出手续费＋滑点下小额账户逐笔亏损，百分比风控不可行。
- 解决：风控与小资金 reality 对齐。

## 2026-10-05 — 0 候选兜底：换排序重试一次

- 主排序 0 通过时，按 `swaps_24h` 降序再拉一遍（API 上限 80/类），仍无结果接受空仓。
- 原因：默认排序可能埋没热币；解决"排序偏差导致的假性空仓"。
