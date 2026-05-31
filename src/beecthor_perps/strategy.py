from __future__ import annotations

from .config import Settings
from .models import BeecthorThesis, Decision, DecisionAction, Direction, MarketSnapshot, OrderIntent, PriceZone
from .safety import validate_market_snapshot, validate_order_intent


def _quantity_from_notional(notional_usdt: float, price: float) -> float:
    return max(0.001, round(notional_usdt / price, 3))


def _first_target(zone: PriceZone, direction: Direction) -> float | None:
    if not zone.targets:
        return None
    if direction == Direction.LONG:
        viable = [target for target in zone.targets if target > zone.high]
        return min(viable) if viable else None
    viable = [target for target in zone.targets if target < zone.low]
    return max(viable) if viable else None


def _build_intent(
    *,
    thesis: BeecthorThesis,
    snapshot: MarketSnapshot,
    settings: Settings,
    direction: Direction,
    zone: PriceZone,
    reason: str,
) -> Decision:
    take_profit = _first_target(zone, direction)
    if take_profit is None:
        return Decision(DecisionAction.REJECT, "No viable take-profit target in thesis zone")

    target_notional = settings.safety.default_notional_usdt
    if direction == Direction.LONG:
        target_notional = min(target_notional, settings.safety.max_notional_usdt * 0.5)
    quantity = _quantity_from_notional(target_notional, snapshot.price)
    notional = round(quantity * snapshot.price, 2)
    intent = OrderIntent(
        symbol=snapshot.symbol.upper(),
        direction=direction,
        quantity=quantity,
        notional_usdt=notional,
        leverage=min(2, settings.safety.max_leverage),
        entry_price_reference=snapshot.price,
        stop_loss=zone.stop_loss,
        take_profit=take_profit,
        reason=reason,
        source_video_id=thesis.video_id,
    )
    validate_order_intent(intent, settings)
    return Decision(DecisionAction.TRADE, reason, intent)


def evaluate_thesis(thesis: BeecthorThesis, snapshot: MarketSnapshot, settings: Settings) -> Decision:
    validate_market_snapshot(snapshot, settings)

    if thesis.confidence < 0.55:
        return Decision(DecisionAction.WAIT, "Thesis confidence below threshold")

    bearish_short = thesis.macro_bias == "bearish" and thesis.preferred_setup in {
        "short_resistance",
        "short_rejection",
    }
    if bearish_short:
        for zone in thesis.short_zones:
            if zone.contains(snapshot.price):
                return _build_intent(
                    thesis=thesis,
                    snapshot=snapshot,
                    settings=settings,
                    direction=Direction.SHORT,
                    zone=zone,
                    reason=f"Price is inside Beecthor short zone: {zone.label or zone.low}",
                )
        return Decision(DecisionAction.WAIT, "Bearish thesis active, but price is not in a short zone")

    tactical_long = thesis.preferred_setup in {"long_support", "sweep_reclaim_long"}
    if tactical_long:
        for zone in thesis.long_zones:
            if zone.contains(snapshot.price):
                return _build_intent(
                    thesis=thesis,
                    snapshot=snapshot,
                    settings=settings,
                    direction=Direction.LONG,
                    zone=zone,
                    reason=f"Price is inside Beecthor long zone: {zone.label or zone.low}",
                )
        return Decision(DecisionAction.WAIT, "Long thesis active, but price is not in a long zone")

    return Decision(DecisionAction.WAIT, "No supported playbook for thesis")
