import datetime
import logging
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
import risk_manager

logger = logging.getLogger(__name__)

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
        now_et = datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=5)
        return now_et.weekday() < 5 and 9 <= now_et.hour < 16
    now_et = datetime.datetime.now(tz)
    if now_et.weekday() >= 5:
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

    Uses the new actionable signal engine with risk gate integration.
    Sends BUY/SELL alerts only; skips HOLD unless signal is strong.
    """
    from ai_advisor import get_actionable_signal

    risk_manager.reset_daily_if_needed()

    for symbol in WATCHLIST:
        if not is_crypto(symbol) and not is_market_hours():
            continue

        try:
            signal = get_actionable_signal(symbol)
            action = signal["action"]
            score = signal["score"]

            logger.info(
                "Scan: %s action=%s score=%.1f confidence=%.1f",
                symbol, action, score, signal.get("confidence", 0),
            )

            if action == "HOLD":
                reasons_str = "; ".join(signal.get("reasons", [])[:2])
                logger.info("Scan: skipping %s (HOLD) — %s", symbol, reasons_str)
                continue

            if not _cooldown_ok(symbol):
                logger.info("Scan: skipping %s — cooldown active", symbol)
                continue

            # Build analysis payload compatible with send_trade_alert
            analysis = {
                "price": signal["price"],
                "prediction": {
                    "direction": "LONG" if action == "BUY" else "SHORT",
                    "confidence": signal.get("confidence", 0),
                    "cv_accuracy": 0,
                },
                "indicators": signal.get("indicators", {}),
                "news": {"overall_impact": signal.get("news_impact", "LOW"), "impact_score": 0},
                "recommendation": _build_action_summary(signal),
                # New structured fields for updated formatter
                "signal": signal,
            }

            send_trade_alert(symbol, analysis)
            _alert_cooldowns[symbol] = datetime.datetime.now(timezone.utc)
            risk_manager.record_trade(symbol)

        except Exception as exc:
            logger.error("Scan error for %s: %s", symbol, exc)
            send_alert(f"⚠️ Error scanning {symbol}: {exc}", urgent=False)


def _build_action_summary(signal: dict) -> str:
    """Build a concise text summary of an actionable signal for legacy formatters."""
    r = signal.get("risk", {})
    lines = [
        f"Action: {signal['action']}",
        f"Score: {signal['score']:.0f}/100",
        f"Entry: ${r.get('entry', signal['price']):.2f}",
        f"Stop-Loss: ${r.get('stop_loss', 0):.2f} (-{r.get('stop_loss_pct', 0):.1f}%)",
        f"Take-Profit: ${r.get('take_profit', 0):.2f} (+{r.get('take_profit_pct', 0):.1f}%)",
        f"Suggested: ${r.get('allocation_usd', 0):.2f} ({r.get('allocation_pct', 0):.1f}% of balance)",
    ]
    return "\n".join(lines)


def scan_news() -> None:
    """Check all watchlist symbols for high-impact news events."""
    for symbol in WATCHLIST:
        try:
            news_data = analyze_news_impact(symbol)
            for event in news_data.get("high_impact_events", []):
                title = event.get("title", "").strip()
                if title and title not in _alerted_news_titles:
                    _alerted_news_titles.add(title)
                    send_news_alert(event)
        except Exception as exc:
            logger.error("News scan error for %s: %s", symbol, exc)
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
    logger.info("Scheduler thread started")
