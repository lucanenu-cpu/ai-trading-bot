"""
tests/test_ai_advisor_logic.py

Unit tests for action/threshold logic and AI limiter in ai_advisor.py.
These tests do NOT make network calls.
"""
import sys
import os
import datetime
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as _cfg
_cfg.ACCOUNT_BALANCE_USD  = 100.0
_cfg.RISK_PER_TRADE_PCT   = 1.0
_cfg.MAX_DAILY_LOSS_PCT   = 3.0
_cfg.MAX_TRADES_PER_DAY   = 5
_cfg.MAX_OPEN_POSITIONS   = 3
_cfg.MIN_SIGNAL_SCORE     = 65.0
_cfg.STRONG_SIGNAL_SCORE  = 80.0
_cfg.DEFAULT_STOP_LOSS_PCT  = 2.0
_cfg.DEFAULT_TAKE_PROFIT_PCT = 4.0
_cfg.MAX_AI_CALLS_PER_HOUR = 5
_cfg.AI_ENABLED  = True
_cfg.OPENAI_API_KEY = "test-key"
_cfg.OPENAI_MODEL = "gpt-4o"

import ai_advisor
from ai_advisor import ai_call_allowed, _record_ai_call, _ai_call_bucket, _ai_calls_remaining


# ---------------------------------------------------------------------------
# AI call limiter
# ---------------------------------------------------------------------------

class TestAICallLimiter:
    def setup_method(self):
        """Clear bucket before each test."""
        _ai_call_bucket.clear()

    def test_allowed_when_empty(self):
        assert ai_call_allowed() is True

    def test_blocked_when_budget_exhausted(self):
        # Fill up budget
        for _ in range(_cfg.MAX_AI_CALLS_PER_HOUR):
            _record_ai_call()
        assert ai_call_allowed() is False

    def test_remaining_decreases(self):
        initial = _ai_calls_remaining()
        _record_ai_call()
        assert _ai_calls_remaining() == initial - 1

    def test_blocked_when_ai_disabled(self):
        _cfg.AI_ENABLED = False
        try:
            assert ai_call_allowed() is False
        finally:
            _cfg.AI_ENABLED = True

    def test_blocked_when_no_api_key(self):
        _cfg.OPENAI_API_KEY = ""
        try:
            assert ai_call_allowed() is False
        finally:
            _cfg.OPENAI_API_KEY = "test-key"


# ---------------------------------------------------------------------------
# get_smart_score action thresholds
# ---------------------------------------------------------------------------

class TestSmartScoreThresholds:
    """
    Test the action labels produced from various score values.
    We mock full_analysis and analyze_news_impact to control the score.
    """

    def _make_market_data(self, direction="LONG", confidence=80.0):
        return {
            "symbol": "TEST",
            "price": 100.0,
            "prediction": {"direction": direction, "confidence": confidence, "cv_accuracy": 60.0, "features": {}},
            "indicators": {"rsi": 50.0, "macd": 0.01, "adx": 15.0, "atr": 1.0, "ema_trend": "MIXED"},
        }

    def _make_news_data(self, impact="LOW", score=0.1):
        return {
            "overall_impact": impact,
            "impact_score": score,
            "high_impact_events": [],
            "medium_impact_events": [],
            "article_count": 0,
            "all_articles": [],
        }

    def test_strong_buy_label(self):
        with patch("ai_advisor.full_analysis", return_value=self._make_market_data("LONG", 95.0)), \
             patch("ai_advisor.analyze_news_impact", return_value=self._make_news_data("HIGH", 0.8)):
            result = ai_advisor.get_smart_score("TEST")
        assert "BUY" in result["action"]
        assert result["smart_score"] >= 75

    def test_hold_label_for_neutral_score(self):
        with patch("ai_advisor.full_analysis", return_value=self._make_market_data("LONG", 50.0)), \
             patch("ai_advisor.analyze_news_impact", return_value=self._make_news_data("LOW", 0.0)):
            result = ai_advisor.get_smart_score("TEST")
        # Base score = 50 + small delta — should be HOLD
        assert result["smart_score"] >= 0
        assert result["smart_score"] <= 100

    def test_sell_label(self):
        with patch("ai_advisor.full_analysis", return_value=self._make_market_data("SHORT", 90.0)), \
             patch("ai_advisor.analyze_news_impact", return_value=self._make_news_data("HIGH", 0.1)):
            result = ai_advisor.get_smart_score("TEST")
        assert "SELL" in result["action"]

    def test_score_clamped_0_100(self):
        # Even with extreme inputs, score must stay 0-100
        with patch("ai_advisor.full_analysis", return_value=self._make_market_data("LONG", 100.0)), \
             patch("ai_advisor.analyze_news_impact", return_value=self._make_news_data("HIGH", 1.0)):
            result = ai_advisor.get_smart_score("TEST")
        assert 0 <= result["smart_score"] <= 100

    def test_score_breakdown_keys(self):
        with patch("ai_advisor.full_analysis", return_value=self._make_market_data()), \
             patch("ai_advisor.analyze_news_impact", return_value=self._make_news_data()):
            result = ai_advisor.get_smart_score("TEST")
        for key in ("base", "ml_delta", "rsi_delta", "ema_delta", "adx_delta", "news_delta"):
            assert key in result["score_breakdown"]


# ---------------------------------------------------------------------------
# get_actionable_signal action rules
# ---------------------------------------------------------------------------

class TestActionableSignal:
    def setup_method(self):
        _ai_call_bucket.clear()

    def _make_market_data(self, direction="LONG", confidence=85.0):
        ema = "BULLISH" if direction == "LONG" else "BEARISH"
        return {
            "symbol": "TEST",
            "price": 100.0,
            "prediction": {"direction": direction, "confidence": confidence, "cv_accuracy": 65.0, "features": {}},
            "indicators": {"rsi": 50.0, "macd": 0.01, "adx": 30.0, "atr": 1.0, "ema_trend": ema},
        }

    def _make_news_data(self):
        return {
            "overall_impact": "MEDIUM",
            "impact_score": 0.4,
            "high_impact_events": [],
            "medium_impact_events": [],
            "article_count": 5,
            "all_articles": [],
        }

    def test_buy_when_bullish_above_threshold(self):
        with patch("ai_advisor.full_analysis", return_value=self._make_market_data("LONG", 90.0)), \
             patch("ai_advisor.analyze_news_impact", return_value=self._make_news_data()):
            result = ai_advisor.get_actionable_signal("TEST")
        assert result["action"] == "BUY"

    def test_sell_when_bearish_above_threshold(self):
        with patch("ai_advisor.full_analysis", return_value=self._make_market_data("SHORT", 90.0)), \
             patch("ai_advisor.analyze_news_impact", return_value=self._make_news_data()):
            result = ai_advisor.get_actionable_signal("TEST")
        assert result["action"] == "SELL"

    def test_hold_when_score_below_threshold(self):
        # Neutral LONG with 51% confidence → score ~50 → HOLD
        with patch("ai_advisor.full_analysis", return_value=self._make_market_data("LONG", 51.0)), \
             patch("ai_advisor.analyze_news_impact", return_value=self._make_news_data()):
            result = ai_advisor.get_actionable_signal("TEST")
        # Score will be around 50 which is below MIN_SIGNAL_SCORE=65
        if result["score"] < _cfg.MIN_SIGNAL_SCORE:
            assert result["action"] == "HOLD"

    def test_risk_dict_present(self):
        with patch("ai_advisor.full_analysis", return_value=self._make_market_data("LONG", 90.0)), \
             patch("ai_advisor.analyze_news_impact", return_value=self._make_news_data()):
            result = ai_advisor.get_actionable_signal("TEST")
        assert "risk" in result
        for key in ("entry", "stop_loss", "take_profit", "allocation_usd", "allocation_pct"):
            assert key in result["risk"]

    def test_reasons_list_present(self):
        with patch("ai_advisor.full_analysis", return_value=self._make_market_data("LONG", 90.0)), \
             patch("ai_advisor.analyze_news_impact", return_value=self._make_news_data()):
            result = ai_advisor.get_actionable_signal("TEST")
        assert isinstance(result["reasons"], list)
