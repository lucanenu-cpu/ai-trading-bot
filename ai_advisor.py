import openai

import config
from market_analyzer import full_analysis
from news_sentiment import analyze_news_impact

SYSTEM_PROMPT = (
    "You are an elite AI trading advisor with deep expertise in technical analysis, "
    "fundamental analysis, macro‑economics, and risk management. "
    "Your task is to provide actionable trade recommendations.\n\n"
    "For every analysis you MUST provide:\n"
    "  • Signal: BUY / SELL / HOLD\n"
    "  • Entry price (exact or range)\n"
    "  • Stop‑Loss (SL) level\n"
    "  • Take‑Profit (TP) level\n"
    "  • Conviction score: 1‑10 (10 = highest confidence)\n"
    "  • Reasoning: concise bullet points (max 6)\n"
    "  • Risk flags: any major risks that could invalidate the thesis\n\n"
    "Always end with: ⚠️ This is not financial advice. Trade responsibly."
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
