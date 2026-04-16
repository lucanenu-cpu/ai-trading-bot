import openai

import config
from market_analyzer import full_analysis
from news_sentiment import analyze_news_impact

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


def get_trade_recommendation(symbol: str) -> str:
    """
    Run full technical + news analysis, then ask GPT‑4o for a trade recommendation.

    Returns the raw GPT response string.
    """
    client = openai.OpenAI(api_key=config.OPENAI_API_KEY)

    # --- gather data ---
    market_data = full_analysis(symbol)
    news_data = analyze_news_impact(symbol)

    pred = market_data["prediction"]
    ind = market_data["indicators"]

    # Build a concise summary of high‑impact news
    hi_events = news_data.get("high_impact_events", [])
    news_summary_lines = []
    for ev in hi_events[:3]:
        da = ev.get("deep_analysis", {})
        news_summary_lines.append(
            f"  - {ev.get('title', '')} "
            f"[{da.get('impact_direction', 'N/A')}, "
            f"expected: {da.get('expected_move', 'N/A')}]"
        )
    news_summary = "\n".join(news_summary_lines) if news_summary_lines else "  - No high‑impact events detected."

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
        f"High‑Impact Events:\n{news_summary}\n\n"
        "Based on the above data, provide your trade recommendation."
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=700,
    )

    return response.choices[0].message.content.strip()


def get_smart_score(symbol: str) -> dict:
    """Generate a smart score 0-100 based on all available signals, no OpenAI needed."""
    market_data = full_analysis(symbol)
    news_data = analyze_news_impact(symbol)

    pred = market_data["prediction"]
    ind = market_data["indicators"]

    score = 50  # neutral start
    signals = []

    # ML model signal (up to ±20)
    confidence = pred.get("confidence", 50)
    if pred["direction"] == "LONG":
        score += (confidence - 50) * 0.4
        if confidence > 70:
            signals.append(f"🤖 ML model: LONG with {confidence:.0f}% confidence")
    else:
        score -= (confidence - 50) * 0.4
        if confidence > 70:
            signals.append(f"🤖 ML model: SHORT with {confidence:.0f}% confidence")

    # RSI signal (up to ±10)
    rsi = ind.get("rsi", 50)
    if rsi < 30:
        score += 10
        signals.append(f"📉 RSI oversold ({rsi:.0f}) — potential bounce")
    elif rsi > 70:
        score -= 10
        signals.append(f"📈 RSI overbought ({rsi:.0f}) — potential pullback")

    # EMA trend (up to ±10)
    if ind.get("ema_trend") == "BULLISH":
        score += 10
        signals.append("📊 EMA alignment: BULLISH (9 > 21 > 50)")
    elif ind.get("ema_trend") == "BEARISH":
        score -= 10
        signals.append("📊 EMA alignment: BEARISH (9 < 21 < 50)")

    # ADX trend strength (up to ±5)
    adx = ind.get("adx", 20)
    if adx > 25:
        score += 5 if pred["direction"] == "LONG" else -5
        signals.append(f"💪 Strong trend (ADX={adx:.0f})")

    # News impact (up to ±15)
    impact = news_data.get("overall_impact", "LOW")
    impact_score_val = news_data.get("impact_score", 0)
    if impact == "HIGH":
        score += 15 if impact_score_val >= 0.5 else -15
        signals.append(f"📰 HIGH impact news detected (score: {impact_score_val:.2f})")
    elif impact == "MEDIUM":
        score += 5
        signals.append(f"📰 MEDIUM impact news")

    # Clamp 0-100
    score = max(0, min(100, score))

    # Generate recommendation
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
        "prediction": pred,
        "indicators": ind,
        "news_impact": impact,
        "news_score": impact_score_val,
        "article_count": news_data.get("article_count", 0),
        "high_impact_count": len(news_data.get("high_impact_events", [])),
    }
