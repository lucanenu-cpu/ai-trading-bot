import logging
import os
from flask import Flask, render_template, jsonify, request, abort

import config
from market_analyzer import full_analysis
from news_sentiment import analyze_news_impact
from ai_advisor import get_trade_recommendation
from scheduler import start_scheduler_thread

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

app = Flask(__name__, static_folder="static", template_folder="templates")
logger = logging.getLogger(__name__)


# Start scheduler immediately at import time (works with gunicorn workers)
def _boot_scheduler():
    """Start scheduler + send startup test message."""
    from notifications import send_telegram

    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    logger.info(f"Telegram config: token={'SET' if token else 'MISSING'}, chat_id={'SET' if chat_id else 'MISSING'}")

    if token and chat_id:
        success = send_telegram("🤖 <b>AI Trading Bot started!</b>\nChecking Telegram connection...")
        logger.info(f"Telegram test message: {'SUCCESS' if success else 'FAILED'}")
    else:
        logger.warning("Telegram not configured - bot token or chat ID missing")

    start_scheduler_thread()


_boot_scheduler()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze/<symbol>")
def analyze(symbol: str):
    """Run full analysis for a symbol and return JSON."""
    try:
        symbol = symbol.upper()
        market_data = full_analysis(symbol)
        news_data = analyze_news_impact(symbol)
        return jsonify(
            {
                "success": True,
                "symbol": symbol,
                "market": market_data,
                "news": {
                    "overall_impact": news_data["overall_impact"],
                    "impact_score": news_data["impact_score"],
                    "article_count": news_data["article_count"],
                    "high_impact_count": len(news_data["high_impact_events"]),
                    "medium_impact_count": len(news_data["medium_impact_events"]),
                },
            }
        )
    except Exception as exc:
        logger.exception("Error analyzing %s", symbol)
        return jsonify({"success": False, "error": "Analysis failed. Please try again."}), 500


@app.route("/recommend/<symbol>")
def recommend(symbol: str):
    """Return a GPT‑4o trade recommendation for a symbol."""
    try:
        symbol = symbol.upper()
        recommendation = get_trade_recommendation(symbol)
        return jsonify({"success": True, "symbol": symbol, "recommendation": recommendation})
    except Exception as exc:
        logger.exception("Error generating recommendation for %s", symbol)
        return jsonify({"success": False, "error": "Recommendation failed. Please try again."}), 500


@app.route("/api/score/<symbol>")
def smart_score(symbol: str):
    """Return a smart score (0-100) combining ML + technicals + news, no OpenAI needed."""
    try:
        symbol = symbol.upper()
        from ai_advisor import get_smart_score
        result = get_smart_score(symbol)
        return jsonify({"success": True, **result})
    except Exception as exc:
        logger.exception("Error scoring %s", symbol)
        return jsonify({"success": False, "error": "Scoring failed."}), 500


@app.route("/news/<symbol>")
def news(symbol: str):
    """Return the latest news and sentiment for a symbol."""
    try:
        symbol = symbol.upper()
        news_data = analyze_news_impact(symbol)
        return jsonify({"success": True, "symbol": symbol, **news_data})
    except Exception as exc:
        logger.exception("Error fetching news for %s", symbol)
        return jsonify({"success": False, "error": "News fetch failed. Please try again."}), 500


@app.route("/watchlist")
def watchlist():
    """Return the current watchlist."""
    from scheduler import WATCHLIST
    return jsonify({"success": True, "watchlist": WATCHLIST})


@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive an external webhook (e.g. TradingView alert)."""
    secret = request.headers.get("X-Webhook-Secret", "")
    if secret != config.WEBHOOK_SECRET:
        abort(403)

    data = request.get_json(force=True, silent=True) or {}
    symbol = data.get("symbol", "").upper()
    if not symbol:
        return jsonify({"success": False, "error": "symbol required"}), 400

    try:
        market_data = full_analysis(symbol)
        news_data = analyze_news_impact(symbol)
        from notifications import send_trade_alert
        send_trade_alert(
            symbol,
            {
                **market_data,
                "news": news_data,
                "recommendation": data.get("message", "Webhook triggered"),
            },
        )
        return jsonify({"success": True, "symbol": symbol})
    except Exception as exc:
        logger.exception("Webhook error for %s", symbol)
        return jsonify({"success": False, "error": "Webhook processing failed."}), 500


# ---------------------------------------------------------------------------
# Telegram test
# ---------------------------------------------------------------------------

@app.route("/api/test-telegram")
def test_telegram():
    """Send a test message to Telegram to verify configuration."""
    from notifications import send_telegram
    success = send_telegram("✅ <b>Test message</b>\nIf you see this, Telegram is working!")
    return jsonify({
        "success": success,
        "token_set": bool(config.TELEGRAM_BOT_TOKEN),
        "chat_id_set": bool(config.TELEGRAM_CHAT_ID),
    })


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False)
