"""
tests/test_tradingview.py

Unit tests for the TradingView integration and the auto-analysis flow.
All network calls are mocked.
"""
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The `requests` module is replaced with a MagicMock in conftest.py — that's
# fine for our purposes because we patch tradingview.requests directly in each
# test below.

import tradingview


# ---------------------------------------------------------------------------
# normalize_query
# ---------------------------------------------------------------------------

class TestNormalizeQuery:
    def test_strips_filler_words(self):
        assert tradingview.normalize_query("Should I invest in Tesla right now?") == "tesla"

    def test_handles_ticker_dollar_prefix(self):
        # Dollar sign is kept during cleanup then stripped from the final result.
        assert tradingview.normalize_query("$AAPL") == "aapl"

    def test_romanian_query(self):
        # "ar trebui sa cumpar bitcoin" → "bitcoin" (stop words stripped)
        result = tradingview.normalize_query("ar trebui sa cumpar bitcoin")
        assert "bitcoin" in result

    def test_empty_query(self):
        assert tradingview.normalize_query("") == ""
        assert tradingview.normalize_query("   ") == ""

    def test_keeps_hyphen(self):
        assert tradingview.normalize_query("BTC-USD") == "btc-usd"

    def test_fallback_when_all_stopwords(self):
        # When every token is a stop word, we fall back to returning them all
        # rather than an empty string.
        result = tradingview.normalize_query("buy sell hold")
        assert result  # non-empty


# ---------------------------------------------------------------------------
# _recommendation_label
# ---------------------------------------------------------------------------

class TestRecommendationLabel:
    def test_strong_buy(self):
        assert tradingview._recommendation_label(0.7) == "STRONG_BUY"
        assert tradingview._recommendation_label(0.5) == "STRONG_BUY"

    def test_buy(self):
        assert tradingview._recommendation_label(0.3) == "BUY"
        assert tradingview._recommendation_label(0.1) == "BUY"

    def test_neutral(self):
        assert tradingview._recommendation_label(0.0) == "NEUTRAL"
        assert tradingview._recommendation_label(0.05) == "NEUTRAL"
        assert tradingview._recommendation_label(-0.05) == "NEUTRAL"

    def test_sell(self):
        assert tradingview._recommendation_label(-0.3) == "SELL"
        assert tradingview._recommendation_label(-0.1) == "SELL"

    def test_strong_sell(self):
        assert tradingview._recommendation_label(-0.7) == "STRONG_SELL"
        assert tradingview._recommendation_label(-0.5) == "STRONG_SELL"


# ---------------------------------------------------------------------------
# to_yfinance_symbol
# ---------------------------------------------------------------------------

class TestYFinanceMapping:
    def test_stock_unchanged(self):
        assert tradingview.to_yfinance_symbol("AAPL", "stock") == "AAPL"
        assert tradingview.to_yfinance_symbol("tsla", "stock") == "TSLA"

    def test_crypto_usdt_stripped(self):
        assert tradingview.to_yfinance_symbol("BTCUSDT", "crypto") == "BTC-USD"

    def test_crypto_usd_appended(self):
        assert tradingview.to_yfinance_symbol("ETHUSD", "crypto") == "ETH-USD"

    def test_crypto_already_hyphenated(self):
        assert tradingview.to_yfinance_symbol("BTC-USD", "crypto") == "BTC-USD"

    def test_forex(self):
        assert tradingview.to_yfinance_symbol("EURUSD", "forex") == "EURUSD=X"
        # Idempotent
        assert tradingview.to_yfinance_symbol("EURUSD=X", "forex") == "EURUSD=X"


# ---------------------------------------------------------------------------
# search_symbol (network mocked)
# ---------------------------------------------------------------------------

def _mock_response(json_data, status=200):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    resp.status_code = status
    return resp


class TestSearchSymbol:
    def test_returns_first_match(self):
        with patch.object(tradingview, "requests") as mock_req:
            mock_req.get.return_value = _mock_response([
                {"symbol": "AAPL", "exchange": "NASDAQ", "type": "stock",
                 "description": "Apple Inc.", "currency_code": "USD"},
            ])
            result = tradingview.search_symbol("apple")
        assert result["symbol"] == "AAPL"
        assert result["exchange"] == "NASDAQ"
        assert result["type"] == "stock"

    def test_prefers_stock_over_other_types(self):
        with patch.object(tradingview, "requests") as mock_req:
            mock_req.get.return_value = _mock_response([
                {"symbol": "AAPL", "exchange": "NASDAQ", "type": "futures", "description": ""},
                {"symbol": "AAPL", "exchange": "NASDAQ", "type": "stock", "description": "Apple"},
            ])
            result = tradingview.search_symbol("apple")
        assert result["type"] == "stock"

    def test_strips_html_highlight_tags(self):
        with patch.object(tradingview, "requests") as mock_req:
            mock_req.get.return_value = _mock_response([
                {"symbol": "<em>AAPL</em>", "exchange": "NASDAQ", "type": "stock",
                 "description": "<em>Apple</em> Inc."},
            ])
            result = tradingview.search_symbol("apple")
        assert result["symbol"] == "AAPL"
        assert "<em>" not in result["description"]

    def test_empty_query_returns_none(self):
        assert tradingview.search_symbol("") is None
        assert tradingview.search_symbol("   ") is None

    def test_network_error_returns_none(self):
        with patch.object(tradingview, "requests") as mock_req:
            mock_req.get.side_effect = Exception("boom")
            assert tradingview.search_symbol("apple") is None

    def test_empty_result_returns_none(self):
        with patch.object(tradingview, "requests") as mock_req:
            mock_req.get.return_value = _mock_response([])
            assert tradingview.search_symbol("zzzzz") is None

    def test_handles_dict_wrapper(self):
        with patch.object(tradingview, "requests") as mock_req:
            mock_req.get.return_value = _mock_response({"symbols": [
                {"symbol": "AAPL", "exchange": "NASDAQ", "type": "stock", "description": "Apple"},
            ]})
            result = tradingview.search_symbol("apple")
        assert result["symbol"] == "AAPL"


# ---------------------------------------------------------------------------
# get_technical_analysis (network mocked)
# ---------------------------------------------------------------------------

class TestGetTechnicalAnalysis:
    def test_buy_score(self):
        with patch.object(tradingview, "requests") as mock_req:
            mock_req.post.return_value = _mock_response({
                "data": [{"s": "NASDAQ:AAPL", "d": [0.35, 180.0]}],
            })
            result = tradingview.get_technical_analysis("AAPL", "NASDAQ", "stock")
        assert result["recommendation"] == "BUY"
        assert result["score"] == 0.35
        assert result["close"] == 180.0
        assert result["screener"] == "america"

    def test_crypto_uses_crypto_screener(self):
        with patch.object(tradingview, "requests") as mock_req:
            mock_req.post.return_value = _mock_response({
                "data": [{"s": "BINANCE:BTCUSDT", "d": [-0.6, 42000.0]}],
            })
            result = tradingview.get_technical_analysis("BTCUSDT", "BINANCE", "crypto")
        assert result["recommendation"] == "STRONG_SELL"
        assert result["screener"] == "crypto"

    def test_missing_inputs(self):
        result = tradingview.get_technical_analysis("", "NASDAQ", "stock")
        assert result["recommendation"] == "UNKNOWN"

    def test_network_error(self):
        with patch.object(tradingview, "requests") as mock_req:
            mock_req.post.side_effect = Exception("boom")
            result = tradingview.get_technical_analysis("AAPL", "NASDAQ", "stock")
        assert result["recommendation"] == "UNKNOWN"
        assert result["score"] == 0.0

    def test_empty_data(self):
        with patch.object(tradingview, "requests") as mock_req:
            mock_req.post.return_value = _mock_response({"data": []})
            result = tradingview.get_technical_analysis("AAPL", "NASDAQ", "stock")
        assert result["recommendation"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# get_auto_analysis (integration with ai_advisor, TradingView mocked)
# ---------------------------------------------------------------------------

# Ensure config defaults match other tests. Keep these identical to the values
# set in tests/test_ai_advisor_logic.py so there is no conflict at collection
# time regardless of the order pytest loads modules.
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
_cfg.MAX_AI_CALLS_PER_HOUR = 5
_cfg.AI_ENABLED = True
_cfg.OPENAI_API_KEY = "test-key"
_cfg.OPENAI_MODEL = "gpt-4o"

import ai_advisor


class TestGetAutoAnalysis:
    def _mk_signal(self, action="HOLD", score=50.0, reasons=None):
        return {
            "symbol": "AAPL",
            "price": 180.0,
            "action": action,
            "confidence": 70,
            "score": score,
            "score_breakdown": {},
            "reasons": reasons if reasons is not None else ["base reason"],
            "risk": {
                "entry": 180.0, "stop_loss": 176.4, "take_profit": 187.2,
                "stop_loss_pct": 2.0, "take_profit_pct": 4.0,
                "allocation_usd": 10.0, "allocation_pct": 10.0, "quantity": 0.055,
            },
            "ai_used": False,
            "ai_calls_remaining": 5,
            "news_impact": "LOW",
            "indicators": {},
        }

    def test_empty_query_returns_error(self):
        result = ai_advisor.get_auto_analysis("")
        assert result["success"] is False
        assert "Empty" in result["error"]

    def test_unresolved_query_returns_error(self):
        with patch("tradingview.search_symbol", return_value=None):
            result = ai_advisor.get_auto_analysis("zzz random text")
        assert result["success"] is False
        assert "TradingView" in result["error"]

    def test_happy_path_returns_signal_and_tv(self):
        match = {
            "symbol": "AAPL", "exchange": "NASDAQ", "type": "stock",
            "description": "Apple Inc.", "currency_code": "USD",
        }
        tv = {
            "recommendation": "BUY", "score": 0.3, "close": 180.0,
            "source": "tradingview", "screener": "america", "ticker": "NASDAQ:AAPL",
        }
        with patch("tradingview.search_symbol", return_value=match), \
             patch("tradingview.get_technical_analysis", return_value=tv), \
             patch("ai_advisor.get_actionable_signal",
                   return_value=self._mk_signal(action="BUY", score=75.0)):
            result = ai_advisor.get_auto_analysis("apple stock")

        assert result["success"] is True
        assert result["query"] == "apple stock"
        assert result["resolved"]["symbol"] == "AAPL"
        assert result["resolved"]["yfinance_symbol"] == "AAPL"
        assert result["tradingview"]["recommendation"] == "BUY"
        assert any("TradingView consensus" in r for r in result["reasons"])
        assert result["action"] == "BUY"

    def test_crypto_query_maps_to_yfinance(self):
        match = {"symbol": "BTCUSDT", "exchange": "BINANCE", "type": "crypto",
                 "description": "Bitcoin", "currency_code": "USD"}
        tv = {"recommendation": "STRONG_BUY", "score": 0.7, "close": 42000.0,
              "source": "tradingview", "screener": "crypto", "ticker": "BINANCE:BTCUSDT"}

        captured = {}

        def fake_signal(symbol):
            captured["symbol"] = symbol
            return self._mk_signal(action="HOLD", score=60.0)

        with patch("tradingview.search_symbol", return_value=match), \
             patch("tradingview.get_technical_analysis", return_value=tv), \
             patch("ai_advisor.get_actionable_signal", side_effect=fake_signal):
            result = ai_advisor.get_auto_analysis("should I invest in bitcoin?")

        # Crypto ticker should be converted for yfinance consumption.
        assert captured["symbol"] == "BTC-USD"
        assert result["resolved"]["yfinance_symbol"] == "BTC-USD"
        # STRONG_BUY consensus + near-threshold score (60 ≥ 55) should flip HOLD→BUY.
        assert result["action"] == "BUY"

    def test_strong_sell_tips_hold_to_sell(self):
        match = {"symbol": "XYZ", "exchange": "NASDAQ", "type": "stock",
                 "description": "XYZ", "currency_code": "USD"}
        tv = {"recommendation": "STRONG_SELL", "score": -0.7, "close": 10.0,
              "source": "tradingview", "screener": "america", "ticker": "NASDAQ:XYZ"}
        # bearish_score = 100 - 40 = 60, which is >= MIN_SIGNAL_SCORE - 10 = 55
        with patch("tradingview.search_symbol", return_value=match), \
             patch("tradingview.get_technical_analysis", return_value=tv), \
             patch("ai_advisor.get_actionable_signal",
                   return_value=self._mk_signal(action="HOLD", score=40.0)):
            result = ai_advisor.get_auto_analysis("is XYZ a good buy?")
        assert result["action"] == "SELL"

    def test_unknown_tv_does_not_add_reason(self):
        match = {"symbol": "AAPL", "exchange": "NASDAQ", "type": "stock",
                 "description": "Apple", "currency_code": "USD"}
        tv = {"recommendation": "UNKNOWN", "score": 0.0,
              "source": "tradingview", "screener": "america", "ticker": "NASDAQ:AAPL"}
        with patch("tradingview.search_symbol", return_value=match), \
             patch("tradingview.get_technical_analysis", return_value=tv), \
             patch("ai_advisor.get_actionable_signal",
                   return_value=self._mk_signal(action="HOLD", score=50.0)):
            result = ai_advisor.get_auto_analysis("apple")
        assert result["success"] is True
        assert not any("TradingView consensus" in r for r in result["reasons"])
