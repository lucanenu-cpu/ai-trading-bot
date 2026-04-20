"""
risk_manager.py — Deterministic, network-free risk management helpers.

All functions are pure / testable and rely only on config values passed in as
arguments so they can be exercised without a live market connection.
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from datetime import timezone
from typing import Optional

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State dataclass
# ---------------------------------------------------------------------------

@dataclass
class RiskState:
    """Tracks intraday risk metrics.  Reset via :func:`reset_daily_if_needed`."""
    date: datetime.date = field(default_factory=lambda: datetime.date.today())
    trades_today: int = 0
    realized_pnl_today: float = 0.0
    open_positions: list = field(default_factory=list)

    # Singleton-style global state used by the scheduler
    _instance: Optional["RiskState"] = field(default=None, init=False, repr=False, compare=False)


# Module-level singleton
_state = RiskState()


def get_state() -> RiskState:
    """Return the module-level RiskState singleton."""
    return _state


def reset_daily_if_needed(state: Optional[RiskState] = None) -> None:
    """Reset counters when the calendar date has changed."""
    s = state if state is not None else _state
    today = datetime.date.today()
    if s.date != today:
        logger.info("RiskManager: new day %s — resetting daily counters", today)
        s.date = today
        s.trades_today = 0
        s.realized_pnl_today = 0.0
        s.open_positions = []


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------

def calculate_position_size(
    balance: float,
    risk_pct: float,
    stop_loss_pct: float,
    price: float,
) -> dict:
    """
    Calculate position size based on risk per trade.

    Args:
        balance:       Account balance in USD.
        risk_pct:      Maximum risk per trade as a % of balance (e.g. 1.0 = 1 %).
        stop_loss_pct: Distance from entry to stop-loss as a % (e.g. 2.0 = 2 %).
        price:         Current asset price.

    Returns:
        {
            "risk_amount_usd":  float,   # $ at risk
            "allocation_usd":   float,   # total position size in $
            "allocation_pct":   float,   # allocation as % of balance
            "quantity":         float,   # number of units
        }
    """
    if balance <= 0 or risk_pct <= 0 or stop_loss_pct <= 0 or price <= 0:
        return {
            "risk_amount_usd": 0.0,
            "allocation_usd": 0.0,
            "allocation_pct": 0.0,
            "quantity": 0.0,
        }

    risk_amount_usd = balance * (risk_pct / 100.0)
    # allocation = risk / (stop_loss% / 100)
    allocation_usd = risk_amount_usd / (stop_loss_pct / 100.0)
    # cap at full balance
    allocation_usd = min(allocation_usd, balance)
    allocation_pct = (allocation_usd / balance) * 100.0
    quantity = allocation_usd / price

    return {
        "risk_amount_usd": round(risk_amount_usd, 4),
        "allocation_usd": round(allocation_usd, 4),
        "allocation_pct": round(allocation_pct, 2),
        "quantity": round(quantity, 6),
    }


# ---------------------------------------------------------------------------
# Trade levels (SL / TP)
# ---------------------------------------------------------------------------

def compute_trade_levels(
    price: float,
    direction: str,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> dict:
    """
    Compute absolute stop-loss and take-profit prices.

    Args:
        price:           Entry price.
        direction:       "BUY" or "SELL" (or "LONG"/"SHORT").
        stop_loss_pct:   % below entry (BUY) or above entry (SELL).
        take_profit_pct: % above entry (BUY) or below entry (SELL).

    Returns:
        {
            "entry":       float,
            "stop_loss":   float,
            "take_profit": float,
            "stop_loss_pct":   float,
            "take_profit_pct": float,
        }
    """
    if price <= 0:
        return {
            "entry": price,
            "stop_loss": price,
            "take_profit": price,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
        }

    is_long = direction.upper() in ("BUY", "LONG")
    if is_long:
        sl = price * (1 - stop_loss_pct / 100.0)
        tp = price * (1 + take_profit_pct / 100.0)
    else:
        sl = price * (1 + stop_loss_pct / 100.0)
        tp = price * (1 - take_profit_pct / 100.0)

    return {
        "entry": round(price, 4),
        "stop_loss": round(sl, 4),
        "take_profit": round(tp, 4),
        "stop_loss_pct": round(stop_loss_pct, 2),
        "take_profit_pct": round(take_profit_pct, 2),
    }


# ---------------------------------------------------------------------------
# Trade gate
# ---------------------------------------------------------------------------

def can_open_new_trade(
    state: Optional[RiskState] = None,
    balance: Optional[float] = None,
) -> tuple[bool, str]:
    """
    Check whether a new trade is allowed given current risk state.

    Returns:
        (True, "OK") if allowed, or (False, reason_string) if blocked.
    """
    s = state if state is not None else _state
    bal = balance if balance is not None else config.ACCOUNT_BALANCE_USD

    reset_daily_if_needed(s)

    # Max trades per day
    if s.trades_today >= config.MAX_TRADES_PER_DAY:
        reason = f"Max trades per day reached ({config.MAX_TRADES_PER_DAY})"
        logger.info("RiskGate BLOCKED: %s", reason)
        return False, reason

    # Max open positions
    if len(s.open_positions) >= config.MAX_OPEN_POSITIONS:
        reason = f"Max open positions reached ({config.MAX_OPEN_POSITIONS})"
        logger.info("RiskGate BLOCKED: %s", reason)
        return False, reason

    # Daily loss cap
    if bal > 0:
        daily_loss_pct = (-s.realized_pnl_today / bal) * 100.0
        if daily_loss_pct >= config.MAX_DAILY_LOSS_PCT:
            reason = (
                f"Daily loss cap hit ({daily_loss_pct:.1f}% >= {config.MAX_DAILY_LOSS_PCT}%)"
            )
            logger.info("RiskGate BLOCKED: %s", reason)
            return False, reason

    logger.debug("RiskGate PASS: trades_today=%d, open=%d", s.trades_today, len(s.open_positions))
    return True, "OK"


# ---------------------------------------------------------------------------
# Allocation recommendation based on signal score
# ---------------------------------------------------------------------------

def allocation_recommendation(
    score: float,
    balance: Optional[float] = None,
) -> dict:
    """
    Suggest allocation size based on signal confidence score.

    Higher scores get more allocation, lower scores get smaller sizing.

    Returns:
        {
            "suggested_pct":   float,  # % of balance to allocate
            "suggested_usd":   float,  # $ to allocate
            "size_label":      str,    # "full" / "half" / "quarter"
        }
    """
    bal = balance if balance is not None else config.ACCOUNT_BALANCE_USD

    if score >= config.STRONG_SIGNAL_SCORE:
        pct = config.RISK_PER_TRADE_PCT
        label = "full"
    elif score >= config.MIN_SIGNAL_SCORE:
        pct = config.RISK_PER_TRADE_PCT * 0.5
        label = "half"
    else:
        pct = config.RISK_PER_TRADE_PCT * 0.25
        label = "quarter"

    # Convert risk% to actual allocation using default SL
    sizing = calculate_position_size(
        balance=bal,
        risk_pct=pct,
        stop_loss_pct=config.DEFAULT_STOP_LOSS_PCT,
        price=1.0,  # price-independent; we want allocation_usd directly
    )

    # Override: if the caller just wants suggested allocation in USD proportional to score
    allocation_usd = bal * (pct / 100.0) / (config.DEFAULT_STOP_LOSS_PCT / 100.0)
    allocation_usd = min(allocation_usd, bal)

    return {
        "suggested_pct": round(pct, 2),
        "suggested_usd": round(allocation_usd, 2),
        "size_label": label,
    }


# ---------------------------------------------------------------------------
# Record a trade
# ---------------------------------------------------------------------------

def record_trade(symbol: str, state: Optional[RiskState] = None) -> None:
    """Increment daily trade counter and add symbol to open positions."""
    s = state if state is not None else _state
    reset_daily_if_needed(s)
    s.trades_today += 1
    if symbol not in s.open_positions:
        s.open_positions.append(symbol)
    logger.info("RiskManager: recorded trade for %s (trades_today=%d)", symbol, s.trades_today)
