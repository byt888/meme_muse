"""SOL 链适配器 (数据源: GMGN, 与 BSC 共用 GmgnMarketClient)

实测结论 (2026-10-07):
- gmgn-cli 所有读接口支持 --chain sol, 字段结构与 BSC 基本一致
- SOL trenches 额外提供: is_wash_trading, rug_ratio (BSC 没有)
- SOL security 额外提供: renounced_mint / renounced_freeze_account /
  burn_ratio / burn_status / lock_summary (LP 锁定)
- token info 的 price 可能是 dict {price, price_1m, price_5m}, 需取 price 字段
- security 的 is_honeypot 可能为 null, 用 honeypot 字段兜底
- 地址为 base58, 非 0x 格式
"""
from .base import ChainAdapter

CHAIN = "sol"

# 原生/基础代币
NATIVE = "SOL"
NATIVE_ADDRESS = "So11111111111111111111111111111111111111112"  # wSOL
USDC_SOL = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# GMGN trenches 三阶段 (与 BSC 同名)
STAGE_NEW_CREATION = "new_creation"
STAGE_NEAR_COMPLETION = "near_completion"
STAGE_COMPLETED = "completed"

# SOL 发射平台 (2026-10-07 trenches 实测出现的值, 非穷举)
LAUNCHPADS = [
    "Pump.fun",          # 主导 (~80% 新币)
    "pump_mayhem",
    "meteora_virtual_curve",
    "raydium",           # 毕业后池子常见
]

GMGN_FEE_PCT = 1.0  # GMGN 每笔交易收费约 1% (与 BSC 一致)


def _fix_price_dict(token: dict) -> dict:
    """token info 的 price 可能是 dict, 取出标量"""
    p = token.get("price_usd")
    if isinstance(p, dict):
        token["price_usd"] = p.get("price")
        token["price_1m_usd"] = p.get("price_1m")
        token["price_5m_usd"] = p.get("price_5m")
    return token


class SolAdapter(ChainAdapter):
    """SOL 适配器, 数据层委托给 GmgnMarketClient(chain='sol'),
    只做 SOL 特有的字段修正"""
    chain = CHAIN

    def __init__(self):
        from .gmgn_market import GmgnMarketClient
        self._c = GmgnMarketClient(chain=CHAIN)

    def native_token(self) -> str:
        return NATIVE

    def explorer_tx_url(self, tx_hash: str) -> str:
        return f"https://solscan.io/tx/{tx_hash}"

    def explorer_token_url(self, address: str) -> str:
        return f"https://gmgn.ai/sol/token/{address}"

    # ---- 行情发现 (委托) ----
    def get_trenches(self, stage: str, limit: int = 50,
                     sort_by: str | None = None) -> list[dict]:
        toks = self._c.get_trenches(stage, limit, sort_by=sort_by)
        for t in toks:
            raw = t.get("_raw", {})
            # SOL trenches 直接给 wash trading / rug ratio (BSC 没有)
            if t.get("wash_trading") is None and raw.get("is_wash_trading") is not None:
                t["wash_trading"] = bool(raw.get("is_wash_trading"))
            if t.get("rug_ratio") is None and raw.get("rug_ratio") is not None:
                t["rug_ratio"] = raw.get("rug_ratio")
            _fix_price_dict(t)
        return toks

    def get_trending(self, interval: str = "1m", limit: int = 50) -> list[dict]:
        return self._c.get_trending(interval, limit)

    def search_token(self, query: str) -> list[dict]:
        return self._c.search_token(query)

    def get_token_info(self, address: str) -> dict | None:
        t = self._c.get_token_info(address)
        return _fix_price_dict(t) if t else None

    def get_token_security(self, address: str) -> dict | None:
        """security 复核, 补 SOL 特有字段。
        注意: SOL 的 is_honeypot 常为 null, 用 honeypot 兜底;
        mint renounce / freeze renounce 是 SOL 版"权限安全"的核心。"""
        from .gmgn_market import _run
        data = _run(["token", "security", "--chain", CHAIN,
                     "--address", address])
        if not data or not data.get("address"):
            return None
        base = self._c.get_token_security(address) or {}
        hp = data.get("is_honeypot")
        if hp is None:
            hp = data.get("honeypot", 0)
        base["is_honeypot"] = bool(hp)
        base["renounced_mint"] = data.get("renounced_mint")
        base["renounced_freeze"] = data.get("renounced_freeze_account")
        base["burn_ratio"] = data.get("burn_ratio")
        base["burn_status"] = data.get("burn_status")
        base["lp_locked"] = (data.get("lock_summary") or {}).get("is_locked")
        return base

    def get_kline(self, address: str, resolution: str = "1m",
                  limit: int = 100) -> list[dict]:
        return self._c.get_kline(address, resolution)[:limit]

    def check_auth(self) -> bool:
        return self._c.check_auth()

    def enrich_momentum(self, token: dict,
                        trending_cache: list[dict] | None = None) -> dict:
        return self._c.enrich_momentum(token, trending_cache)

    def swap(self, token_in: str, token_out: str, amount: float,
             slippage_pct: float, dry_run: bool = True) -> dict:
        raise NotImplementedError("execution needs user authorization")
