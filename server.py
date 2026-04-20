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
    """Return a GPT trade recommendation for a symbol (legacy endpoint)."""
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


@app.route("/api/recommendation/<symbol>")
def api_recommendation(symbol: str):
    """
    Return a unified actionable signal with BUY/SELL/HOLD action,
    allocation recommendation, SL/TP levels, and reasons.
    """
    try:
        symbol = symbol.upper()
        from ai_advisor import get_actionable_signal
        signal = get_actionable_signal(symbol)
        return jsonify({"success": True, **signal})
    except Exception as exc:
        logger.exception("Error generating actionable signal for %s", symbol)
        return jsonify({"success": False, "error": "Signal generation failed. Please try again."}), 500


@app.route("/api/ask", methods=["GET", "POST"])
def api_ask():
    """
    Natural-language auto-analysis endpoint.

    Accepts a free-text query (e.g. "should I invest in Tesla?", "bitcoin",
    "apple stock"), auto-searches TradingView to resolve the ticker, then
    returns a unified BUY/SELL/HOLD signal with recommended allocation
    (how much to invest), SL/TP levels, reasons, and TradingView's
    technical consensus.

    Query parameter (GET) or JSON body field (POST): ``q`` / ``query``.
    """
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        query = (body.get("q") or body.get("query") or "").strip()
    else:
        query = (request.args.get("q") or request.args.get("query") or "").strip()

    if not query:
        return jsonify({"success": False, "error": "Missing 'q' query parameter."}), 400

    try:
        from ai_advisor import get_auto_analysis
        result = get_auto_analysis(query)
        status = 200 if result.get("success", False) else 404
        return jsonify(result), status
    except Exception as exc:
        logger.exception("Error in auto-analysis for query %r", query)
        return jsonify({"success": False, "error": "Auto-analysis failed. Please try again."}), 500


@app.route("/api/risk-state")
def api_risk_state():
    """Return current risk state for diagnostics."""
    import risk_manager
    state = risk_manager.get_state()
    risk_manager.reset_daily_if_needed(state)
    return jsonify({
        "success": True,
        "date": state.date.isoformat(),
        "trades_today": state.trades_today,
        "realized_pnl_today": state.realized_pnl_today,
        "open_positions": state.open_positions,
        "limits": {
            "max_trades_per_day": config.MAX_TRADES_PER_DAY,
            "max_open_positions": config.MAX_OPEN_POSITIONS,
            "max_daily_loss_pct": config.MAX_DAILY_LOSS_PCT,
            "account_balance_usd": config.ACCOUNT_BALANCE_USD,
            "risk_per_trade_pct": config.RISK_PER_TRADE_PCT,
            "min_signal_score": config.MIN_SIGNAL_SCORE,
            "strong_signal_score": config.STRONG_SIGNAL_SCORE,
            "default_stop_loss_pct": config.DEFAULT_STOP_LOSS_PCT,
            "default_take_profit_pct": config.DEFAULT_TAKE_PROFIT_PCT,
            "max_ai_calls_per_hour": config.MAX_AI_CALLS_PER_HOUR,
            "ai_enabled": config.AI_ENABLED,
        },
    })


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
    import risk_manager
    from ai_advisor import _ai_calls_remaining
    state = risk_manager.get_state()
    return jsonify({
        "status": "ok",
        "ai_enabled": config.AI_ENABLED,
        "ai_calls_remaining_this_hour": _ai_calls_remaining(),
        "trades_today": state.trades_today,
        "open_positions": len(state.open_positions),
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False)
