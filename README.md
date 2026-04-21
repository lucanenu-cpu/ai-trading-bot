# AI Trading Bot

A risk-managed AI trading signal bot combining machine-learning predictions,
technical analysis, news sentiment, and optional OpenAI refinement to produce
structured **BUY / SELL / HOLD** signals with automatic stop-loss, take-profit,
and position-sizing recommendations.

> ⚠️ **Risk Disclaimer** — This software is provided for **informational and
> educational purposes only**. It does **not** constitute financial advice.
> Trading carries significant risk of loss. Always do your own research and
> consult a qualified financial professional before making any investment
> decisions. Past performance is not indicative of future results. Never risk
> money you cannot afford to lose.

---

## 🚀 Live Demo (Railway)

**Public URL:** https://ai-trading-bot-production.up.railway.app

> Open the URL, type a ticker (e.g. `AAPL`, `BTC-USD`, `TSLA`) and click **Analyze** to get a live BUY/SELL/HOLD signal with entry, stop-loss, take-profit, and reasoning.

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https://github.com/lucanenu-cpu/ai-trading-bot)

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Browser (HTML / CSS / JS)  ←──  Flask server.py         │
│  - Analyze tab (signals)        /api/recommendation      │
│  - Dashboard tab (status)       /api/bot-status          │
│  - Settings tab (risk config)   POST /api/settings       │
└─────────────────────────────────────────────────────────┘
           │                            │
           ▼                            ▼
    ai_advisor.py               scheduler.py
   (signal pipeline)          (background scan loop)
           │                            │
    ┌──────┴──────┐                     │
    ▼             ▼                     ▼
market_analyzer  news_sentiment     notifications
(yfinance + XGBoost + ta)  (NewsAPI + RSS)  (Telegram / Twilio)
           │
           ▼
    risk_manager.py
   (SL/TP · position sizing · daily gate · cooldown)
           │
           ▼
    tradingview.py
   (symbol search + technical consensus)
```

### Key modules

| File | Responsibility |
|---|---|
| `config.py` | Environment-based configuration with safe defaults |
| `market_analyzer.py` | Fetches OHLCV data, computes indicators, trains XGBoost |
| `ai_advisor.py` | Signal scoring, choppiness filter, AI refinement |
| `risk_manager.py` | Position sizing, SL/TP, daily loss gate, cooldown |
| `tradingview.py` | TradingView symbol search and technical consensus |
| `news_sentiment.py` | NewsAPI + RSS sentiment analysis |
| `scheduler.py` | Background scan loop, watchlist, cooldowns |
| `notifications.py` | Telegram / Twilio alerts |
| `server.py` | Flask REST API + HTML dashboard |

---

## Quick Start

### Prerequisites
- Python 3.10+
- (Optional) Docker

### Local setup

```bash
git clone https://github.com/lucanenu-cpu/ai-trading-bot
cd ai-trading-bot

# Install dependencies
pip install -r requirements.txt

# Copy and edit environment variables
cp .env.example .env
# edit .env with your keys

# Start the server
python server.py
# Open http://localhost:8080
```

### Docker

```bash
docker build -t ai-trading-bot .
docker run -p 8080:8080 --env-file .env ai-trading-bot
# Open http://localhost:8080
```

### Deploy to Railway

1. **Push this repo to GitHub** (or fork it).

2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → select this repo.

3. Railway auto-detects the `Dockerfile` and builds the image.

4. Add environment variables in **Railway → Variables** (all optional):

   | Variable | Required? | Notes |
   |---|---|---|
   | `OPENAI_API_KEY` | Optional | Enables AI-refined signals via GPT-4o |
   | `NEWS_API_KEY` | Optional | Enables live news sentiment |
   | `TELEGRAM_BOT_TOKEN` | Optional | Telegram trade alerts |
   | `TELEGRAM_CHAT_ID` | Optional | Telegram trade alerts |
   | `ACCOUNT_BALANCE_USD` | Optional | Default `10` — for position sizing |
   | `AI_ENABLED` | Optional | `true` / `false` (default `true`) |

   > Railway sets the `PORT` variable automatically — **do not** set it manually.

5. Click **Deploy**. The build takes 2–4 minutes (installing ML libraries).  
   Once the build finishes, Railway provides a public URL like:
   ```
   https://<your-app-name>.up.railway.app
   ```

6. Open the URL in your browser. You should see the AI Trading Bot UI.  
   Type any ticker (e.g. `AAPL`, `BTC-USD`, `TSLA`) and click **⚡ Analyze**.

#### Troubleshooting "this site can't be reached"

If Railway shows the site as unreachable:
1. In Railway dashboard → your project → **Deployments** tab: check if the latest build succeeded (green tick).
2. If the build failed, open **Build Logs** to see the error.
3. If the build succeeded but the service is down, open **Service Logs** — look for the gunicorn startup line:
   ```
   [INFO] Listening at: http://0.0.0.0:<PORT>
   ```
4. Make sure the service has a **public domain** assigned: Railway → your service → **Settings → Networking → Generate Domain**.
5. The first startup takes ~60 seconds while the ML models load — the health check allows up to 5 minutes.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Dashboard UI |
| `GET` | `/api/recommendation/<symbol>` | Structured BUY/SELL/HOLD signal |
| `GET` | `/api/ask?q=<query>` | Natural-language auto-analysis |
| `GET` | `/api/score/<symbol>` | Raw smart score (no AI) |
| `GET` | `/api/bot-status` | Bot status, positions, trade history, limits |
| `POST` | `/api/settings` | Update risk settings in-memory |
| `GET` | `/api/risk-state` | Raw risk state (diagnostics) |
| `GET` | `/health` | Health check |
| `GET` | `/watchlist` | Current watchlist |
| `GET` | `/news/<symbol>` | News sentiment for symbol |
| `GET` | `/recommend/<symbol>` | Legacy AI recommendation (raw GPT text) |
| `POST` | `/webhook` | TradingView / external webhook |
| `GET` | `/api/test-telegram` | Test Telegram connection |

### POST `/api/settings` body

```json
{
  "account_balance_usd": 1000,
  "risk_per_trade_pct": 1.0,
  "default_stop_loss_pct": 2.0,
  "default_take_profit_pct": 4.0,
  "min_signal_score": 65,
  "trade_cooldown_secs": 300,
  "chop_adx_threshold": 20,
  "atr_sl_multiplier": 2.0
}
```

---

## Configuration Variables

All settings are loaded from environment variables (`.env` file).
They can also be updated at runtime via `POST /api/settings`.

### Credentials

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key (optional — bot works without it) |
| `NEWS_API_KEY` | NewsAPI.org key for news sentiment |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for alerts |
| `TELEGRAM_CHAT_ID` | Telegram chat ID to send alerts to |
| `WEBHOOK_SECRET` | Secret for TradingView webhook authentication |

### Server

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8080` | HTTP server port |

### Risk & Safety

| Variable | Default | Description |
|---|---|---|
| `ACCOUNT_BALANCE_USD` | `10.0` | Account size used for position sizing |
| `RISK_PER_TRADE_PCT` | `1.0` | Max % of balance risked per trade |
| `MAX_DAILY_LOSS_PCT` | `3.0` | Drawdown guard — stops new trades after daily loss exceeds this % |
| `MAX_TRADES_PER_DAY` | `5` | Max trades per calendar day |
| `MAX_OPEN_POSITIONS` | `3` | Max simultaneous open positions |
| `TRADE_COOLDOWN_SECS` | `300` | Min seconds between trades on the same symbol (0 = disabled) |

### Signal Thresholds

| Variable | Default | Description |
|---|---|---|
| `MIN_SIGNAL_SCORE` | `65.0` | Minimum composite score to emit BUY/SELL |
| `STRONG_SIGNAL_SCORE` | `80.0` | Score above which full position sizing is used |
| `CHOP_ADX_THRESHOLD` | `20.0` | ADX below this skips trades (choppy market filter, 0 = disabled) |

### Stop-Loss / Take-Profit

| Variable | Default | Description |
|---|---|---|
| `DEFAULT_STOP_LOSS_PCT` | `2.0` | Fixed SL distance in % (used when `ATR_SL_MULTIPLIER=0`) |
| `DEFAULT_TAKE_PROFIT_PCT` | `4.0` | Fixed TP distance in % |
| `ATR_SL_MULTIPLIER` | `2.0` | ATR × multiplier = dynamic SL distance (0 = use fixed %) |

### AI

| Variable | Default | Description |
|---|---|---|
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model for AI refinement |
| `MAX_AI_CALLS_PER_HOUR` | `20` | Per-hour rate limit for OpenAI calls |
| `AI_ENABLED` | `true` | Toggle AI refinement on/off |

---

## Signal Pipeline

1. **Fetch** — download 6 months of OHLCV data from Yahoo Finance.
2. **Indicators** — compute EMA(9/21/50), MACD, RSI, ADX, ATR, BB, VWAP, OBV.
3. **ML Model** — train an XGBoost classifier with 5-fold `TimeSeriesSplit` CV.
4. **Smart Score** — aggregate ML confidence, RSI, EMA trend, MACD momentum, ADX strength, and news sentiment into a 0–100 score.
5. **Choppiness filter** — if ADX < `CHOP_ADX_THRESHOLD`, emit HOLD (avoid ranging markets).
6. **Action gate** — BUY when `score ≥ MIN_SIGNAL_SCORE` + LONG direction; SELL for inverse.
7. **Risk gate** — block if daily loss cap / max trades / max positions / per-symbol cooldown.
8. **AI refinement** — optionally call GPT near threshold or for strong signals.
9. **SL/TP sizing** — compute dynamic stops using `ATR × ATR_SL_MULTIPLIER` (capped 0.5–8 %) with 2:1 TP ratio, or fixed defaults.
10. **Position sizing** — `risk_amount = balance × risk_pct`; `allocation = risk_amount / sl_pct`.

---

## Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

Tests cover:
- `risk_manager.py` — position sizing, SL/TP computation, daily gate, cooldown, trade history
- `ai_advisor.py` — smart score thresholds, actionable signal logic, AI rate limiter, choppiness filter
- `tradingview.py` — symbol search, technical analysis, auto-analysis

No network calls are made in tests; heavy dependencies are mocked via `tests/conftest.py`.
