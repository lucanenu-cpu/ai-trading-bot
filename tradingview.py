"""
tradingview.py — Lightweight integration with TradingView's public endpoints.

Two capabilities are exposed:

1. :func:`search_symbol` — resolve a free-text query (e.g. ``"tesla"``,
   ``"bitcoin"``, ``"apple stock"``) to a concrete ticker / exchange pair
   via TradingView's symbol-search endpoint.

2. :func:`get_technical_analysis` — pull TradingView's built-in technical
   analysis consensus (``STRONG_BUY`` / ``BUY`` / ``NEUTRAL`` / ``SELL`` /
   ``STRONG_SELL``) via the scanner endpoint.

Both endpoints are public and unauthenticated. Network errors are caught and
surfaced as ``None`` / empty dicts so the caller can gracefully fall back to
purely local analysis.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Public TradingView endpoints
_SYMBOL_SEARCH_URL = "https://symbol-search.tradingview.com/symbol_search/"
_SCANNER_URL_TMPL = "https://scanner.tradingview.com/{screener}/scan"

# Browsers-like headers — TradingView rejects requests without a UA/Referer.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
    "Accept": "application/json",
}

_DEFAULT_TIMEOUT = 8  # seconds

# Words we strip from a free-text user query before sending it to symbol-search.
# The goal is to turn "should I invest in tesla right now?" into "tesla".
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "buy", "by", "can",
    "cumpar", "cumpara", "dau", "de", "do", "eu", "for", "from", "good",
    "hold", "i", "in", "invest", "investesc", "investing", "investment",
    "is", "it", "la", "market", "me", "much", "my", "now", "of", "on",
    "or", "pe", "please", "pret", "price", "put", "right", "sa", "sell",
    "share", "shares", "should", "stock", "stocks", "sunt", "target",
    "tell", "the", "this", "to", "today", "trade", "what", "when",
    "whether", "with", "worth", "would", "you",
}

# ---------------------------------------------------------------------------
# Query normalisation
# ---------------------------------------------------------------------------

def normalize_query(query: str) -> str:
    """Strip filler words from a user query and keep only meaningful tokens.

    >>> normalize_query("Should I invest in Tesla right now?")
    'tesla'
    """
    if not query:
        return ""
    # Keep letters, digits, $ (for e.g. $AAPL) and dashes (for BTC-USD).
    cleaned = re.sub(r"[^A-Za-z0-9$\-\s]", " ", query)
    tokens = [t for t in cleaned.strip().lower().split() if t]
    filtered = [t for t in tokens if t not in _STOP_WORDS]
    if not filtered:
        filtered = tokens  # fall back to the full query if everything was filtered
    # Keep at most 3 tokens — symbol-search works best on short queries.
    return " ".join(filtered[:3]).strip("$").strip()


# ---------------------------------------------------------------------------
# Symbol search
# ---------------------------------------------------------------------------

def search_symbol(query: str) -> Optional[dict]:
    """Resolve a free-text query to a TradingView symbol.

    Returns the first/best match as a dict::

        {
            "symbol":   "AAPL",
            "exchange": "NASDAQ",
            "type":     "stock",     # stock | crypto | forex | index | futures
            "description": "Apple Inc.",
        }

    Returns ``None`` when nothing matches or on network failure.
    """
    cleaned = normalize_query(query)
    if not cleaned:
        return None

    params = {
        "text": cleaned,
        "hl": "1",
        "exchange": "",
        "lang": "en",
        "type": "stock,crypto,index,forex,futures,economic",
        "domain": "production",
    }

    try:
        resp = requests.get(
            _SYMBOL_SEARCH_URL,
            params=params,
            headers=_HEADERS,
            timeout=_DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # requests errors, JSON decode errors, ...
        logger.warning("TradingView symbol search failed for %r: %s", query, exc)
        return None

    # The API can return either a raw list or a dict wrapping a ``symbols`` list.
    matches = data if isinstance(data, list) else data.get("symbols", [])
    if not matches:
        return None

    # Prefer stocks/crypto over exotic types when multiple matches exist.
    preferred_order = ("stock", "crypto", "index", "forex", "futures")
    matches_sorted = sorted(
        matches,
        key=lambda m: preferred_order.index(m.get("type"))
        if m.get("type") in preferred_order
        else len(preferred_order),
    )
    best = matches_sorted[0]

    # TradingView sometimes wraps the ticker in <em>…</em> highlight tags.
    raw_symbol = best.get("symbol", "")
    symbol = re.sub(r"<[^>]+>", "", raw_symbol).upper()

    return {
        "symbol": symbol,
        "exchange": best.get("exchange", "").upper(),
        "type": best.get("type", ""),
        "description": re.sub(r"<[^>]+>", "", best.get("description", "")),
        "currency_code": best.get("currency_code", ""),
    }


# ---------------------------------------------------------------------------
# Technical analysis consensus
# ---------------------------------------------------------------------------

def _recommendation_label(score: float) -> str:
    """Map a TradingView ``Recommend.All`` score (-1..+1) to a label."""
    if score >= 0.5:
        return "STRONG_BUY"
    if score >= 0.1:
        return "BUY"
    if score <= -0.5:
        return "STRONG_SELL"
    if score <= -0.1:
        return "SELL"
    return "NEUTRAL"


def get_technical_analysis(
    symbol: str,
    exchange: str,
    symbol_type: str = "stock",
) -> dict:
    """Fetch TradingView's technical consensus for a given ticker.

    Returns a dict like::

        {
            "recommendation": "BUY",
            "score":          0.33,   # -1..+1
            "source":         "tradingview",
            "screener":       "america",
            "ticker":         "NASDAQ:AAPL",
        }

    On error returns ``{"recommendation": "UNKNOWN", "score": 0.0, ...}``.
    """
    if not symbol or not exchange:
        return {"recommendation": "UNKNOWN", "score": 0.0, "source": "tradingview"}

    screener = "crypto" if symbol_type == "crypto" else "america"
    ticker = f"{exchange}:{symbol}".upper()

    payload = {
        "symbols": {"tickers": [ticker], "query": {"types": []}},
        "columns": ["Recommend.All", "close"],
    }

    try:
        resp = requests.post(
            _SCANNER_URL_TMPL.format(screener=screener),
            json=payload,
            headers=_HEADERS,
            timeout=_DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning(
            "TradingView scanner failed for %s (%s): %s", ticker, screener, exc
        )
        return {
            "recommendation": "UNKNOWN",
            "score": 0.0,
            "source": "tradingview",
            "screener": screener,
            "ticker": ticker,
        }

    rows = data.get("data") or []
    if not rows:
        return {
            "recommendation": "UNKNOWN",
            "score": 0.0,
            "source": "tradingview",
            "screener": screener,
            "ticker": ticker,
        }

    values = rows[0].get("d") or []
    score = float(values[0]) if values and values[0] is not None else 0.0
    close = float(values[1]) if len(values) > 1 and values[1] is not None else None

    return {
        "recommendation": _recommendation_label(score),
        "score": round(score, 3),
        "close": close,
        "source": "tradingview",
        "screener": screener,
        "ticker": ticker,
    }


# ---------------------------------------------------------------------------
# Symbol mapping TradingView → yfinance
# ---------------------------------------------------------------------------

def to_yfinance_symbol(symbol: str, symbol_type: str = "stock") -> str:
    """Map a TradingView ticker to the symbol expected by yfinance.

    TradingView returns crypto pairs like ``BTCUSD`` / ``BTCUSDT`` while
    yfinance uses ``BTC-USD``. Forex pairs like ``EURUSD`` become
    ``EURUSD=X``. Stocks are returned unchanged.
    """
    if not symbol:
        return symbol

    sym = symbol.upper()

    if symbol_type == "crypto":
        # Already hyphenated (e.g. BTC-USD) — leave as-is.
        if "-" in sym:
            return sym
        # Normalise common quote suffixes (USDT/USDC → USD).
        for quote in ("USDT", "USDC", "USD"):
            if sym.endswith(quote) and len(sym) > len(quote):
                base = sym[: -len(quote)]
                return f"{base}-USD"
        return sym

    if symbol_type == "forex":
        if sym.endswith("=X"):
            return sym
        return f"{sym}=X"

    # stocks / indices / futures — yfinance generally accepts the raw ticker.
    return sym
