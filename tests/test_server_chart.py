"""
tests/test_server_chart.py

Unit tests for the GET /chart/<symbol> endpoint in server.py.
Heavy deps (yfinance, numpy, pandas, …) are already stubbed by conftest.py.
"""
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch config before importing server so the scheduler doesn't start and
# Telegram/OpenAI credentials don't matter.
import config as _cfg
_cfg.TELEGRAM_BOT_TOKEN = ""
_cfg.TELEGRAM_CHAT_ID = ""
_cfg.AI_ENABLED = False
_cfg.OPENAI_API_KEY = ""

# Stub scheduler so it doesn't actually start background threads.
from unittest.mock import MagicMock as _MM
sys.modules.setdefault("scheduler", _MM())

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_hist(prices):
    """Return a minimal fake DataFrame-like object for yfinance.history()."""
    import datetime

    class _Row:
        def __init__(self, i, price):
            self.Open   = price * 0.99
            self.High   = price * 1.01
            self.Low    = price * 0.98
            self.Close  = price
            self.Volume = 1_000_000

        def get(self, key, default=None):
            return getattr(self, key, default)

        def __getitem__(self, key):
            return getattr(self, key)

    class _FakeHist:
        def __init__(self, prices):
            self._data = [
                (
                    datetime.datetime(2024, 1, 1, 0, i, tzinfo=datetime.timezone.utc),
                    _Row(i, p),
                )
                for i, p in enumerate(prices)
            ]
            self.empty = len(prices) == 0

        def iterrows(self):
            return iter(self._data)

    return _FakeHist(prices)


@pytest.fixture()
def client():
    """Flask test client with scheduler + notifications patched out."""
    with patch("scheduler.start_scheduler_thread"), \
         patch("notifications.send_telegram", return_value=True):
        # Import server fresh inside the patch context so _boot_scheduler runs
        # but is harmless.
        import importlib
        import server as srv
        importlib.reload(srv)
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            yield c


# ---------------------------------------------------------------------------
# /chart/<symbol> happy-path tests
# ---------------------------------------------------------------------------

class TestChartEndpoint:
    def test_returns_success_and_candles(self, client):
        fake_hist = _make_fake_hist([100.0, 101.0, 102.0])
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = fake_hist

        with patch("yfinance.Ticker", return_value=mock_ticker):
            resp = client.get("/chart/AAPL")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["symbol"] == "AAPL"
        assert data["candle_count"] == 3
        assert len(data["candles"]) == 3
        assert "current_price" in data

    def test_candle_fields_present(self, client):
        fake_hist = _make_fake_hist([150.0])
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = fake_hist

        with patch("yfinance.Ticker", return_value=mock_ticker):
            resp = client.get("/chart/TSLA")

        data = resp.get_json()
        candle = data["candles"][0]
        for field in ("time", "open", "high", "low", "close", "volume"):
            assert field in candle, f"Missing field: {field}"

    def test_symbol_uppercased(self, client):
        fake_hist = _make_fake_hist([200.0, 201.0])
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = fake_hist

        with patch("yfinance.Ticker", return_value=mock_ticker):
            resp = client.get("/chart/aapl")

        data = resp.get_json()
        assert data["symbol"] == "AAPL"

    def test_interval_parameter_passed_through(self, client):
        fake_hist = _make_fake_hist([300.0])
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = fake_hist

        with patch("yfinance.Ticker", return_value=mock_ticker):
            resp = client.get("/chart/SPY?interval=D")

        data = resp.get_json()
        assert data["success"] is True
        assert data["interval"] == "D"

    def test_default_interval_is_60(self, client):
        fake_hist = _make_fake_hist([500.0])
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = fake_hist

        with patch("yfinance.Ticker", return_value=mock_ticker):
            resp = client.get("/chart/BTC-USD")

        data = resp.get_json()
        assert data["interval"] == "60"

    def test_current_price_equals_last_close(self, client):
        prices = [100.0, 110.0, 120.0]
        fake_hist = _make_fake_hist(prices)
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = fake_hist

        with patch("yfinance.Ticker", return_value=mock_ticker):
            resp = client.get("/chart/AAPL")

        data = resp.get_json()
        assert data["current_price"] == pytest.approx(prices[-1], rel=1e-4)

    def test_empty_history_returns_404(self, client):
        fake_hist = _make_fake_hist([])  # empty
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = fake_hist

        with patch("yfinance.Ticker", return_value=mock_ticker):
            resp = client.get("/chart/UNKNOWN")

        assert resp.status_code == 404
        data = resp.get_json()
        assert data["success"] is False

    def test_yfinance_exception_returns_500(self, client):
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = RuntimeError("network error")

        with patch("yfinance.Ticker", return_value=mock_ticker):
            resp = client.get("/chart/ERR")

        assert resp.status_code == 500
        data = resp.get_json()
        assert data["success"] is False

    def test_response_includes_period(self, client):
        fake_hist = _make_fake_hist([80.0])
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = fake_hist

        with patch("yfinance.Ticker", return_value=mock_ticker):
            resp = client.get("/chart/AAPL?interval=W")

        data = resp.get_json()
        assert "period" in data

    def test_custom_period_override(self, client):
        fake_hist = _make_fake_hist([90.0])
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = fake_hist

        with patch("yfinance.Ticker", return_value=mock_ticker) as mock_yf:
            resp = client.get("/chart/AAPL?interval=D&period=3mo")

        data = resp.get_json()
        assert data["success"] is True
        assert data["period"] == "3mo"
