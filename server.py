import logging
import os
from flask import Flask, render_template, jsonify, request, abort

import config
from market_analyzer import full_analysis
from news_sentiment import analyze_news_impact
from ai_advisor import get_trade_recommendation
from scheduler import start_scheduler_thread

app = Flask(__name__, static_folder="static", template_folder="templates")
logger = logging.getLogger(__name__)

_scheduler_launched = False


@app.before_request
def _start_scheduler_once():
    global _scheduler_launched
    if not _scheduler_launched:
        _scheduler_launched = True
        start_scheduler_thread()


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
