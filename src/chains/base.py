"""
多链适配器接口 (ChainAdapter)

设计目标:
- 所有链相关操作经统一接口, 策略层只依赖接口不依赖具体链
- 新增链 (SOL/ETH/...) 时只需实现本接口, 无需改策略代码
- 纯数据结构用 dict, 字段命名统一 (snake_case), 各链实现负责映射

Token 字典统一字段 (各链尽量填, 缺失填 None):
    address, symbol, name, chain,
    price_usd, market_cap_usd, liquidity_usd, pool_usd,
    txns_24h/1h, buys/sells, volume_usd,
    holders, holder_change_1h_pct,
    buy_tax_pct, sell_tax_pct,
    is_honeypot, top10_holder_pct, dev_hold_pct, bundler_pct,
    wash_trading (bool), rug_ratio (0-1),
    created_at_ts, age_minutes,
    launchpad, stage (new_creation/near_completion/completed),
    smart_money_count, kol_count, call_count (喊单数), watchers (正在浏览),
    price_change_5m/1h/24h_pct
"""
from abc import ABC, abstractmethod
from typing import Optional


class ChainAdapter(ABC):
    chain: str = ""

    # ---- 行情发现 ----
    @abstractmethod
    def get_trenches(self, stage: str, limit: int = 50) -> list[dict]:
        """新币三阶段: new_creation / near_completion / completed"""

    @abstractmethod
    def get_trending(self, interval: str = "1m", limit: int = 50) -> list[dict]:
        """热门榜"""

    @abstractmethod
    def search_token(self, query: str) -> list[dict]:
        """按名称/symbol/CA 搜索代币"""

    @abstractmethod
    def get_token_info(self, address: str) -> Optional[dict]:
        """代币详情 (安全字段+行情+持仓分布)"""

    @abstractmethod
    def get_kline(self, address: str, resolution: str = "1m",
                  limit: int = 100) -> list[dict]:
        """K 线: [{ts, open, high, low, close, volume}]"""

    # ---- 交易执行 (需授权, 纸面模式可 mock) ----
    @abstractmethod
    def swap(self, token_in: str, token_out: str, amount: float,
             slippage_pct: float, dry_run: bool = True) -> dict:
        """兑换, dry_run=True 只返回模拟结果不真下单"""

    # ---- 工具 ----
    @abstractmethod
    def native_token(self) -> str:
        """本链 gas/基础币符号, 如 BNB/SOL/ETH"""

    @abstractmethod
    def explorer_tx_url(self, tx_hash: str) -> str:
        """浏览器交易链接"""
