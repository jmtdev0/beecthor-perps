from __future__ import annotations

from datetime import UTC, datetime

from .config import Settings
from .models import Direction, MarketSnapshot, OrderIntent


class SafetyViolation(ValueError):
    """Raised when an order intent violates a hard risk rule."""


def validate_market_snapshot(snapshot: MarketSnapshot, settings: Settings) -> None:
    if snapshot.symbol.upper() not in settings.safety.symbol_allowlist:
        raise SafetyViolation(f"Symbol {snapshot.symbol} is not allowed")
    age_seconds = (datetime.now(UTC) - snapshot.observed_at).total_seconds()
    if age_seconds > settings.safety.market_data_max_age_seconds:
        raise SafetyViolation(f"Market data is stale: {age_seconds:.1f}s old")
    if snapshot.price <= 0:
        raise SafetyViolation("Market price must be positive")


def validate_order_intent(
    intent: OrderIntent,
    settings: Settings,
    *,
    open_positions: int = 0,
    realized_pnl_today_usdt: float = 0.0,
) -> None:
    symbol = intent.symbol.upper()
    if symbol not in settings.safety.symbol_allowlist:
        raise SafetyViolation(f"Symbol {symbol} is not in SYMBOL_ALLOWLIST")
    if intent.notional_usdt <= 0:
        raise SafetyViolation("Order notional must be positive")
    if intent.notional_usdt > settings.safety.max_notional_usdt:
        raise SafetyViolation(
            f"Order notional {intent.notional_usdt} exceeds max {settings.safety.max_notional_usdt}"
        )
    if intent.leverage < 1 or intent.leverage > settings.safety.max_leverage:
        raise SafetyViolation(f"Leverage {intent.leverage} exceeds max {settings.safety.max_leverage}")
    if intent.quantity <= 0:
        raise SafetyViolation("Order quantity must be positive")
    if open_positions >= settings.safety.max_open_positions:
        raise SafetyViolation("Max open positions reached")
    if realized_pnl_today_usdt <= -abs(settings.safety.daily_loss_limit_usdt):
        raise SafetyViolation("Daily loss limit reached")
    if intent.stop_loss <= 0 or intent.take_profit <= 0:
        raise SafetyViolation("Stop loss and take profit are required")

    if intent.direction == Direction.LONG:
        if not intent.stop_loss < intent.entry_price_reference < intent.take_profit:
            raise SafetyViolation("Long intent requires stop < entry < take-profit")
    elif intent.direction == Direction.SHORT:
        if not intent.take_profit < intent.entry_price_reference < intent.stop_loss:
            raise SafetyViolation("Short intent requires take-profit < entry < stop")
    else:
        raise SafetyViolation(f"Unsupported direction: {intent.direction}")
