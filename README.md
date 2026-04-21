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

## 🚀 Unde vezi aplicația / How to Access the App

> **Română:** Rulează comanda de mai jos în terminal și deschide browserul la adresa indicată.

### ▶️ Local (cel mai simplu / easiest)

```bash
# 1. Instalează dependențele (o singură dată)
pip install -r requirements.txt

# 2. Pornește serverul
python server.py

# 3. Deschide browserul la:
#    http://localhost:8080
```

**Deschide:** [http://localhost:8080](http://localhost:8080)

Vei vedea interfața AI Trading Bot cu:
- Tab **🔍 Analyze** — introdu un simbol (ex. `AAPL`, `BTC-USD`) și apasă **⚡ Analyze**
- Primești recomandare **BUY / SELL / HOLD**, sumă sugerată, Entry, Stop-Loss, Take-Profit
- Grafic TradingView live integrat
- Tab **📊 Dashboard** — starea botului, poziții deschise, istoric tranzacții
- Tab **⚙️ Settings** — configurare risc / strategie

### 🐳 Docker

```bash
docker build -t ai-trading-bot .
docker run -p 8080:8080 --env-file .env ai-trading-bot
# Deschide: http://localhost:8080
```

### ☁️ Railway (deployment în cloud)

1. Conectează repo-ul la [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**
2. Setează variabilele de mediu din `.env.example` în panoul Railway → **Variables**
3. Railway detectează automat `Dockerfile` și deployează
4. URL-ul aplicației apare în dashboard Railway (ex. `https://ai-trading-bot-production.up.railway.app`)

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

> See the **[🚀 Unde vezi aplicația / How to Access the App](#-unde-vezi-aplicația--how-to-access-the-app)** section above for the fastest way to run and view the bot.

### Prerequisites
- Python 3.10+
- (Optional) Docker

### First-time setup (clone + env vars)

```bash
git clone https://github.com/lucanenu-cpu/ai-trading-bot
cd ai-trading-bot

# Copy and edit environment variables (API keys are optional)
cp .env.example .env
# edit .env with your keys

# Install dependencies
pip install -r requirements.txt

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
