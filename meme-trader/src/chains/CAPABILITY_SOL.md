# SOL 链能力手册 (CAPABILITY)

> 研究日期: 2026-10-07 | 数据源: GMGN (`gmgn-cli --chain sol`) | 适配器: `src/chains/sol.py`

## 一句话

GMGN 的 SOL 接口与 BSC 字段结构基本一致, 可直接复用 `GmgnMarketClient`;
SOL 版 trenches 甚至多给了 `is_wash_trading` / `rug_ratio`,
security 接口多给了 mint/freeze 权限状态。适配器已写完并冒烟测试通过。

## 接口对照 (全部实测通过)

| 接口 | CLI 命令 | 状态 | 备注 |
|---|---|---|---|
| trenches 三阶段 | `market trenches --chain sol --type <stage>` | ✅ | 字段与 BSC 一致, 另多 `is_wash_trading`、`rug_ratio`、`burn_status`、`renounced_mint`、`renounced_freeze_account` |
| token info | `token info --chain sol --address` | ✅ | 含 `visiting_count`(正在浏览人数); `price` 可能是 dict `{price,price_1m,price_5m}`, 适配器已处理 |
| token security | `token security --chain sol --address` | ✅ | `is_honeypot` 常为 null (用 `honeypot` 兜底); 核心看 `renounced_mint` / `renounced_freeze_account` / `burn_ratio` / `lock_summary.is_locked` |
| kline | `market kline --chain sol --address --resolution` | ✅ | 格式与 BSC 一致 (毫秒时间戳, 适配器已处理) |
| trending | `market trending --chain sol` | ✅ | 与 BSC 同接口 |
| search | `market search --query --chain sol` | ✅ | 与 BSC 同接口 |

## 与 BSC 的关键差异

1. **地址格式**: base58 (如 `Cf16W7...`), 非 0x。入库/去重时注意不要按 0x 前缀假设。
2. **trenches 无 honeypot 字段**: SOL 的 trenches 压根不返回该字段 → 初筛记为 unknown,
   否决以 security 接口为准 (本来 BSC 也要求 security 二次确认, 逻辑不变)。
3. **税**: SOL 代币通常无税 (buy_tax/sell_tax 多为 0), BSC 那套"总税率≤4%"阈值
   在 SOL 上几乎恒过, 初筛时该条件形同虚设 → SOL 阈值需重定 (见下)。
4. **发射平台**: Pump.fun 占主导 (~80%), 另有 pump_mayhem、meteora_virtual_curve;
   Raydium 多为毕业后池子。"即将打满"在 SOL = pump.fun 内盘毕业 (progress→100%)。
5. **原生币**: SOL; 浏览器 solscan.io; GMGN 链接 `gmgn.ai/sol/token/<addr>`。
6. **聪明钱字段**: `smart_degen_count` / `renowned_count` / `callout_count` 命名与 BSC 一致。

## 技术坑

- token info 的 `price` 有时是 dict, 直接 `float()` 会炸 → `sol.py::_fix_price_dict` 已处理。
- security 的 `is_honeypot: null` → 按 `honeypot` 字段兜底, 仍无则 False
  (结合 renounced_mint/freeze 综合判断, 单一字段不判死)。
- SOL 新币极多, trenches `new_creation` 50 条里 launchpad 几乎全是 Pump.fun,
  初筛阈值若照抄 BSC 会放进来大量噪音 → **SOL 必须独立跑数据定阈值**。
- GMGN 产品层 (SnipeX/一键跟单/自动买卖) 均为 SOL only, BSC 不可用。
  这意味着 SOL 实盘时执行工具有更多选项, 但自动交易同样需用户明确授权
  (`GMGN_ALLOW_AUTOMATED_TRADES` 保持关闭, 铁律不变)。

## 复用指南

```python
from chains.sol import SolAdapter
a = SolAdapter()
toks = a.get_trenches("new_creation", 50)   # 统一 token dict, 见 chains/base.py
info = a.get_token_info(addr)               # 含 watchers (visiting_count)
sec  = a.get_token_security(addr)           # 含 renounced_mint/freeze, lp_locked
kl   = a.get_kline(addr, "1m")              # 纸面退出模拟直接复用
```

策略层 (打分/生命周期/退出模拟/风控) 零改动, 只消费统一 token dict。
BSC 的 `paper_scan_all.sh` 复制一份改 `--chain sol` 即可跑 SOL 纸面
(阈值文件需独立, 见 OPTIMIZATION_LOG 待办)。

## 下一步 (Phase B, 待用户确认后启动)

1. 建 `scripts/paper_scan_sol.sh` (复用管线, 独立阈值配置 `config/sol_thresholds.yaml`)
2. 跑 1–2 周 SOL 纸面, 统计各阶段 M50 / txns / holders / callout 分布
3. 按 SOL 数据定初筛阈值, 写入 OPTIMIZATION_LOG
4. SOL 独立纸面门禁 (20 笔/胜率 55%/盈亏比 1.5), 达标前不谈实盘
