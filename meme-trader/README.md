# Meme Trader — 多链 Meme 币自动交易系统

新闻驱动为主策略的 BSC Meme 币扫描 → 精选 → 执行 → 退出系统。
设计为**可复制给他人使用**、**多链适配**、**规则代码优先于 LLM**。

## 快速开始 (复制即用)

```bash
git clone <repo> && cd meme-trader
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm install -g gmgn-cli          # GMGN 行情/交易 CLI

cp .env.example .env && chmod 600 .env        # 填密钥
cp config/config.example.yaml config/config.yaml  # 改参数
```

必填密钥 (`.env`):
| 变量 | 获取方式 |
|---|---|
| `GMGN_API_KEY` | https://gmgn.ai/ai 生成 (Free 套餐可用) |
| `GMGN_PRIVATE_KEY` | API 请求签名密钥 (非链上钱包私钥, 可轮换) |
| `J7_SESSION_ID` | j7tracker.io 登录后 F12 `localStorage.getItem("sessionId")` (15天有效期) |

验证 GMGN: `gmgn-cli config --check` (返回 0 即正常)

## 项目结构

```
src/
  chains/       多链适配器 (ChainAdapter 接口)
    base.py       统一 token dict 字段规范
    bsc.py        BSC 常量 (发射平台/交易参数)
    gmgn_market.py  gmgn-cli 读操作封装 (trenches/trending/search)
    # sol.py / eth.py 预留
  sources/      情报源 (第1层采集)
  intel/        情报库+确认器 (第2+3层)
  screening/    精选框架 (第4层决策)
    filters.py    初筛 (三阶段用户经验条件)
    veto.py       一票否决 (5项)
    lifecycle.py  9状态生命周期状态机
    scorer.py     动量打分 + 打分映射仓位
  execution/    执行层 (A轨GMGN/B轨自持钱包, 需授权)
  risk/         风控 (并发上限/熔断/退出参数)
  common/       config.py (yaml+env 分层配置)
config/         config.example.yaml (复制为 config.yaml)
scripts/        运行脚本
tests/          测试
```

## 设计原则

1. **规则优先**: 筛选/打分/状态机/风控全部是纯函数规则实现, 零 LLM 依赖。
   LLM 只作为可选增强 (如推文语义解析), 不在核心决策链上。
2. **多链适配**: 策略代码只依赖 `ChainAdapter` 接口。新增链只需实现
   `get_trenches/get_trending/search_token/get_token_info/get_kline/swap`。
3. **配置驱动**: 阈值/仓位/阶段参数全在 `config.yaml`, 密钥全在 `.env`,
   换用户只需改配置, 不改代码。
4. **默认纸面**: `dry_run: true` 时所有执行只模拟不下单。
   实盘需显式改配置 + 用户授权 (钱包/资金)。

## 四层情报加工链

```
采集 (sources) → 提取/映射 (intel) → 决策 (screening) → 执行/风控 (execution/risk)
```

- 第1层: J7Tracker 推文流 (已运行, 见外部 `web3/j7/`), GMGN trenches
- 第2层: 情报库 SQLite + 实体提取 (ticker/CA/项目名)
- 第3层: `news_confirmer.py` — 币→新闻催化剂确认 (JSON 直喂精选)
- 第4层: 初筛 → 一票否决 → 生命周期 (仅 uptrend/second_wave 可开仓) → 打分映射仓位

## 当前状态

- ✅ J7 推文监听 + 情报库 + 新闻确认器 (外部 `web3/j7/`, 待迁入 `src/`)
- ✅ 筛选框架 (filters/veto/lifecycle/scorer, 自测通过)
- ✅ 风控模块, GMGN 读操作封装
- ⏳ GMGN API Key (待用户提供) → trenches 实盘扫描
- ⏳ 执行层 (待用户授权钱包/资金)
- ⏳ 路径1 推文→币快打 (待执行层就绪)

## 安全

- `.env` / `config.yaml` / `*.db` / `logs/` 永不提交 (见 `.gitignore`)
- `GMGN_PRIVATE_KEY` 是 API 签名密钥, 不是链上私钥
- 无头自动交易需 `GMGN_ALLOW_AUTOMATED_TRADES=1` + 用户明确授权
