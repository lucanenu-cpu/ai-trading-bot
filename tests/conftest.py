"""
conftest.py — Stub out heavy ML/network dependencies so ai_advisor tests
can be collected without numpy / xgboost / yfinance installed.
"""
import sys
from unittest.mock import MagicMock


def _mock_mod(name: str) -> MagicMock:
    m = MagicMock()
    m.__name__ = name
    sys.modules[name] = m
    return m


# Heavy numeric/ML libraries
for _dep in [
    "numpy", "pandas",
    "yfinance",
    "ta", "ta.trend", "ta.momentum", "ta.volatility", "ta.volume",
    "sklearn", "sklearn.model_selection",
    "xgboost",
    "requests",
    "feedparser",
    "bs4", "beautifulsoup4",
]:
    if _dep not in sys.modules:
        _mock_mod(_dep)

# Explicit attribute stubs so `from X import Y` works
sys.modules["sklearn.model_selection"].TimeSeriesSplit = MagicMock()
sys.modules["xgboost"].XGBClassifier = MagicMock()
sys.modules["numpy"].bool_ = bool

# Ensure new config attrs are present so tests that import config early don't fail
import config as _config
if not hasattr(_config, "TRADE_COOLDOWN_SECS"):
    _config.TRADE_COOLDOWN_SECS = 0
if not hasattr(_config, "CHOP_ADX_THRESHOLD"):
    _config.CHOP_ADX_THRESHOLD = 20.0
if not hasattr(_config, "ATR_SL_MULTIPLIER"):
    _config.ATR_SL_MULTIPLIER = 0.0

# Stub market_analyzer and news_sentiment so ai_advisor can be imported
# without triggering the heavy chain.  Tests that need controlled output
# patch ai_advisor.full_analysis / ai_advisor.analyze_news_impact directly.
_ma = _mock_mod("market_analyzer")
_ma.full_analysis = MagicMock(return_value={
    "symbol": "TEST", "price": 100.0,
    "prediction": {"direction": "LONG", "confidence": 75.0, "cv_accuracy": 60.0, "features": {}},
    "indicators": {"rsi": 50.0, "macd": 0.01, "adx": 20.0, "atr": 1.0, "ema_trend": "MIXED"},
})

_ns = _mock_mod("news_sentiment")
_ns.analyze_news_impact = MagicMock(return_value={
    "overall_impact": "LOW",
    "impact_score": 0.1,
    "high_impact_events": [],
    "medium_impact_events": [],
    "article_count": 0,
    "all_articles": [],
})

