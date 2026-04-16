import datetime
import threading
import time
from datetime import timezone
from typing import Optional
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

from market_analyzer import full_analysis
from news_sentiment import analyze_news_impact
from notifications import send_alert, send_trade_alert, send_news_alert

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WATCHLIST = [
    "AAPL", "TSLA", "MSFT", "NVDA", "AMZN",
    "META", "GOOGL", "BTC-USD", "ETH-USD", "SPY", "QQQ",
]

SCAN_INTERVAL_MINUTES = 30
NEWS_INTERVAL_MINUTES = 10

# Cooldown tracking: {symbol: last_alert_datetime}
_alert_cooldowns: dict = {}
_alerted_news_titles: set = set()

_CRYPTO_SYMBOLS = {"BTC-USD", "ETH-USD"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_market_hours() -> bool:
    """Return True if current time falls within US market hours (Mon‑Fri 9–16 ET), DST‑aware."""
    try:
        tz = ZoneInfo("America/New_York")
    except Exception:
        # Fallback: approximate with UTC-5 if zoneinfo unavailable
        now_et = datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=5)
        return now_et.weekday() < 5 and 9 <= now_et.hour < 16
    now_et = datetime.datetime.now(tz)
    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return 9 <= now_et.hour < 16


def is_crypto(symbol: str) -> bool:
    """Return True if the symbol is a crypto asset."""
    return symbol in _CRYPTO_SYMBOLS or symbol.endswith("-USD")


def _cooldown_ok(symbol: str, hours: int = 4) -> bool:
    """Return True if enough time has passed since the last alert for this symbol."""
    last = _alert_cooldowns.get(symbol)
    if last is None:
        return True
    return (datetime.datetime.now(timezone.utc) - last).total_seconds() >= hours * 3600


# ---------------------------------------------------------------------------
# Scan routines
# ---------------------------------------------------------------------------

def scan_markets() -> None:
    """
    Analyze each symbol in the watchlist and send alerts for strong signals.

    Alert criteria:
    - AI direction and news impact aligned with confidence > 70 %, OR
    - Model confidence > 80 % regardless of news
    - 4‑hour per‑symbol cooldown
    """
    for symbol in WATCHLIST:
        # Crypto trades 24/7; equities only during market hours
        if not is_crypto(symbol) and not is_market_hours():
            continue

        try:
            market_data = full_analysis(symbol)
            news_data = analyze_news_impact(symbol)

            pred = market_data["prediction"]
            confidence = pred.get("confidence", 0)
            direction = pred.get("direction", "")
            overall_impact = news_data.get("overall_impact", "LOW")

            # Determine if news and ML are aligned
            news_bullish = overall_impact in ("HIGH", "MEDIUM") and any(
                ev.get("deep_analysis", {}).get("impact_direction") == "BULLISH"
                for ev in news_data.get("high_impact_events", [])
            )
            news_bearish = overall_impact in ("HIGH", "MEDIUM") and any(
                ev.get("deep_analysis", {}).get("impact_direction") == "BEARISH"
                for ev in news_data.get("high_impact_events", [])
            )

            aligned = (
                (direction == "LONG" and news_bullish) or
                (direction == "SHORT" and news_bearish)
            )

            should_alert = (
                (aligned and confidence > 70) or
                (confidence > 80)
            )

            if should_alert and _cooldown_ok(symbol):
                analysis = {
                    **market_data,
                    "news": news_data,
                    "recommendation": f"{direction} signal with {confidence:.1f}% confidence",
                }
                send_trade_alert(symbol, analysis)
                _alert_cooldowns[symbol] = datetime.datetime.now(timezone.utc)

        except Exception as exc:
            send_alert(f"⚠️ Error scanning {symbol}: {exc}", urgent=False)


def scan_news() -> None:
    """Check all watchlist symbols for high‑impact news events."""
    for symbol in WATCHLIST:
        try:
            news_data = analyze_news_impact(symbol)
            for event in news_data.get("high_impact_events", []):
                title = event.get("title", "").strip()
                if title and title not in _alerted_news_titles:
                    _alerted_news_titles.add(title)
                    send_news_alert(event)
        except Exception as exc:
            send_alert(f"⚠️ Error scanning news for {symbol}: {exc}", urgent=False)


# ---------------------------------------------------------------------------
# Main scheduler loop
# ---------------------------------------------------------------------------

def run_scheduler() -> None:
    """Blocking loop that runs market and news scans on their respective intervals."""
    send_alert(
        "🤖 <b>AI Trading Bot started!</b>\n"
        f"📋 Watching: {', '.join(WATCHLIST)}\n"
        f"⏱ Market scan every {SCAN_INTERVAL_MINUTES} min | "
        f"News scan every {NEWS_INTERVAL_MINUTES} min"
    )

    last_market_scan = datetime.datetime.min.replace(tzinfo=timezone.utc)
    last_news_scan = datetime.datetime.min.replace(tzinfo=timezone.utc)

    while True:
        now = datetime.datetime.now(timezone.utc)

        if (now - last_market_scan).total_seconds() >= SCAN_INTERVAL_MINUTES * 60:
            scan_markets()
            last_market_scan = now

        if (now - last_news_scan).total_seconds() >= NEWS_INTERVAL_MINUTES * 60:
            scan_news()
            last_news_scan = now

        time.sleep(60)


# ---------------------------------------------------------------------------
# Daemon thread launcher
# ---------------------------------------------------------------------------

_scheduler_thread: Optional[threading.Thread] = None
_scheduler_started = False


def start_scheduler_thread() -> None:
    """Start the scheduler as a background daemon thread (idempotent)."""
    global _scheduler_thread, _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    _scheduler_thread = threading.Thread(target=run_scheduler, daemon=True, name="scheduler")
    _scheduler_thread.start()
