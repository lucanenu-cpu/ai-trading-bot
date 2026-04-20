import logging
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Credentials / external services
# ---------------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "changeme")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TWILIO_SID = os.getenv("TWILIO_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM", "")
TWILIO_TO = os.getenv("TWILIO_TO", "")

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
PORT = int(os.getenv("PORT", 8080))

# ---------------------------------------------------------------------------
# OpenAI model
# ---------------------------------------------------------------------------
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# ---------------------------------------------------------------------------
# Helpers for safe env parsing
# ---------------------------------------------------------------------------

def _get_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        logger.warning("Config: invalid float for %s=%r, using default %s", key, raw, default)
        return default


def _get_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        logger.warning("Config: invalid int for %s=%r, using default %s", key, raw, default)
        return default


def _get_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Risk & strategy settings
# ---------------------------------------------------------------------------
ACCOUNT_BALANCE_USD: float = _get_float("ACCOUNT_BALANCE_USD", 10.0)
RISK_PER_TRADE_PCT: float = _get_float("RISK_PER_TRADE_PCT", 1.0)
MAX_DAILY_LOSS_PCT: float = _get_float("MAX_DAILY_LOSS_PCT", 3.0)
MAX_TRADES_PER_DAY: int = _get_int("MAX_TRADES_PER_DAY", 5)
MAX_OPEN_POSITIONS: int = _get_int("MAX_OPEN_POSITIONS", 3)
MIN_SIGNAL_SCORE: float = _get_float("MIN_SIGNAL_SCORE", 65.0)
STRONG_SIGNAL_SCORE: float = _get_float("STRONG_SIGNAL_SCORE", 80.0)
DEFAULT_STOP_LOSS_PCT: float = _get_float("DEFAULT_STOP_LOSS_PCT", 2.0)
DEFAULT_TAKE_PROFIT_PCT: float = _get_float("DEFAULT_TAKE_PROFIT_PCT", 4.0)

# ---------------------------------------------------------------------------
# AI usage guardrails
# ---------------------------------------------------------------------------
MAX_AI_CALLS_PER_HOUR: int = _get_int("MAX_AI_CALLS_PER_HOUR", 20)
AI_ENABLED: bool = _get_bool("AI_ENABLED", True)
