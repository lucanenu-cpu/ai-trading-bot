import datetime
import logging
import re
import requests
from datetime import timezone

import config

logger = logging.getLogger(__name__)

try:
    from twilio.rest import Client as TwilioClient
    _twilio_available = True
except ImportError:
    _twilio_available = False


# ---------------------------------------------------------------------------
# Low‑level senders
# ---------------------------------------------------------------------------

def send_telegram(message: str, parse_mode: str = "HTML") -> bool:
    """Send a message via Telegram Bot API. Returns True on success."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured: token=%s, chat_id=%s",
                       bool(config.TELEGRAM_BOT_TOKEN), bool(config.TELEGRAM_CHAT_ID))
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": parse_mode,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error("Telegram API error: %s %s", resp.status_code, resp.text)
        else:
            logger.info("Telegram message sent successfully")
        return resp.status_code == 200
    except Exception as e:
        logger.error("Telegram send failed: %s", e)
        return False


def send_sms(message: str) -> bool:
    """Send an SMS via Twilio (optional). Returns True on success."""
    if not _twilio_available:
        return False
    if not all([config.TWILIO_SID, config.TWILIO_AUTH_TOKEN,
                config.TWILIO_FROM, config.TWILIO_TO]):
        return False
    try:
        client = TwilioClient(config.TWILIO_SID, config.TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=message,
            from_=config.TWILIO_FROM,
            to=config.TWILIO_TO,
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def format_actionable_signal(symbol: str, signal: dict) -> str:
    """
    Return an HTML-formatted Telegram message for an actionable BUY/SELL/HOLD signal.

    signal is the dict returned by ai_advisor.get_actionable_signal().
    """
    action = signal.get("action", "HOLD")
    score = signal.get("score", 0)
    price = signal.get("price", 0)
    confidence = signal.get("confidence", 0)
    reasons = signal.get("reasons", [])
    risk = signal.get("risk", {})
    ai_used = signal.get("ai_used", False)

    now = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Action emoji and colour hint
    if action == "BUY":
        action_emoji = "🟢"
        action_label = "BUY"
    elif action == "SELL":
        action_emoji = "🔴"
        action_label = "SELL"
    else:
        action_emoji = "🟡"
        action_label = "HOLD"

    alloc_usd = risk.get("allocation_usd", 0)
    alloc_pct = risk.get("allocation_pct", 0)
    entry = risk.get("entry", price)
    sl = risk.get("stop_loss", 0)
    tp = risk.get("take_profit", 0)
    sl_pct = risk.get("stop_loss_pct", 0)
    tp_pct = risk.get("take_profit_pct", 0)

    reasons_text = "\n".join(
        f"  • {_html_escape(r)}" for r in reasons[:5]
    ) or "  • N/A"

    ai_note = " 🧠 AI" if ai_used else " 📊 Local"

    msg = (
        f"{action_emoji} <b>SIGNAL: {action_label} — {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Price:</b> ${price:,.4f}\n"
        f"📊 <b>Score:</b> {score:.0f}/100 | Confidence: {confidence:.0f}%{ai_note}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>How much to invest:</b>\n"
        f"  ${alloc_usd:.2f} ({alloc_pct:.1f}% of your balance)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Trade levels:</b>\n"
        f"  Entry:       ${entry:,.4f}\n"
        f"  Stop-Loss:   ${sl:,.4f} (-{sl_pct:.1f}%)\n"
        f"  Take-Profit: ${tp:,.4f} (+{tp_pct:.1f}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>Why:</b>\n{reasons_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {now}\n"
        f"<i>⚠️ Not financial advice. Trade responsibly.</i>"
    )
    return msg


def format_trade_signal(symbol: str, analysis: dict) -> str:
    """
    Return an HTML‑formatted Telegram message for a trade signal.

    Supports both the new 'signal' key (actionable signal dict) and the legacy format.
    """
    # Prefer new structured signal if available
    if "signal" in analysis:
        return format_actionable_signal(symbol, analysis["signal"])

    pred = analysis.get("prediction", {})
    ind = analysis.get("indicators", {})
    news = analysis.get("news", {})
    rec = analysis.get("recommendation", "")
    price = analysis.get("price", 0)

    direction = pred.get("direction", "N/A")
    confidence = pred.get("confidence", 0)
    cv_acc = pred.get("cv_accuracy", 0)
    overall_impact = news.get("overall_impact", "N/A")
    impact_score = news.get("impact_score", 0)

    signal_emoji = "🟢" if direction == "LONG" else "🔴"
    now = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    msg = (
        f"{signal_emoji} <b>TRADE SIGNAL — {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Price:</b> ${price}\n"
        f"📈 <b>Prediction:</b> {direction} ({confidence:.1f}% confidence)\n"
        f"🤖 <b>Model CV Accuracy:</b> {cv_acc:.1f}%\n"
        f"📰 <b>News Sentiment:</b> {overall_impact} (score: {impact_score:.2f})\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Indicators</b>\n"
        f"  RSI: {ind.get('rsi', 'N/A')}\n"
        f"  MACD: {ind.get('macd', 'N/A')}\n"
        f"  ADX: {ind.get('adx', 'N/A')}\n"
        f"  ATR: {ind.get('atr', 'N/A')}\n"
        f"  EMA Trend: {ind.get('ema_trend', 'N/A')}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 <b>Recommendation</b>\n{rec}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {now}\n"
        f"<i>⚠️ Not financial advice. Trade responsibly.</i>"
    )
    return msg


def format_high_impact_alert(event: dict) -> str:
    """Return an HTML‑formatted urgent alert for a high‑impact news event."""
    da = event.get("deep_analysis", {})
    affected = ", ".join(event.get("affected_symbols", [])) or "N/A"
    sentiment = event.get("sentiment", {})

    direction = da.get("impact_direction", "N/A")
    magnitude = da.get("impact_magnitude", "N/A")
    expected_move = da.get("expected_move", "N/A")
    time_horizon = da.get("time_horizon", "N/A")
    key_risk = da.get("key_risk", "N/A")
    recommended_action = da.get("recommended_action", "N/A")
    event_summary = da.get("event_summary", event.get("title", ""))

    now = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sentiment_label = sentiment.get("label", "neutral").upper()

    msg = (
        f"🚨 <b>HIGH‑IMPACT NEWS ALERT</b> 🚨\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📰 <b>{_html_escape(event.get('title', ''))}</b>\n\n"
        f"📋 <b>Summary:</b> {_html_escape(event_summary)}\n"
        f"🎯 <b>Direction:</b> {direction}\n"
        f"⚡ <b>Magnitude:</b> {magnitude}\n"
        f"📉 <b>Expected Move:</b> {expected_move}\n"
        f"⏱ <b>Time Horizon:</b> {time_horizon}\n"
        f"😐 <b>Sentiment:</b> {sentiment_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏦 <b>Affected Assets:</b> {_html_escape(affected)}\n"
        f"⚠️ <b>Key Risk:</b> {_html_escape(key_risk)}\n"
        f"✅ <b>Recommended Action:</b> {recommended_action}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {now}\n"
        f"<i>⚠️ Not financial advice. Trade responsibly.</i>"
    )
    return msg


# ---------------------------------------------------------------------------
# HTML escaping helper
# ---------------------------------------------------------------------------

def _html_escape(text: str) -> str:
    """Escape characters that would break Telegram HTML parse mode."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ---------------------------------------------------------------------------
# Unified alert dispatcher
# ---------------------------------------------------------------------------

def send_alert(message: str, urgent: bool = False) -> None:
    """Send via Telegram always; SMS only when urgent=True."""
    send_telegram(message)
    if urgent:
        # Strip HTML tags for SMS using a bounded, linear pattern to avoid ReDoS
        plain = re.sub(r"<[^<>]{0,100}>", "", message)
        send_sms(plain)


def send_trade_alert(symbol: str, analysis: dict) -> None:
    """Format and dispatch a trade signal alert."""
    message = format_trade_signal(symbol, analysis)
    send_alert(message, urgent=False)


def send_news_alert(event: dict) -> None:
    """Format and dispatch a high‑impact news alert (urgent)."""
    message = format_high_impact_alert(event)
    send_alert(message, urgent=True)
