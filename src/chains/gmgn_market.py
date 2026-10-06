"""
GMGN 市场数据客户端 — 封装 gmgn-cli (BSC)

前置: `gmgn-cli config --check` 必须通过 (需用户在 gmgn.ai 生成 API Key)。
本模块只做读操作 (trenches/trending/search/token/kline), 不下单。

字段映射到统一 token dict (见 chains/base.py)。
"""
import json
import shutil
import subprocess


class GmgnError(Exception):
    pass


class GmgnAuthError(GmgnError):
    """API Key 未配置或失效 → 需用户操作"""


class GmgnRateLimitError(GmgnError):
    """限流 → 退避重试"""


def _run(args: list[str], timeout: int = 30) -> dict:
    if not shutil.which("gmgn-cli"):
        raise GmgnError("gmgn-cli 未安装: npm install -g gmgn-cli")
    try:
        p = subprocess.run(["gmgn-cli"] + args, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise GmgnError(f"gmgn-cli 超时: {' '.join(args)}")
    out = (p.stdout or "").strip()
    # 尝试解析 JSON (cli 可能输出纯 JSON 或混杂日志)
    data = None
    for candidate in (out, out[out.find("{"):], out[out.find("["):]):
        if not candidate or len(candidate) < 2:
            continue
        try:
            data = json.loads(candidate)
            break
        except Exception:
            continue
    if data is None:
        err = (p.stderr or out)[:300]
        if "401" in err or "unauthorized" in err.lower() or "api key" in err.lower():
            raise GmgnAuthError(f"GMGN 认证失败: {err}")
        if "429" in err or "rate" in err.lower():
            raise GmgnRateLimitError(f"GMGN 限流: {err}")
        raise GmgnError(f"gmgn-cli 失败: {err}")
    return data if isinstance(data, dict) else {"items": data}


def _norm_token(raw: dict, chain: str = "bsc") -> dict:
    """GMGN 原始字段 → 统一 token dict (字段缺失填 None)
    字段依据 2026-10-05 实测的 trenches 返回 (85 字段)"""
    import time
    g = lambda *ks: next((raw.get(k) for k in ks if raw.get(k) is not None), None)

    def tax_pct(v):
        if v is None:
            return None
        v = float(v)
        return v * 100 if v < 1 else v  # GMGN 返回小数形态 (0.02=2%)

    bt, st = tax_pct(g("buy_tax")), tax_pct(g("sell_tax"))
    cts = g("created_timestamp")
    age_min = (time.time() - float(cts)) / 60 if cts else None
    txns = g("swaps_24h")
    if txns is None:
        b, s = g("buys_24h"), g("sells_24h")
        txns = (b or 0) + (s or 0) if (b is not None or s is not None) else None
    return {
        "address": g("address"),
        "symbol": g("symbol"), "name": g("name"), "chain": chain,
        "price_usd": g("price"),
        "market_cap_usd": g("market_cap"),
        "liquidity_usd": g("liquidity"),
        "pool_usd": g("liquidity"),
        "txns": txns,
        "txns_24h": txns,
        "buys_24h": g("buys_24h"), "sells_24h": g("sells_24h"),
        "net_buy_24h": g("net_buy_24h"),
        "volume_usd": g("volume_24h"),
        "holders": g("holder_count"),
        "buy_tax_pct": bt, "sell_tax_pct": st,
        "total_tax_pct": (bt + st) if (bt is not None or st is not None) else None,
        "is_honeypot": bool(g("is_honeypot")) if g("is_honeypot") is not None else None,
        "top10_holder_pct": g("top_10_holder_rate"),
        "dev_hold_pct": g("dev_team_hold_rate"),
        "dev_creator_status": g("creator_token_status"),  # creator_hold=dev未跑
        "bundler_pct": g("bundler_trader_amount_rate"),
        "rat_trader_rate": g("rat_trader_amount_rate"),
        "rug_ratio": None,  # trenches 未提供
        "wash_trading": None,  # trenches 未直接提供
        "age_minutes": age_min,
        "created_at_ts": cts,
        "launchpad": g("launchpad", "launchpad_platform"),
        "progress_pct": g("progress"),  # bonding curve 进度 0-100
        "smart_money_count": g("smart_degen_count"),
        "kol_count": g("renowned_count"),
        "call_count": g("callout_count", "tg_call_count"),  # 喊单数
        "watchers": None,  # trenches 不提供 (初筛中按 unknown 处理)
        "twitter_handle": g("twitter_handle"),
        "twitter_has_tweet": g("twitter_is_tweet"),
        "cto_flag": g("cto_flag"),
        "_raw": raw,
    }


class GmgnMarketClient:
    """BSC 市场数据, 读操作"""

    def __init__(self, chain: str = "bsc"):
        self.chain = chain

    def _q(self, *args, data_key: str | None = None) -> list[dict]:
        data = _run(list(args))
        items = None
        if data_key:
            items = data.get(data_key)
        if items is None:
            items = data.get("items") or data.get("tokens") or data.get("data") or []
        if isinstance(items, dict):
            items = items.get("tokens") or items.get("list") or items.get("rank") or []
        return [_norm_token(x, self.chain) for x in (items or [])]

    def get_trenches(self, stage: str, limit: int = 50,
                     sort_by: str | None = None) -> list[dict]:
        """stage: new_creation / near_completion / completed
        注意: --type 只返回对应阶段的数据 (其他 key 为空数组), 按 stage key 取
        字段已验证: callout_count = 前端小喇叭喊单数 (2026-10-05 用 ZACHXBT 对账: API=9=前端显示9)
        sort_by: 服务端排序 (如 swaps_24h/holder_count/usd_market_cap),
        默认排序可能埋没热币, 0 候选时可换排序重试"""
        args = ["market", "trenches", "--chain", self.chain,
                "--type", stage, "--limit", str(limit)]
        if sort_by:
            args += ["--sort-by", sort_by, "--direction", "desc"]
        return self._q(*args, data_key=stage)[:limit]

    def get_trending(self, interval: str = "1m", limit: int = 50) -> list[dict]:
        return self._q("market", "trending", "--chain", self.chain,
                       "--interval", interval, "--limit", str(limit))[:limit]

    def enrich_momentum(self, token: dict, trending_cache: list[dict] | None = None) -> dict:
        """用 trending 数据补动量字段 (price_change_1m/5m/1h)。
        trenches 不提供这些, 生命周期分类需要。
        trending_cache: 预拉取的 trending 列表, 避免每个币调一次"""
        addr = (token.get("address") or "").lower()
        tl = trending_cache
        if tl is None:
            tl = self.get_trending("1m", 200)
        for t in tl:
            raw = t.get("_raw", {})
            if (raw.get("address") or t.get("address") or "").lower() == addr:
                token["price_change_1m_pct"] = raw.get("price_change_percent1m")
                token["price_change_5m_pct"] = raw.get("price_change_percent5m")
                token["price_change_1h_pct"] = raw.get("price_change_percent1h")
                break
        return token

    def search_token(self, query: str) -> list[dict]:
        return self._q("market", "search", "--query", query,
                       "--chain", self.chain)

    def get_token_security(self, address: str) -> dict | None:
        """代币安全详情。重要: trenches 的 is_honeypot 有误报 (2026-10-05 实测
        AGENTIAL/DOODROP 在 trenches 显示 True, security 接口显示 False),
        否决项必须以此接口为准。"""
        data = _run(["token", "security", "--chain", self.chain,
                     "--address", address])
        if not data or not data.get("address"):
            return None
        return {
            "is_honeypot": bool(data.get("is_honeypot", False)),
            "is_open_source": data.get("is_open_source"),
            "is_blacklist": data.get("is_blacklist"),
            "top10_holder_pct": data.get("top_10_holder_rate"),
            "burn_ratio": data.get("burn_ratio"),
            "_raw": data,
        }

    def get_token_info(self, address: str) -> dict | None:
        """代币详情。注意返回结构与 trenches 不同, 含 visiting_count(正在浏览人数)。
        用 _norm_token_info 单独解析后合并。"""
        data = _run(["token", "info", "--chain", self.chain,
                     "--address", address])
        if not data or not data.get("address"):
            return None
        t = _norm_token(data, self.chain)
        # token info 特有字段补齐
        t["watchers"] = data.get("visiting_count")
        st = data.get("stat") or {}
        if t.get("dev_hold_pct") is None:
            t["dev_hold_pct"] = st.get("dev_team_hold_rate")
        if t.get("top10_holder_pct") is None:
            t["top10_holder_pct"] = st.get("top_10_holder_rate")
        t["holders"] = t["holders"] or data.get("holder_count") or st.get("holder_count")
        t["call_count"] = t.get("call_count") or st.get("degen_call_count")
        t["launchpad_progress"] = data.get("launchpad_progress")
        return t

    def check_auth(self) -> bool:
        """CLI 是否已配置 (不抛异常版本)"""
        try:
            p = subprocess.run(["gmgn-cli", "config", "--check"],
                               capture_output=True, timeout=15)
            return p.returncode == 0
        except Exception:
            return False
