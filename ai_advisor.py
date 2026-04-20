import logging
import openai

import config
from market_analyzer import full_analysis
from news_sentiment import analyze_news_impact

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an elite Wall Street quantitative trading advisor managing a $10M portfolio. "
    "You combine technical analysis, machine learning signals, news sentiment, and macro context.\n\n"
    "RULES:\n"
    "1. Be DECISIVE — never be vague. Give exact numbers.\n"
    "2. Always specify: BUY, SELL, or HOLD with exact entry price\n"
    "3. Risk management: Always give Stop-Loss and Take-Profit levels\n"
    "4. Position sizing: Suggest % of portfolio (1-5% for risky, 5-15% for high conviction)\n"
    "5. Time horizon: Scalp (hours), Swing (1-5 days), Position (1-4 weeks)\n"
    "6. Rate urgency: 🔴 ACT NOW, 🟡 WATCH CLOSELY, 🟢 NO RUSH\n\n"
    "FORMAT your response EXACTLY like this:\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "📊 SIGNAL: [BUY/SELL/HOLD]\n"
    "💰 Entry: $XXX.XX\n"
    "🛑 Stop-Loss: $XXX.XX (-X.X%)\n"
    "🎯 Target 1: $XXX.XX (+X.X%)\n"
    "🎯 Target 2: $XXX.XX (+X.X%)\n"
    "📏 Position Size: X% of portfolio\n"
    "⏰ Time Horizon: [Scalp/Swing/Position]\n"
    "🚦 Urgency: [🔴/🟡/🟢]\n"
    "📈 Conviction: X/10\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "📋 REASONING:\n"
    "• [bullet 1]\n"
    "• [bullet 2]\n"
    "• [bullet 3]\n\n"
    "⚠️ RISK FLAGS:\n"
    "• [risk 1]\n"
    "• [risk 2]\n\n"
    "💡 SMART MONEY TIP:\n"
    "[One pro insight about this trade]\n\n"
    "⚠️ This is not financial advice. Trade responsibly."
)

# ---------------------------------------------------------------------------
# In-memory AI call rate limiter (hourly bucket, no persistence)
# ---------------------------------------------------------------------------
import datetime
from datetime import timezone
from typing import Optional

_ai_call_bucket: dict = {}   # { "YYYY-MM-DDTHH": count }


def _ai_calls_remaining() -> int:
    """Return number of remaining AI calls for the current UTC hour."""
    hour_key = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    used = _ai_call_bucket.get(hour_key, 0)
    return max(0, config.MAX_AI_CALLS_PER_HOUR - used)


def _record_ai_call() -> None:
    """Increment the call counter for the current UTC hour."""
    hour_key = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    _ai_call_bucket[hour_key] = _ai_call_bucket.get(hour_key, 0) + 1
    # Prune old keys to avoid unbounded growth
    current = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    stale = [k for k in _ai_call_bucket if k < current]
    for k in stale:
        del _ai_call_bucket[k]


def ai_call_allowed() -> bool:
    """Return True if we are allowed to call OpenAI right now."""
    if not config.AI_ENABLED:
        logger.info("AI disabled via AI_ENABLED=false")
        return False
    if not config.OPENAI_API_KEY:
        logger.warning("OpenAI API key not set — skipping AI call")
        return False
    remaining = _ai_calls_remaining()
    if remaining <= 0:
        logger.warning(
            "AI call budget exhausted for current hour (limit=%d). Falling back to local scoring.",
            config.MAX_AI_CALLS_PER_HOUR,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Legacy function (kept for backward compatibility with server.py)
# ---------------------------------------------------------------------------

def get_trade_recommendation(symbol: str) -> str:
    """
    Run full technical + news analysis, then ask GPT for a trade recommendation.

    Returns the raw GPT response string (or a fallback message when AI is unavailable).
    """
    market_data = full_analysis(symbol)
    news_data = analyze_news_impact(symbol)

    pred = market_data["prediction"]
    ind = market_data["indicators"]

    hi_events = news_data.get("high_impact_events", [])
    news_summary_lines = []
    for ev in hi_events[:3]:
        da = ev.get("deep_analysis", {})
        news_summary_lines.append(
            f"  - {ev.get('title', '')} "
            f"[{da.get('impact_direction', 'N/A')}, "
            f"expected: {da.get('expected_move', 'N/A')}]"
        )
    news_summary = "\n".join(news_summary_lines) if news_summary_lines else "  - No high-impact events detected."

    if not ai_call_allowed():
        logger.info("get_trade_recommendation: AI unavailable, returning local fallback for %s", symbol)
        score_data = get_smart_score(symbol)
        return (
            f"[Local analysis — AI budget exhausted or disabled]\n"
            f"Action: {score_data['action']}\n"
            f"Score: {score_data['smart_score']}/100\n"
            f"Signals:\n" + "\n".join(f"  {s}" for s in score_data['signals'])
        )

    prompt = (
        f"Symbol: {symbol}\n"
        f"Current Price: ${market_data['price']}\n\n"
        f"=== ML Prediction ===\n"
        f"Direction: {pred['direction']}\n"
        f"Model Confidence: {pred['confidence']}%\n"
        f"CV Accuracy: {pred['cv_accuracy']}%\n\n"
        f"=== Technical Indicators ===\n"
        f"RSI: {ind['rsi']}\n"
        f"MACD diff: {ind['macd']}\n"
        f"ADX: {ind['adx']}\n"
        f"ATR: {ind['atr']}\n"
        f"EMA Trend: {ind['ema_trend']}\n\n"
        f"=== News Sentiment ===\n"
        f"Overall Impact: {news_data['overall_impact']}\n"
        f"Impact Score: {news_data['impact_score']}\n"
        f"Articles Analyzed: {news_data['article_count']}\n"
        f"High-Impact Events:\n{news_summary}\n\n"
        "Based on the above data, provide your trade recommendation."
    )

    try:
        client = openai.OpenAI(api_key=config.OPENAI_API_KEY)
        _record_ai_call()
        logger.info("AI call: get_trade_recommendation for %s (remaining_this_hour=%d)", symbol, _ai_calls_remaining())
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=700,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("OpenAI call failed for %s: %s", symbol, exc)
        return "[AI unavailable — try again later or use local analysis]"


# ---------------------------------------------------------------------------
# Smart score (no OpenAI)
# ---------------------------------------------------------------------------

def get_smart_score(symbol: str) -> dict:
    """Generate a smart score 0-100 based on all available signals, no OpenAI needed."""
    logger.info("SmartScore: starting analysis for %s", symbol)
    market_data = full_analysis(symbol)
    news_data = analyze_news_impact(symbol)

    pred = market_data["prediction"]
    ind = market_data["indicators"]

    score = 50.0  # neutral start
    signals = []
    score_breakdown = {
        "base": 50.0,
        "ml_delta": 0.0,
        "rsi_delta": 0.0,
        "ema_delta": 0.0,
        "adx_delta": 0.0,
        "news_delta": 0.0,
    }

    # ML model signal (up to ±20)
    confidence = pred.get("confidence", 50)
    ml_delta = (confidence - 50) * 0.4
    if pred["direction"] == "LONG":
        score += ml_delta
        score_breakdown["ml_delta"] = round(ml_delta, 2)
        if confidence > 70:
            signals.append(f"🤖 ML model: LONG with {confidence:.0f}% confidence")
    else:
        score -= ml_delta
        score_breakdown["ml_delta"] = round(-ml_delta, 2)
        if confidence > 70:
            signals.append(f"🤖 ML model: SHORT with {confidence:.0f}% confidence")

    # RSI signal (up to ±10)
    rsi = ind.get("rsi", 50)
    if rsi < 30:
        score += 10
        score_breakdown["rsi_delta"] = 10
        signals.append(f"📉 RSI oversold ({rsi:.0f}) — potential bounce")
    elif rsi > 70:
        score -= 10
        score_breakdown["rsi_delta"] = -10
        signals.append(f"📈 RSI overbought ({rsi:.0f}) — potential pullback")

    # EMA trend (up to ±10)
    if ind.get("ema_trend") == "BULLISH":
        score += 10
        score_breakdown["ema_delta"] = 10
        signals.append("📊 EMA alignment: BULLISH (9 > 21 > 50)")
    elif ind.get("ema_trend") == "BEARISH":
        score -= 10
        score_breakdown["ema_delta"] = -10
        signals.append("📊 EMA alignment: BEARISH (9 < 21 < 50)")

    # MACD momentum (up to ±8): positive macd_diff = bullish momentum
    macd_diff = ind.get("macd", 0)
    if macd_diff > 0:
        score += 8
        score_breakdown["macd_delta"] = 8
        signals.append(f"📈 MACD bullish momentum (diff={macd_diff:+.4f})")
    elif macd_diff < 0:
        score -= 8
        score_breakdown["macd_delta"] = -8
        signals.append(f"📉 MACD bearish momentum (diff={macd_diff:+.4f})")
    else:
        score_breakdown["macd_delta"] = 0

    # ADX trend strength (up to ±5)
    adx = ind.get("adx", 20)
    if adx > 25:
        adx_delta = 5 if pred["direction"] == "LONG" else -5
        score += adx_delta
        score_breakdown["adx_delta"] = adx_delta
        signals.append(f"💪 Strong trend (ADX={adx:.0f})")

    # News impact (up to ±15)
    impact = news_data.get("overall_impact", "LOW")
    impact_score_val = news_data.get("impact_score", 0)
    if impact == "HIGH":
        news_delta = 15 if impact_score_val >= 0.5 else -15
        score += news_delta
        score_breakdown["news_delta"] = news_delta
        signals.append(f"📰 HIGH impact news detected (score: {impact_score_val:.2f})")
    elif impact == "MEDIUM":
        score += 5
        score_breakdown["news_delta"] = 5
        signals.append(f"📰 MEDIUM impact news")

    # Clamp 0-100
    score = max(0.0, min(100.0, score))

    logger.info(
        "SmartScore: %s score=%.1f breakdown=%s",
        symbol, score, score_breakdown,
    )

    # Generate recommendation label
    if score >= 75:
        action = "STRONG BUY 🟢"
    elif score >= 60:
        action = "BUY 🟢"
    elif score >= 45:
        action = "HOLD 🟡"
    elif score >= 30:
        action = "SELL 🔴"
    else:
        action = "STRONG SELL 🔴"

    return {
        "symbol": symbol,
        "price": market_data["price"],
        "smart_score": round(score),
        "action": action,
        "signals": signals,
        "score_breakdown": score_breakdown,
        "prediction": pred,
        "indicators": ind,
        "news_impact": impact,
        "news_score": impact_score_val,
        "article_count": news_data.get("article_count", 0),
        "high_impact_count": len(news_data.get("high_impact_events", [])),
    }


# ---------------------------------------------------------------------------
# Unified actionable recommendation
# ---------------------------------------------------------------------------

def get_actionable_signal(symbol: str) -> dict:
    """
    Produce a single structured trading signal with BUY/SELL/HOLD action,
    allocation recommendation, SL/TP levels, and reasons.

    Returns:
        {
            "symbol":         str,
            "price":          float,
            "action":         "BUY" | "SELL" | "HOLD",
            "confidence":     float (0-100),
            "score":          float (0-100),
            "score_breakdown": dict,
            "reasons":        list[str],
            "risk": {
                "entry":          float,
                "stop_loss":      float,
                "take_profit":    float,
                "stop_loss_pct":  float,
                "take_profit_pct":float,
                "allocation_usd": float,
                "allocation_pct": float,
                "quantity":       float,
            },
            "ai_used":        bool,
            "ai_calls_remaining": int,
        }
    """
    from risk_manager import (
        calculate_position_size,
        compute_trade_levels,
        allocation_recommendation,
        can_open_new_trade,
        check_symbol_cooldown,
    )

    logger.info("ActionableSignal: generating for %s", symbol)

    # --- Base scoring ---
    score_data = get_smart_score(symbol)
    score = float(score_data["smart_score"])
    price = score_data["price"]
    pred_direction = score_data["prediction"]["direction"]
    reasons = list(score_data["signals"])

    # --- Determine raw action from score + ML direction ---
    # Score moves UP from 50 for bullish signals (BUY when score >= MIN_SIGNAL_SCORE).
    # Score moves DOWN from 50 for bearish signals; bearish_score = 100 - score inverts
    # this so we can apply the same threshold for SELL decisions.
    bearish_score = 100.0 - score

    if pred_direction == "LONG" and score >= config.MIN_SIGNAL_SCORE:
        raw_action = "BUY"
    elif pred_direction == "SHORT" and bearish_score >= config.MIN_SIGNAL_SCORE:
        raw_action = "SELL"
    else:
        raw_action = "HOLD"
        if pred_direction == "LONG":
            reasons.insert(0, f"Score {score:.0f} below threshold {config.MIN_SIGNAL_SCORE:.0f}")
        else:
            reasons.insert(0, f"Bearish score {bearish_score:.0f} below threshold {config.MIN_SIGNAL_SCORE:.0f}")

    # --- Choppiness / low-trend filter ---
    # When ADX is below the configured threshold the market is ranging — skip trade
    # to avoid overtrading in choppy conditions.
    adx = score_data.get("indicators", {}).get("adx", 25.0)
    if raw_action != "HOLD" and adx < config.CHOP_ADX_THRESHOLD:
        logger.info(
            "ActionableSignal: choppiness filter blocked %s — ADX=%.1f < %.1f",
            symbol, adx, config.CHOP_ADX_THRESHOLD,
        )
        raw_action = "HOLD"
        reasons.insert(0, f"Choppy market: ADX={adx:.1f} below threshold {config.CHOP_ADX_THRESHOLD:.0f} — avoiding trade")

    # --- AI refinement only for near-threshold or strong setups ---
    ai_used = False
    ai_reasoning: list[str] = []
    effective_score = score if pred_direction == "LONG" else bearish_score
    near_threshold = (
        abs(effective_score - config.MIN_SIGNAL_SCORE) <= 10
        or effective_score >= config.STRONG_SIGNAL_SCORE
    )

    if near_threshold and raw_action != "HOLD" and ai_call_allowed():
        try:
            rec_text = get_trade_recommendation(symbol)
            ai_used = True
            # Extract first 2 bullets from AI response as extra reasons
            for line in rec_text.splitlines():
                stripped = line.strip().lstrip("•- ")
                if stripped and not stripped.startswith("━") and len(ai_reasoning) < 2:
                    ai_reasoning.append(f"🧠 {stripped[:120]}")
            if ai_reasoning:
                reasons.extend(ai_reasoning)
        except Exception as exc:
            logger.warning("AI refinement failed for %s: %s", symbol, exc)

    # --- Risk gate check ---
    can_trade, gate_reason = can_open_new_trade()
    if not can_trade and raw_action != "HOLD":
        logger.info("ActionableSignal: risk gate blocked %s — %s", symbol, gate_reason)
        raw_action = "HOLD"
        reasons.insert(0, f"Risk gate: {gate_reason}")

    # --- Per-symbol cooldown check ---
    cooldown_ok, cooldown_reason = check_symbol_cooldown(symbol)
    if not cooldown_ok and raw_action != "HOLD":
        logger.info("ActionableSignal: cooldown blocked %s — %s", symbol, cooldown_reason)
        raw_action = "HOLD"
        reasons.insert(0, f"Cooldown: {cooldown_reason}")

    action = raw_action

    # --- Dynamic ATR-based SL/TP ---
    # Use ATR × multiplier as SL distance when ATR is available and multiplier > 0.
    # This adapts SL to current market volatility rather than a fixed percentage.
    atr = score_data.get("indicators", {}).get("atr", 0.0)
    if config.ATR_SL_MULTIPLIER > 0 and atr > 0 and price > 0:
        dynamic_sl_pct = (config.ATR_SL_MULTIPLIER * atr / price) * 100.0
        # Cap between 0.5 % and 8 % to prevent absurdly wide/narrow stops
        sl_pct = round(max(0.5, min(dynamic_sl_pct, 8.0)), 2)
        # Maintain a 2 : 1 reward/risk ratio for the take-profit
        tp_pct = round(sl_pct * 2.0, 2)
        logger.debug(
            "ActionableSignal: ATR-based SL for %s: ATR=%.4f → SL=%.2f%% TP=%.2f%%",
            symbol, atr, sl_pct, tp_pct,
        )
    else:
        sl_pct = config.DEFAULT_STOP_LOSS_PCT
        tp_pct = config.DEFAULT_TAKE_PROFIT_PCT

    # --- SL/TP levels ---
    levels = compute_trade_levels(
        price=price,
        direction=action if action != "HOLD" else "BUY",
        stop_loss_pct=sl_pct,
        take_profit_pct=tp_pct,
    )

    # --- Allocation sizing (use effective score for sizing decisions) ---
    alloc = allocation_recommendation(effective_score)
    sizing = calculate_position_size(
        balance=config.ACCOUNT_BALANCE_USD,
        risk_pct=config.RISK_PER_TRADE_PCT,
        stop_loss_pct=config.DEFAULT_STOP_LOSS_PCT,
        price=price,
    )

    risk_obj = {
        "entry": levels["entry"],
        "stop_loss": levels["stop_loss"],
        "take_profit": levels["take_profit"],
        "stop_loss_pct": levels["stop_loss_pct"],
        "take_profit_pct": levels["take_profit_pct"],
        "allocation_usd": alloc["suggested_usd"],
        "allocation_pct": alloc["suggested_pct"],
        "quantity": sizing["quantity"],
    }

    logger.info(
        "ActionableSignal: %s action=%s score=%.1f ai_used=%s",
        symbol, action, score, ai_used,
    )

    return {
        "symbol": symbol,
        "price": price,
        "action": action,
        "confidence": score_data["prediction"].get("confidence", 0),
        "score": score,
        "score_breakdown": score_data.get("score_breakdown", {}),
        "reasons": reasons[:6],  # cap to keep messages concise
        "risk": risk_obj,
        "ai_used": ai_used,
        "ai_calls_remaining": _ai_calls_remaining(),
        "news_impact": score_data.get("news_impact", "LOW"),
        "indicators": score_data.get("indicators", {}),
    }


# ---------------------------------------------------------------------------
# Auto-analysis from a natural-language query (TradingView-backed)
# ---------------------------------------------------------------------------

def get_auto_analysis(query: str) -> dict:
    """
    Resolve a free-text user query (e.g. "should I invest in Tesla?", "bitcoin",
    "apple stock") to a concrete ticker via TradingView's public symbol-search,
    then run the standard actionable-signal pipeline on it.

    TradingView's built-in technical consensus is folded into the result as an
    extra reason and is also used to nudge near-threshold HOLD decisions when
    the consensus is strong in one direction.

    Returns a dict with the same shape as :func:`get_actionable_signal` plus::

        {
            "query":       "<original user query>",
            "resolved": {
                "symbol":      "AAPL",
                "exchange":    "NASDAQ",
                "type":        "stock",
                "description": "Apple Inc.",
            },
            "tradingview": {
                "recommendation": "BUY",
                "score":          0.33,
                ...
            },
        }

    When no symbol can be resolved, returns::

        {"success": False, "error": "...", "query": "..."}
    """
    from tradingview import (
        search_symbol,
        get_technical_analysis,
        to_yfinance_symbol,
    )

    if not query or not query.strip():
        return {"success": False, "error": "Empty query.", "query": query or ""}

    logger.info("AutoAnalysis: resolving query %r via TradingView", query)
    match = search_symbol(query)
    if not match:
        return {
            "success": False,
            "error": (
                "Could not find a matching ticker on TradingView. "
                "Try a more specific name or a ticker symbol."
            ),
            "query": query,
        }

    tv_symbol = match["symbol"]
    tv_type = match.get("type", "stock")
    yf_symbol = to_yfinance_symbol(tv_symbol, tv_type)

    logger.info(
        "AutoAnalysis: %r resolved to %s (%s, %s) → yfinance=%s",
        query, tv_symbol, match.get("exchange"), tv_type, yf_symbol,
    )

    # --- Run the main signal pipeline on the resolved symbol ---
    signal = get_actionable_signal(yf_symbol)

    # --- Pull TradingView's technical consensus in parallel-ish ---
    tv_analysis = get_technical_analysis(tv_symbol, match.get("exchange", ""), tv_type)

    # Fold TV consensus into the reasons list.
    rec = tv_analysis.get("recommendation", "UNKNOWN")
    if rec != "UNKNOWN":
        reasons = list(signal.get("reasons", []))
        reasons.append(
            f"📡 TradingView consensus: {rec} (score {tv_analysis.get('score', 0):+.2f})"
        )
        signal["reasons"] = reasons[:7]

        # Nudge near-threshold HOLD → BUY/SELL when TV is STRONG and consistent.
        if signal.get("action") == "HOLD":
            score = float(signal.get("score", 50.0))
            if rec == "STRONG_BUY" and score >= (config.MIN_SIGNAL_SCORE - 10):
                signal["action"] = "BUY"
                signal["reasons"].insert(
                    0, "TradingView STRONG_BUY consensus tipped near-threshold HOLD to BUY."
                )
            elif rec == "STRONG_SELL" and (100.0 - score) >= (config.MIN_SIGNAL_SCORE - 10):
                signal["action"] = "SELL"
                signal["reasons"].insert(
                    0, "TradingView STRONG_SELL consensus tipped near-threshold HOLD to SELL."
                )

    signal["success"] = True
    signal["query"] = query
    signal["resolved"] = {
        "symbol": tv_symbol,
        "yfinance_symbol": yf_symbol,
        "exchange": match.get("exchange", ""),
        "type": tv_type,
        "description": match.get("description", ""),
    }
    signal["tradingview"] = tv_analysis
    return signal

