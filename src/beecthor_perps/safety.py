from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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
    require_stop_loss: bool = True,
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
    if intent.take_profit <= 0:
        raise SafetyViolation("Take profit is required")
    if require_stop_loss and intent.stop_loss <= 0:
        raise SafetyViolation("Stop loss is required")

    if intent.direction == Direction.LONG:
        if intent.entry_price_reference >= intent.take_profit:
            raise SafetyViolation("Long intent requires entry < take-profit")
        if require_stop_loss and intent.stop_loss >= intent.entry_price_reference:
            raise SafetyViolation("Long intent requires stop < entry < take-profit")
    elif intent.direction == Direction.SHORT:
        if intent.take_profit >= intent.entry_price_reference:
            raise SafetyViolation("Short intent requires take-profit < entry")
        if require_stop_loss and intent.stop_loss <= intent.entry_price_reference:
            raise SafetyViolation("Short intent requires take-profit < entry < stop")
    else:
        raise SafetyViolation(f"Unsupported direction: {intent.direction}")


def active_trade_direction(trade: dict[str, Any]) -> str:
    direction = str(trade.get("direction") or trade.get("position_side") or "").strip().lower()
    if direction in {"long", "short"}:
        return direction
    return ""


def active_trade_notional(trade: dict[str, Any]) -> float:
    value = trade.get("notional_usdc", trade.get("notional_usdt", 0))
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def validate_active_trade_limits(
    intent: OrderIntent,
    settings: Settings,
    active_trades: list[dict[str, Any]],
) -> None:
    open_trades = [
        trade
        for trade in active_trades
        if str(trade.get("status") or "open").lower() in {"open", "in_position", "active"}
    ]
    if len(open_trades) >= settings.safety.max_open_positions:
        raise SafetyViolation("Max open positions reached")

    direction = intent.direction.value
    same_side = [trade for trade in open_trades if active_trade_direction(trade) == direction]
    if len(same_side) >= settings.safety.max_open_positions_per_side:
        raise SafetyViolation("Max open positions per side reached")

    total_notional = sum(active_trade_notional(trade) for trade in open_trades) + intent.notional_usdt
    if total_notional > settings.safety.max_total_notional_usdt:
        raise SafetyViolation(
            f"Total notional {total_notional:.2f} exceeds max {settings.safety.max_total_notional_usdt:.2f}"
        )
