"""
tests/test_server_chart.py

Tests for the /api/chart-data/<symbol> endpoint added to server.py.
"""
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Stub heavy deps before importing server (conftest already handles most)
# ---------------------------------------------------------------------------
for _dep in ["scheduler", "notifications"]:
    if _dep not in sys.modules:
        m = MagicMock()
        m.__name__ = _dep
        sys.modules[_dep] = m

# Prevent scheduler from starting during import
sys.modules["scheduler"].start_scheduler_thread = MagicMock()
sys.modules["scheduler"].WATCHLIST = ["AAPL"]
sys.modules["notifications"].send_telegram = MagicMock(return_value=True)


def _make_mock_df(closes):
    """Build a minimal mock DataFrame compatible with fetch_market_data output."""
    import pandas as pd
    import datetime

    dates = [datetime.date(2024, 1, i + 1) for i in range(len(closes))]
    df = MagicMock()
    df.empty = False
    df.index = dates
    df.__getitem__ = lambda self, key: (
        [float(c) for c in closes] if key == "Close" else []
    )
    return df


class TestChartDataEndpoint:
    """Tests for GET /api/chart-data/<symbol>."""

    def _get_client(self):
        import server
        server.app.config["TESTING"] = True
        return server.app.test_client()

    def test_success_returns_dates_and_closes(self):
        import pandas as pd
        import datetime

        closes = [100.0, 101.5, 99.8, 103.2]
        dates = [datetime.date(2024, 1, i + 1) for i in range(len(closes))]

        mock_df = MagicMock()
        mock_df.empty = False
        mock_df.index = dates

        # Simulate df["Close"] returning a list-like of floats
        mock_df.__getitem__ = lambda self, key: closes if key == "Close" else []

        with patch("market_analyzer.fetch_market_data", return_value=mock_df):
            client = self._get_client()
            resp = client.get("/api/chart-data/AAPL")
            data = resp.get_json()

        assert resp.status_code == 200
        assert data["success"] is True
        assert data["symbol"] == "AAPL"
        assert "dates" in data
        assert "closes" in data
        assert len(data["dates"]) == len(closes)
        assert len(data["closes"]) == len(closes)

    def test_symbol_uppercased(self):
        closes = [150.0, 151.0]
        import datetime
        dates = [datetime.date(2024, 1, i + 1) for i in range(len(closes))]

        mock_df = MagicMock()
        mock_df.empty = False
        mock_df.index = dates
        mock_df.__getitem__ = lambda self, key: closes if key == "Close" else []

        with patch("market_analyzer.fetch_market_data", return_value=mock_df):
            client = self._get_client()
            resp = client.get("/api/chart-data/aapl")
            data = resp.get_json()

        assert data["symbol"] == "AAPL"

    def test_empty_dataframe_returns_404(self):
        mock_df = MagicMock()
        mock_df.empty = True

        with patch("market_analyzer.fetch_market_data", return_value=mock_df):
            client = self._get_client()
            resp = client.get("/api/chart-data/UNKNOWN")
            data = resp.get_json()

        assert resp.status_code == 404
        assert data["success"] is False

    def test_fetch_exception_returns_500(self):
        with patch("market_analyzer.fetch_market_data", side_effect=RuntimeError("network error")):
            client = self._get_client()
            resp = client.get("/api/chart-data/FAIL")
            data = resp.get_json()

        assert resp.status_code == 500
        assert data["success"] is False

    def test_dates_formatted_as_yyyy_mm_dd(self):
        import datetime
        closes = [200.0, 201.0]
        dates = [datetime.date(2024, 3, 15), datetime.date(2024, 3, 16)]

        mock_df = MagicMock()
        mock_df.empty = False
        mock_df.index = dates
        mock_df.__getitem__ = lambda self, key: closes if key == "Close" else []

        with patch("market_analyzer.fetch_market_data", return_value=mock_df):
            client = self._get_client()
            resp = client.get("/api/chart-data/SPY")
            data = resp.get_json()

        assert data["dates"] == ["2024-03-15", "2024-03-16"]
