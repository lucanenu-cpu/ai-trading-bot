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


@app.route("/api/chart-data/<symbol>")
def api_chart_data(symbol: str):
    """Return daily close price history for Chart.js rendering (last 30 trading days)."""
    try:
        symbol = symbol.upper()
        from market_analyzer import fetch_market_data
        df = fetch_market_data(symbol, period="30d", interval="1d")
        if df.empty:
            return jsonify({"success": False, "error": "No data available"}), 404

        dates = [str(d)[:10] for d in df.index]
        closes = [round(float(c), 4) for c in df["Close"]]

        return jsonify({
            "success": True,
            "symbol": symbol,
            "dates": dates,
            "closes": closes,
        })
    except Exception as exc:
        logger.exception("Error fetching chart data for %s", symbol)
        return jsonify({"success": False, "error": "Chart data unavailable"}), 500


@app.route("/api/recommendation/<symbol>")
def api_recommendation(symbol: str):
    """
    Return a unified actionable signal with BUY/SELL/HOLD action,
    allocation recommendation, SL/TP levels, and reasons.

    The response is enriched with TradingView resolution info (exchange,
    type) and TradingView's technical consensus so the frontend can embed
    the matching TradingView chart and display data consistent with it.
    """
    try:
        symbol = symbol.upper()
        from ai_advisor import get_actionable_signal
        signal = get_actionable_signal(symbol)

        # Best-effort TradingView enrichment so the UI can always render a chart
        # and show the same price/consensus that TradingView shows.
        try:
            from tradingview import search_symbol, get_technical_analysis
            match = search_symbol(symbol)
            if match:
                tv_analysis = get_technical_analysis(
                    match["symbol"], match.get("exchange", ""), match.get("type", "stock")
                )
                signal["resolved"] = {
                    "symbol": match["symbol"],
                    "yfinance_symbol": symbol,
                    "exchange": match.get("exchange", ""),
                    "type": match.get("type", ""),
                    "description": match.get("description", ""),
                }
                signal["tradingview"] = tv_analysis
        except Exception:  # never fail the signal because of TV enrichment
            logger.exception("TradingView enrichment failed for %s", symbol)

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


@app.route("/api/bot-status")
def api_bot_status():
    """
    Comprehensive bot status endpoint for the dashboard.

    Returns risk state, open positions, recent trade history, config limits,
    and AI availability — all in one call.
    """
    import risk_manager
    from ai_advisor import _ai_calls_remaining
    from scheduler import WATCHLIST

    state = risk_manager.get_state()
    risk_manager.reset_daily_if_needed(state)

    return jsonify({
        "success": True,
        "status": "running",
        "ai_enabled": config.AI_ENABLED,
        "ai_calls_remaining": _ai_calls_remaining(),
        "ai_calls_max": config.MAX_AI_CALLS_PER_HOUR,
        "trades_today": state.trades_today,
        "open_positions": state.open_positions,
        "realized_pnl_today": state.realized_pnl_today,
        "recent_trades": state.recent_trades[-10:],
        "watchlist": WATCHLIST,
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
            "trade_cooldown_secs": config.TRADE_COOLDOWN_SECS,
            "chop_adx_threshold": config.CHOP_ADX_THRESHOLD,
            "atr_sl_multiplier": config.ATR_SL_MULTIPLIER,
            "max_ai_calls_per_hour": config.MAX_AI_CALLS_PER_HOUR,
        },
    })


@app.route("/api/settings", methods=["POST"])
def api_settings():
    """
    Update key risk/strategy settings in-memory (no restart needed).

    Accepts a JSON body with any subset of the following fields (all optional):
        account_balance_usd  (float, 1 – 1 000 000)
        risk_per_trade_pct   (float, 0.1 – 5.0)
        default_stop_loss_pct  (float, 0.5 – 10.0)
        default_take_profit_pct (float, 1.0 – 20.0)
        min_signal_score     (float, 50 – 90)
        trade_cooldown_secs  (int, 0 – 3600)
        chop_adx_threshold   (float, 0 – 40)
        atr_sl_multiplier    (float, 0 – 5)

    Returns the updated effective config values.
    """
    body = request.get_json(silent=True) or {}
    if not body:
        return jsonify({"success": False, "error": "Empty JSON body"}), 400

    updated = {}
    errors = []

    def _update_float(key: str, attr: str, lo: float, hi: float) -> None:
        raw = body.get(key)
        if raw is None:
            return
        try:
            v = float(raw)
        except (TypeError, ValueError):
            errors.append(f"{key}: must be a number")
            return
        if not (lo <= v <= hi):
            errors.append(f"{key}: must be between {lo} and {hi}")
            return
        setattr(config, attr, v)
        updated[key] = v

    def _update_int(key: str, attr: str, lo: int, hi: int) -> None:
        raw = body.get(key)
        if raw is None:
            return
        try:
            v = int(raw)
        except (TypeError, ValueError):
            errors.append(f"{key}: must be an integer")
            return
        if not (lo <= v <= hi):
            errors.append(f"{key}: must be between {lo} and {hi}")
            return
        setattr(config, attr, v)
        updated[key] = v

    _update_float("account_balance_usd",     "ACCOUNT_BALANCE_USD",      1.0,   1_000_000.0)
    _update_float("risk_per_trade_pct",       "RISK_PER_TRADE_PCT",       0.1,   5.0)
    _update_float("default_stop_loss_pct",    "DEFAULT_STOP_LOSS_PCT",    0.5,   10.0)
    _update_float("default_take_profit_pct",  "DEFAULT_TAKE_PROFIT_PCT",  1.0,   20.0)
    _update_float("min_signal_score",         "MIN_SIGNAL_SCORE",         50.0,  90.0)
    _update_float("chop_adx_threshold",       "CHOP_ADX_THRESHOLD",       0.0,   40.0)
    _update_float("atr_sl_multiplier",        "ATR_SL_MULTIPLIER",        0.0,   5.0)
    _update_int(  "trade_cooldown_secs",      "TRADE_COOLDOWN_SECS",      0,     3600)

    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    if not updated:
        return jsonify({"success": False, "error": "No recognised settings provided"}), 400

    logger.info("Settings updated via API: %s", updated)
    return jsonify({"success": True, "updated": updated})


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
