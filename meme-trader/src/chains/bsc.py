"""BSC 链常量 (来自 GMGN 官方 skill, 勿凭记忆修改)"""
from .base import ChainAdapter

CHAIN = "bsc"

# 原生/基础代币
NATIVE = "BNB"
NATIVE_ADDRESS = "0x0000000000000000000000000000000000000000"
USDC_BSC = "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"

# GMGN trenches 三阶段
STAGE_NEW_CREATION = "new_creation"        # 新创建, 内盘未毕业
STAGE_NEAR_COMPLETION = "near_completion"  # 即将打满/毕业
STAGE_COMPLETED = "completed"              # 已毕业/已开盘

# BSC 发射平台 (gmgn-cli --launchpad-platform 可选值)
LAUNCHPADS = [
    "fourmeme", "fourmeme_agent", "bn_fourmeme", "four_xmode_agent",
    "cubepeg", "likwid", "goplus_creator", "goplus_skills",
    "openfour", "flap", "flap_stocks", "flap_aioracle",
    "clanker", "lunafun", "pool_uniswap", "pool_pancake",
]

# 交易参数
MIN_GAS_PRICE_GWEI = 0.05
MIN_TIP_FEE_BNB = 0.000001
ANTI_MEV_SUPPORTED = True
GMGN_FEE_PCT = 1.0  # GMGN 每笔交易收费约 1%


class BscAdapter(ChainAdapter):
    """BSC 适配器骨架, 数据源实现见 gmgn_market.GmgnMarketClient"""
    chain = CHAIN

    def native_token(self) -> str:
        return NATIVE

    def explorer_tx_url(self, tx_hash: str) -> str:
        return f"https://bscscan.com/tx/{tx_hash}"

    # 以下方法由 GmgnMarketClient 提供具体实现, 这里仅占位以明确接口
    def get_trenches(self, stage: str, limit: int = 50):
        raise NotImplementedError("use GmgnMarketClient")

    def get_trending(self, interval: str = "1m", limit: int = 50):
        raise NotImplementedError("use GmgnMarketClient")

    def search_token(self, query: str):
        raise NotImplementedError("use GmgnMarketClient")

    def get_token_info(self, address: str):
        raise NotImplementedError("use GmgnMarketClient")

    def get_kline(self, address: str, resolution: str = "1m", limit: int = 100):
        raise NotImplementedError("use GmgnMarketClient")

    def swap(self, token_in: str, token_out: str, amount: float,
             slippage_pct: float, dry_run: bool = True):
        raise NotImplementedError("execution needs user authorization")
