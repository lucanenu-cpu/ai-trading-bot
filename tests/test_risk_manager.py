"""
tests/test_risk_manager.py

Minimal unit tests for risk_manager.py — pure logic, no network calls.
"""
import datetime
import sys
import os

# Ensure repo root is on path so imports work when run from any directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

# Patch config values before importing risk_manager so tests use controlled settings
import config as _cfg
_cfg.ACCOUNT_BALANCE_USD = 100.0
_cfg.RISK_PER_TRADE_PCT = 1.0
_cfg.MAX_DAILY_LOSS_PCT = 3.0
_cfg.MAX_TRADES_PER_DAY = 5
_cfg.MAX_OPEN_POSITIONS = 3
_cfg.MIN_SIGNAL_SCORE = 65.0
_cfg.STRONG_SIGNAL_SCORE = 80.0
_cfg.DEFAULT_STOP_LOSS_PCT = 2.0
_cfg.DEFAULT_TAKE_PROFIT_PCT = 4.0

import risk_manager
from risk_manager import (
    RiskState,
    calculate_position_size,
    compute_trade_levels,
    can_open_new_trade,
    allocation_recommendation,
    reset_daily_if_needed,
    record_trade,
)


# ---------------------------------------------------------------------------
# calculate_position_size
# ---------------------------------------------------------------------------

class TestCalculatePositionSize:
    def test_basic(self):
        result = calculate_position_size(
            balance=100.0,
            risk_pct=1.0,
            stop_loss_pct=2.0,
            price=50.0,
        )
        # risk_amount = 100 * 0.01 = 1.0
        # allocation  = 1.0 / 0.02 = 50.0
        assert result["risk_amount_usd"] == pytest.approx(1.0, rel=1e-4)
        assert result["allocation_usd"]  == pytest.approx(50.0, rel=1e-4)
        assert result["allocation_pct"]  == pytest.approx(50.0, rel=1e-4)
        assert result["quantity"]        == pytest.approx(1.0, rel=1e-4)

    def test_capped_at_balance(self):
        # Very tight stop means huge position — should be capped
        result = calculate_position_size(
            balance=100.0,
            risk_pct=10.0,
            stop_loss_pct=0.1,
            price=100.0,
        )
        assert result["allocation_usd"] <= 100.0

    def test_zero_inputs_return_zeros(self):
        result = calculate_position_size(0, 1, 2, 50)
        assert result["allocation_usd"] == 0.0
        result = calculate_position_size(100, 0, 2, 50)
        assert result["allocation_usd"] == 0.0

    def test_quantity_calculation(self):
        result = calculate_position_size(
            balance=100.0,
            risk_pct=1.0,
            stop_loss_pct=2.0,
            price=100.0,
        )
        # allocation = 50, qty = 50 / 100 = 0.5
        assert result["quantity"] == pytest.approx(0.5, rel=1e-4)


# ---------------------------------------------------------------------------
# compute_trade_levels
# ---------------------------------------------------------------------------

class TestComputeTradeLevels:
    def test_buy_direction(self):
        result = compute_trade_levels(100.0, "BUY", 2.0, 4.0)
        assert result["entry"]       == pytest.approx(100.0)
        assert result["stop_loss"]   == pytest.approx(98.0, rel=1e-4)
        assert result["take_profit"] == pytest.approx(104.0, rel=1e-4)

    def test_sell_direction(self):
        result = compute_trade_levels(100.0, "SELL", 2.0, 4.0)
        assert result["stop_loss"]   == pytest.approx(102.0, rel=1e-4)
        assert result["take_profit"] == pytest.approx(96.0, rel=1e-4)

    def test_long_alias(self):
        r1 = compute_trade_levels(100.0, "LONG", 2.0, 4.0)
        r2 = compute_trade_levels(100.0, "BUY",  2.0, 4.0)
        assert r1["stop_loss"] == r2["stop_loss"]

    def test_short_alias(self):
        r1 = compute_trade_levels(100.0, "SHORT", 2.0, 4.0)
        r2 = compute_trade_levels(100.0, "SELL",  2.0, 4.0)
        assert r1["stop_loss"] == r2["stop_loss"]

    def test_zero_price_returns_price(self):
        result = compute_trade_levels(0.0, "BUY", 2.0, 4.0)
        assert result["entry"] == 0.0


# ---------------------------------------------------------------------------
# can_open_new_trade
# ---------------------------------------------------------------------------

class TestCanOpenNewTrade:
    def _fresh_state(self):
        return RiskState()

    def test_allows_on_fresh_state(self):
        state = self._fresh_state()
        ok, reason = can_open_new_trade(state, balance=100.0)
        assert ok is True
        assert reason == "OK"

    def test_blocks_when_max_trades_reached(self):
        state = self._fresh_state()
        state.trades_today = _cfg.MAX_TRADES_PER_DAY  # 5
        ok, reason = can_open_new_trade(state, balance=100.0)
        assert ok is False
        assert "Max trades" in reason

    def test_blocks_when_max_positions_reached(self):
        state = self._fresh_state()
        state.open_positions = ["A", "B", "C"]  # MAX_OPEN_POSITIONS = 3
        ok, reason = can_open_new_trade(state, balance=100.0)
        assert ok is False
        assert "Max open positions" in reason

    def test_blocks_on_daily_loss_cap(self):
        state = self._fresh_state()
        # balance=100, loss=4 => 4% which exceeds MAX_DAILY_LOSS_PCT=3%
        state.realized_pnl_today = -4.0
        ok, reason = can_open_new_trade(state, balance=100.0)
        assert ok is False
        assert "loss cap" in reason.lower()

    def test_resets_on_new_day(self):
        state = self._fresh_state()
        state.date = datetime.date(2000, 1, 1)
        state.trades_today = _cfg.MAX_TRADES_PER_DAY
        # After reset_daily_if_needed today's date will be used, counter resets
        reset_daily_if_needed(state)
        assert state.trades_today == 0
        ok, _ = can_open_new_trade(state, balance=100.0)
        assert ok is True


# ---------------------------------------------------------------------------
# allocation_recommendation
# ---------------------------------------------------------------------------

class TestAllocationRecommendation:
    def test_strong_signal_full_size(self):
        result = allocation_recommendation(85.0, balance=100.0)
        assert result["size_label"] == "full"
        assert result["suggested_usd"] > 0

    def test_moderate_signal_half_size(self):
        result = allocation_recommendation(70.0, balance=100.0)
        assert result["size_label"] == "half"

    def test_weak_signal_quarter_size(self):
        result = allocation_recommendation(40.0, balance=100.0)
        assert result["size_label"] == "quarter"

    def test_usd_is_positive(self):
        result = allocation_recommendation(75.0, balance=50.0)
        assert result["suggested_usd"] > 0
        assert result["suggested_usd"] <= 50.0

    def test_pct_bounds(self):
        result = allocation_recommendation(70.0, balance=100.0)
        # pct should be positive and ≤ RISK_PER_TRADE_PCT
        assert 0 < result["suggested_pct"] <= _cfg.RISK_PER_TRADE_PCT


# ---------------------------------------------------------------------------
# record_trade
# ---------------------------------------------------------------------------

class TestRecordTrade:
    def test_increments_counter(self):
        state = RiskState()
        record_trade("AAPL", state)
        assert state.trades_today == 1
        assert "AAPL" in state.open_positions

    def test_no_duplicate_position(self):
        state = RiskState()
        record_trade("AAPL", state)
        record_trade("AAPL", state)
        assert state.open_positions.count("AAPL") == 1
        assert state.trades_today == 2  # still incremented
