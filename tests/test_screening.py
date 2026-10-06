"""筛选框架单元测试 — 规则逻辑回归保护 (pytest)"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from screening.filters import screen
from screening.veto import check_veto
from screening.lifecycle import classify, can_open, State
from screening.scorer import score_early, size_for_score
from risk.limits import RiskState, can_open as risk_can_open


def good_token():
    return {"txns": 50, "buy_tax_pct": 1, "sell_tax_pct": 1, "call_count": 3,
            "holders": 25, "watchers": 30, "market_cap_usd": 8000,
            "price_change_5m_pct": 20, "buys_1h": 80, "sells_1h": 20,
            "dev_hold_pct": 2, "smart_money_count": 3, "age_minutes": 15,
            "price_change_1h_pct": 40, "holder_change_1h_pct": 15}


def test_screen_pass():
    r = screen(good_token(), "new_creation")
    assert r.passed and not r.failed and not r.unknown


def test_screen_fail_closed_on_missing():
    t = good_token()
    del t["holders"]
    r = screen(t, "new_creation")
    assert not r.passed and "holders" in r.unknown


def test_screen_tax():
    t = good_token()
    t["sell_tax_pct"] = 10
    r = screen(t, "new_creation")
    assert not r.passed and any("total_tax_pct" in f for f in r.failed)


def test_veto_honeypot():
    t = good_token()
    t["is_honeypot"] = True
    assert check_veto(t).vetoed


def test_veto_holder_drain():
    t = good_token()
    t["holder_change_1h_pct"] = -25
    r = check_veto(t)
    assert r.vetoed and any("流失" in x for x in r.reasons)


def test_lifecycle_uptrend_allows():
    assert can_open(classify(good_token()))


def test_lifecycle_dead_blocks():
    t = good_token()
    t.update({"drawdown_from_high_pct": 80, "holder_change_1h_pct": -35})
    st = classify(t)
    assert st == State.DEAD and not can_open(st)


def test_lifecycle_second_wave_needs_catalyst():
    t = good_token()
    t.update({"drawdown_from_high_pct": 65, "price_change_1h_pct": 8,
              "price_change_5m_pct": 3, "holder_change_1h_pct": -2,
              "volume_ratio_vs_avg": 1.0})
    assert classify(t) == State.STABILIZING  # 无催化不开
    assert classify(t, has_fresh_catalyst=True) == State.SECOND_WAVE
    # 仅 5m 反弹但 1h 仍为负 → 未重回上涨趋势, 保守判企稳
    t["price_change_1h_pct"] = -2
    assert classify(t, has_fresh_catalyst=True) == State.STABILIZING


def test_scorer_mapping():
    s, _ = score_early(good_token(), m50=6000)
    assert 0 <= s <= 100
    assert size_for_score(95, 3.5) == 3.5
    assert size_for_score(80, 3.5) == round(3.5 * 0.7, 2)
    assert size_for_score(50, 3.5) == 0.0


def test_risk_concurrency_cap():
    rs = RiskState()
    ok, _ = risk_can_open(rs, "new_creation", 3.5, "0x1")
    assert ok
    rs.positions.append({"stage": "new_creation", "amount_usd": 3.5,
                         "address": "0x1"})
    ok, msg = risk_can_open(rs, "new_creation", 3.5, "0x2")
    assert not ok and "上限" in msg  # 并发上限非目标


def test_risk_blacklist():
    rs = RiskState(blacklisted={"0xdead"})
    ok, _ = risk_can_open(rs, "new_creation", 3.5, "0xdead")
    assert not ok
