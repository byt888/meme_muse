"""
风控 — 仓位/并发/熔断 (规则实现, 无 LLM)

核心原则 (用户确定):
- 各阶段并发数是上限不是目标, 默认空仓
- 只因优质标的开仓, 绝不为凑数开仓
- 以下金额为蓝图参数, 需纸面跑验证后才能作为实盘授权值
"""
from dataclasses import dataclass, field


# 分阶段默认参数 (USD) — 待纸面跑验证, 非最终授权值
STAGE_PARAMS = {
    "new_creation":    {"per_trade": 3.5, "max_positions": 1},
    "near_completion": {"per_trade": 5.5, "max_positions": 2},
    "completed_hot":   {"per_trade": 7.0, "max_positions": 2},
    "second_wave":     {"per_trade": 7.0, "max_positions": 2},
}
GLOBAL_MAX_POSITIONS = 4
GLOBAL_MAX_EXPOSURE_USD = 24.0

# 退出参数 (待验证)
HARD_STOP_PCT = -30        # 硬止损
TAKE_PROFIT_1_PCT = 100    # +100% 卖 50% 回本金
TRAILING_DRAWDOWN = 25      # 剩余仓位 25% 峰值回撤移动止盈
TAKE_PROFIT_2_PCT = 400    # +400% 再卖剩余一半
MOON_DRAWDOWN = 40         # 月球仓移动止盈放宽到 40%
TIME_STOP_HOURS = 4        # 时间止损: 4h 到期市价全平 (纸面胜率按 4h 口径算)


@dataclass
class RiskState:
    positions: list[dict] = field(default_factory=list)  # {stage, amount, ...}
    blacklisted: set = field(default_factory=set)
    halted: bool = False  # 熔断
    halt_reason: str = ""


def stage_position_count(state: RiskState, stage: str) -> int:
    return sum(1 for p in state.positions if p.get("stage") == stage)


def total_exposure(state: RiskState) -> float:
    return sum(p.get("amount_usd", 0) for p in state.positions)


def can_open(state: RiskState, stage: str, amount_usd: float,
             token_address: str) -> tuple[bool, str]:
    """是否允许开新仓"""
    if state.halted:
        return False, f"熔断中: {state.halt_reason}"
    if token_address in state.blacklisted:
        return False, "标的已拉黑"
    params = STAGE_PARAMS.get(stage)
    if not params:
        return False, f"未知阶段: {stage}"
    if stage_position_count(state, stage) >= params["max_positions"]:
        return False, f"{stage} 并发已达上限 {params['max_positions']}"
    if len(state.positions) >= GLOBAL_MAX_POSITIONS:
        return False, f"全局持仓已达上限 {GLOBAL_MAX_POSITIONS}"
    if total_exposure(state) + amount_usd > GLOBAL_MAX_EXPOSURE_USD:
        return False, "超过全局最大敞口"
    return True, "ok"


def trip_circuit_breaker(state: RiskState, reason: str):
    """熔断: 触发后只卖不买, 需人工复位"""
    state.halted = True
    state.halt_reason = reason


def reset_circuit_breaker(state: RiskState):
    state.halted = False
    state.halt_reason = ""
