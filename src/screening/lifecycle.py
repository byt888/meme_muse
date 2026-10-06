"""
生命周期状态机 — 替代固定"年龄"硬切分, 9 状态 (规则实现, 无 LLM)

状态:
  LAUNCH      刚创建, 数据不足
  UPTREND     上涨趋势 ← 唯一允许开新仓的状态
  TOPPING     滞涨顶部, 只卖不买, 收紧移动止盈
  DOWNTREND   下跌, 禁止新仓
  DEAD        死亡螺旋 (回撤>70% 且 holder 1h 流失>30%), 拉黑
  OVERSOLD    超跌 (回撤>60%), 本身不允许抄底
  STABILIZING 超跌企稳 (跌势放缓+holder 止跌), 仍不开仓, 等催化
  SECOND_WAVE 二段 (企稳 + 新催化 + 重回上涨), 允许开仓
  FADED       热度熄灭, 忽略

转移条件由纯函数判定, 输入为 token 快照序列。
"""
from enum import Enum


class State(Enum):
    LAUNCH = "launch"
    UPTREND = "uptrend"
    TOPPING = "topping"
    DOWN_TREND = "downtrend"
    DEAD = "dead"
    OVERSOLD = "oversold"
    STABILIZING = "stabilizing"
    SECOND_WAVE = "second_wave"
    FADED = "faded"


# 允许开新仓的状态 (铁律)
ALLOW_NEW_POSITION = {State.UPTREND, State.SECOND_WAVE}

# 拉黑状态
BLACKLISTED = {State.DEAD}


def classify(t: dict, has_fresh_catalyst: bool = False) -> State:
    """
    t: token 当前快照 (统一字段, 见 chains/base.py)
    has_fresh_catalyst: 是否有新催化 (新闻确认器 verdict != no_catalyst)
    """
    dd = t.get("drawdown_from_high_pct") or 0          # 从高点回撤 %
    hc = t.get("holder_change_1h_pct") or 0             # holder 1h 变化 %
    mom_1h = t.get("price_change_1h_pct") or 0          # 1h 涨跌 %
    mom_5m = t.get("price_change_5m_pct") or 0          # 5m 涨跌 %
    vol_ratio = t.get("volume_ratio_vs_avg") or 1      # 相对均量比
    age = t.get("age_minutes") or 0

    # 死亡螺旋: 回撤>70% 且 holder 快速流失 → 拉黑
    if dd > 70 and hc < -30:
        return State.DEAD

    # 超跌区
    if dd > 60:
        # 企稳迹象: 跌势放缓 + holder 止跌 + 有量
        if mom_1h > -5 and hc > -5 and vol_ratio > 0.5:
            if has_fresh_catalyst and mom_5m > 0 and mom_1h > 0:
                return State.SECOND_WAVE
            return State.STABILIZING
        return State.OVERSOLD

    # 顶部滞涨: 接近高点但动量衰竭 (涨不动 + 放量滞涨)
    if dd < 15 and mom_1h < 2 and vol_ratio > 1.5 and age > 30:
        # 高位放量不涨 → 顶部
        if mom_5m <= 0:
            return State.TOPPING

    # 上涨趋势: 动量为正
    if mom_1h > 5 and mom_5m >= 0:
        return State.UPTREND
    if mom_1h > 0 and hc > 0:
        return State.UPTREND

    # 下跌
    if mom_1h < -10:
        return State.DOWN_TREND

    # 热度熄灭: 量缩 + 无动量 + 有一定年龄
    if vol_ratio < 0.3 and abs(mom_1h) < 3 and age > 120:
        return State.FADED

    # 数据不足
    if age < 10:
        return State.LAUNCH

    return State.STABILIZING  # 默认保守: 不开仓


def can_open(state: State) -> bool:
    return state in ALLOW_NEW_POSITION


def describe(state: State) -> str:
    return {
        State.LAUNCH: "刚创建, 数据不足, 观望",
        State.UPTREND: "上涨趋势, 允许开新仓",
        State.TOPPING: "滞涨顶部, 只卖不买",
        State.DOWN_TREND: "下跌中, 禁止新仓",
        State.DEAD: "死亡螺旋, 拉黑",
        State.OVERSOLD: "超跌, 不抄底",
        State.STABILIZING: "企稳中, 等催化",
        State.SECOND_WAVE: "二段启动, 允许开仓",
        State.FADED: "热度熄灭, 忽略",
    }[state]
