import re
import datetime
import requests
import feedparser
from datetime import timezone

import config

# ---------------------------------------------------------------------------
# RSS feed templates (use {symbol} placeholder where relevant)
# ---------------------------------------------------------------------------
RSS_FEEDS = [
    "https://finance.yahoo.com/rss/headline?s={symbol}",
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://feeds.reuters.com/reuters/businessNews",
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://www.federalreserve.gov/feeds/press_all.xml",
]

# ---------------------------------------------------------------------------
# High‑impact keyword → event type mapping
# ---------------------------------------------------------------------------
HIGH_IMPACT_KEYWORDS = {
    "fed": "central_bank",
    "fomc": "central_bank",
    "rate hike": "interest_rate",
    "rate cut": "interest_rate",
    "interest rate": "interest_rate",
    "quantitative easing": "monetary_policy",
    "quantitative tightening": "monetary_policy",
    "tapering": "monetary_policy",
    "powell": "central_bank",
    "ecb": "central_bank",
    "boj": "central_bank",
    "cpi": "inflation",
    "inflation": "inflation",
    "nonfarm payroll": "employment",
    "nfp": "employment",
    "unemployment": "employment",
    "gdp": "economic_growth",
    "pmi": "economic_indicator",
    "retail sales": "economic_indicator",
    "consumer confidence": "economic_indicator",
    "war": "geopolitical",
    "invasion": "geopolitical",
    "sanctions": "geopolitical",
    "tariff": "trade",
    "trade war": "trade",
    "embargo": "trade",
    "missile": "geopolitical",
    "nuclear": "geopolitical",
    "earnings": "corporate",
    "revenue miss": "corporate",
    "revenue beat": "corporate",
    "guidance": "corporate",
    "bankruptcy": "corporate",
    "merger": "corporate",
    "acquisition": "corporate",
    "ipo": "corporate",
    "stock split": "corporate",
    "buyback": "corporate",
    "dividend": "corporate",
    "layoff": "corporate",
    "sec investigation": "regulatory",
    "fraud": "regulatory",
    "recall": "corporate",
    "fda approval": "regulatory",
    "halving": "crypto",
    "etf approval": "regulatory",
    "defi hack": "crypto",
    "exchange hack": "crypto",
    "regulation crypto": "crypto",
    "black swan": "systemic",
    "circuit breaker": "systemic",
    "flash crash": "systemic",
    "margin call": "systemic",
    "default": "systemic",
    "downgrade": "credit",
}

# ---------------------------------------------------------------------------
# Asset‑specific keyword → symbol mapping
# ---------------------------------------------------------------------------
ASSET_KEYWORDS = {
    "AAPL": ["apple", "iphone", "ipad", "mac", "tim cook", "app store"],
    "TSLA": ["tesla", "elon musk", "ev", "electric vehicle", "cybertruck", "spacex"],
    "MSFT": ["microsoft", "azure", "windows", "satya nadella", "xbox", "copilot"],
    "GOOGL": ["google", "alphabet", "youtube", "waymo", "gemini", "android"],
    "AMZN": ["amazon", "aws", "prime", "bezos", "alexa"],
    "NVDA": ["nvidia", "gpu", "cuda", "jensen huang", "ai chip"],
    "META": ["meta", "facebook", "instagram", "whatsapp", "zuckerberg", "threads"],
    "BTC-USD": ["bitcoin", "btc", "crypto", "satoshi", "blockchain"],
    "ETH-USD": ["ethereum", "eth", "vitalik", "solidity"],
    "SPY": ["s&p 500", "s&p", "sp500", "wall street", "stock market"],
    "QQQ": ["nasdaq", "tech stocks", "tech sector"],
    "GLD": ["gold", "precious metals", "safe haven"],
    "USO": ["oil", "crude", "opec", "petroleum", "wti", "brent"],
    "DXY": ["dollar", "usd", "dollar index", "greenback"],
}

# ---------------------------------------------------------------------------
# FinBERT sentiment pipeline (lazy‑loaded)
# ---------------------------------------------------------------------------
_finbert_pipeline = None


def _get_finbert():
    global _finbert_pipeline
    if _finbert_pipeline is None:
        try:
            from transformers import pipeline as hf_pipeline
            _finbert_pipeline = hf_pipeline(
                "text-classification",
                model="ProsusAI/finbert",
                tokenizer="ProsusAI/finbert",
            )
        except Exception:
            _finbert_pipeline = None
    return _finbert_pipeline


def _finbert_sentiment(text: str) -> dict:
    """Return FinBERT label + score, falling back to neutral on error."""
    pipe = _get_finbert()
    if pipe is None:
        return {"label": "neutral", "score": 0.5}
    try:
        result = pipe(text[:512])[0]
        return {"label": result["label"].lower(), "score": float(result["score"])}
    except Exception:
        return {"label": "neutral", "score": 0.5}


# ---------------------------------------------------------------------------
# GPT-4o deep analysis
# ---------------------------------------------------------------------------
def gpt_deep_analysis(article: dict, symbol: str) -> dict:
    """
    Ask GPT-4o for a structured JSON analysis of a news article.

    Returns dict with keys:
        event_summary, affected_assets, impact_direction, impact_magnitude,
        expected_move, time_horizon, key_risk, recommended_action
    """
    import json
    import openai

    client = openai.OpenAI(api_key=config.OPENAI_API_KEY)

    prompt = (
        f"Analyze this financial news article for its trading impact on {symbol}.\n\n"
        f"Title: {article.get('title', '')}\n"
        f"Summary: {article.get('summary', '')}\n\n"
        "Return a JSON object with these exact keys:\n"
        "  event_summary      - one sentence summary\n"
        "  affected_assets    - list of ticker symbols likely affected\n"
        "  impact_direction   - BULLISH, BEARISH, or NEUTRAL\n"
        "  impact_magnitude   - LOW, MEDIUM, or HIGH\n"
        "  expected_move      - estimated % price move (e.g. '+2%')\n"
        "  time_horizon       - INTRADAY, SHORT_TERM (1-5d), MEDIUM_TERM (1-4w)\n"
        "  key_risk           - main risk to this thesis\n"
        "  recommended_action - BUY, SELL, HOLD, or WATCH\n"
        "Return only the JSON object, no markdown."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a professional financial analyst."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=400,
        )
        raw = response.choices[0].message.content.strip()
        return json.loads(raw)
    except Exception as exc:
        return {
            "event_summary": article.get("title", ""),
            "affected_assets": [symbol],
            "impact_direction": "NEUTRAL",
            "impact_magnitude": "LOW",
            "expected_move": "0%",
            "time_horizon": "INTRADAY",
            "key_risk": str(exc),
            "recommended_action": "WATCH",
        }


# ---------------------------------------------------------------------------
# RSS fetching
# ---------------------------------------------------------------------------
def fetch_from_rss(symbol: str, max_per_feed: int = 15) -> list:
    """Fetch articles published in the last 48 hours from all RSS feeds."""
    cutoff = datetime.datetime.now(timezone.utc) - datetime.timedelta(hours=48)
    articles = []

    for feed_url in RSS_FEEDS:
        url = feed_url.replace("{symbol}", symbol)
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime.datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                if published and published < cutoff:
                    continue
                articles.append(
                    {
                        "title": getattr(entry, "title", ""),
                        "summary": getattr(entry, "summary", ""),
                        "link": getattr(entry, "link", ""),
                        "published": published.isoformat() if published else "",
                        "source": url,
                    }
                )
        except Exception:
            continue

    return articles


# ---------------------------------------------------------------------------
# NewsAPI fetching
# ---------------------------------------------------------------------------
def fetch_from_newsapi(symbol: str, query: str = "") -> list:
    """Fetch articles from NewsAPI.org."""
    if not config.NEWS_API_KEY:
        return []

    q = query or symbol
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": q,
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": 20,
        "apiKey": config.NEWS_API_KEY,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        articles = []
        for item in data.get("articles", []):
            articles.append(
                {
                    "title": item.get("title", ""),
                    "summary": item.get("description", ""),
                    "link": item.get("url", ""),
                    "published": item.get("publishedAt", ""),
                    "source": item.get("source", {}).get("name", "newsapi"),
                }
            )
        return articles
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Combine + deduplicate articles
# ---------------------------------------------------------------------------
def fetch_all_news(symbol: str) -> list:
    """Fetch from all sources and deduplicate by title."""
    rss_articles = fetch_from_rss(symbol)
    api_articles = fetch_from_newsapi(symbol)

    seen_titles: set = set()
    unique: list = []
    for article in rss_articles + api_articles:
        title = (article.get("title") or "").strip().lower()
        if title and title not in seen_titles:
            seen_titles.add(title)
            unique.append(article)

    return unique


# ---------------------------------------------------------------------------
# Keyword detection
# ---------------------------------------------------------------------------
def detect_keyword_impact(text: str) -> list:
    """Return a list of {keyword, event_type} dicts found in text."""
    text_lower = text.lower()
    hits = []
    for keyword, event_type in HIGH_IMPACT_KEYWORDS.items():
        if keyword in text_lower:
            hits.append({"keyword": keyword, "event_type": event_type})
    return hits


def detect_affected_symbols(text: str) -> list:
    """Return ticker symbols mentioned in text via ASSET_KEYWORDS or $TICKER pattern."""
    text_lower = text.lower()
    affected = set()

    # Match ASSET_KEYWORDS
    for sym, keywords in ASSET_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                affected.add(sym)
                break

    # Match $TICKER pattern (e.g. $AAPL)
    tickers = re.findall(r"\$([A-Z]{1,5})", text)
    affected.update(tickers)

    return list(affected)


# ---------------------------------------------------------------------------
# Impact classification
# ---------------------------------------------------------------------------
_SEVERITY_EVENTS = {
    "geopolitical", "systemic", "central_bank", "interest_rate", "crypto",
}


def classify_impact_level(article: dict, keyword_hits: list) -> str:
    """Return HIGH, MEDIUM, or LOW based on keyword hits and event types."""
    if len(keyword_hits) >= 2:
        return "HIGH"

    for hit in keyword_hits:
        if hit["event_type"] in _SEVERITY_EVENTS:
            return "HIGH"

    if len(keyword_hits) == 1:
        return "MEDIUM"

    return "LOW"


# ---------------------------------------------------------------------------
# Full news analysis pipeline
# ---------------------------------------------------------------------------
def analyze_news_impact(symbol: str) -> dict:
    """
    Full pipeline: fetch → detect → classify → sentiment → GPT deep analysis.

    Returns:
        overall_impact   - HIGH / MEDIUM / LOW
        impact_score     - float 0‑1
        high_impact_events  - list of enriched article dicts
        medium_impact_events
        article_count
        all_articles
    """
    articles = fetch_all_news(symbol)

    high_impact_events = []
    medium_impact_events = []
    impact_scores = []

    for article in articles:
        text = f"{article.get('title', '')} {article.get('summary', '')}"
        keyword_hits = detect_keyword_impact(text)
        level = classify_impact_level(article, keyword_hits)
        sentiment = _finbert_sentiment(text)
        affected = detect_affected_symbols(text)

        enriched = {
            **article,
            "keyword_hits": keyword_hits,
            "impact_level": level,
            "sentiment": sentiment,
            "affected_symbols": affected,
        }

        if level == "HIGH":
            enriched["deep_analysis"] = gpt_deep_analysis(article, symbol)
            high_impact_events.append(enriched)
            impact_scores.append(0.9 if sentiment["label"] != "neutral" else 0.7)
        elif level == "MEDIUM":
            medium_impact_events.append(enriched)
            impact_scores.append(0.5 if sentiment["label"] != "neutral" else 0.3)

    impact_score = sum(impact_scores) / len(impact_scores) if impact_scores else 0.0
    overall_impact = (
        "HIGH" if impact_score >= 0.65
        else "MEDIUM" if impact_score >= 0.35
        else "LOW"
    )

    return {
        "overall_impact": overall_impact,
        "impact_score": round(impact_score, 4),
        "high_impact_events": high_impact_events,
        "medium_impact_events": medium_impact_events,
        "article_count": len(articles),
        "all_articles": articles,
    }


def get_market_sentiment(symbol: str) -> dict:
    """Backward‑compatible wrapper around analyze_news_impact."""
    return analyze_news_impact(symbol)
