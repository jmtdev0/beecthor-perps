from __future__ import annotations

from .config import Settings
from .models import BeecthorThesis, Candle, Decision, DecisionAction, Direction, MarketSnapshot, OrderIntent, PriceZone
from .safety import validate_market_snapshot, validate_order_intent


SHORT_SETUPS = {"short_resistance", "short_rejection", "short_resistance_bearish_regime"}
LONG_SETUPS = {"long_support", "sweep_reclaim_long", "long_support_sweep_reclaim"}


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


def _first_rr_qualified_target(
    *,
    zone: PriceZone,
    direction: Direction,
    entry: float,
    minimum: float,
) -> float | None:
    for target in zone.targets:
        if direction == Direction.LONG and target <= zone.high:
            continue
        if direction == Direction.SHORT and target >= zone.low:
            continue
        if _has_reward_risk(
            entry=entry,
            stop_loss=zone.stop_loss,
            take_profit=target,
            direction=direction,
            minimum=minimum,
        ):
            return target
    return None


def _select_take_profit(
    *,
    zone: PriceZone,
    direction: Direction,
    entry: float,
    min_reward_risk: float | None,
    target_selection: str,
) -> float | None:
    if target_selection == "first_rr_qualified" and min_reward_risk is not None:
        return _first_rr_qualified_target(
            zone=zone,
            direction=direction,
            entry=entry,
            minimum=min_reward_risk,
        )
    return _first_target(zone, direction)


def _build_intent(
    *,
    thesis: BeecthorThesis,
    snapshot: MarketSnapshot,
    settings: Settings,
    direction: Direction,
    zone: PriceZone,
    reason: str,
    min_reward_risk: float | None = None,
    target_selection: str = "first",
) -> Decision:
    take_profit = _select_take_profit(
        zone=zone,
        direction=direction,
        entry=snapshot.price,
        min_reward_risk=min_reward_risk,
        target_selection=target_selection,
    )
    if take_profit is None:
        if target_selection == "first_rr_qualified" and min_reward_risk is not None:
            return Decision(DecisionAction.REJECT, f"No take-profit target reaches {min_reward_risk:.1f}R")
        return Decision(DecisionAction.REJECT, "No viable take-profit target in thesis zone")
    if min_reward_risk is not None and not _has_reward_risk(
        entry=snapshot.price,
        stop_loss=zone.stop_loss,
        take_profit=take_profit,
        direction=direction,
        minimum=min_reward_risk,
    ):
        return Decision(DecisionAction.REJECT, f"Reward/risk is below {min_reward_risk:.1f}R")

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


def _has_reward_risk(
    *,
    entry: float,
    stop_loss: float,
    take_profit: float,
    direction: Direction,
    minimum: float,
) -> bool:
    if direction == Direction.LONG:
        risk = entry - stop_loss
        reward = take_profit - entry
    else:
        risk = stop_loss - entry
        reward = entry - take_profit
    return risk > 0 and reward > 0 and reward / risk >= minimum


def _closed(candles: list[Candle]) -> list[Candle]:
    return [candle for candle in candles if candle.closed]


def _long_reclaim_is_clear(zone: PriceZone, candles: list[Candle]) -> bool:
    closed = _closed(candles)[-4:]
    if len(closed) < 2:
        return False
    reclaim_candle = closed[-2]
    hold_candle = closed[-1]
    sweep_low = min(candle.low for candle in closed)
    touched_zone = any(candle.low <= zone.high for candle in closed)
    return (
        touched_zone
        and reclaim_candle.close > zone.high
        and hold_candle.close > zone.high
        and hold_candle.low > sweep_low
    )


def _long_one_5m_reclaim_is_clear(zone: PriceZone, candles: list[Candle]) -> bool:
    closed = _closed(candles)[-4:]
    if len(closed) < 1:
        return False
    reclaim_candle = closed[-1]
    touched_zone = any(candle.low <= zone.high for candle in closed)
    return touched_zone and reclaim_candle.close > zone.high


def _short_rejection_is_clear(zone: PriceZone, candles: list[Candle]) -> bool:
    closed = _closed(candles)[-4:]
    if len(closed) < 2:
        return False
    rejection_candle = closed[-2]
    hold_candle = closed[-1]
    sweep_high = max(candle.high for candle in closed)
    touched_zone = any(candle.high >= zone.low for candle in closed)
    return (
        touched_zone
        and rejection_candle.close < zone.low
        and hold_candle.close < zone.low
        and hold_candle.high < sweep_high
    )


def _short_one_5m_rejection_is_clear(zone: PriceZone, candles: list[Candle]) -> bool:
    closed = _closed(candles)[-4:]
    if len(closed) < 1:
        return False
    rejection_candle = closed[-1]
    touched_zone = any(candle.high >= zone.low for candle in closed)
    return touched_zone and rejection_candle.close < zone.low


def _long_confirmation_is_clear(zone: PriceZone, candles: list[Candle], settings: Settings) -> bool:
    if settings.strategy.confirmation_policy == "one_5m":
        return _long_one_5m_reclaim_is_clear(zone, candles)
    return _long_reclaim_is_clear(zone, candles)


def _short_confirmation_is_clear(zone: PriceZone, candles: list[Candle], settings: Settings) -> bool:
    if settings.strategy.confirmation_policy == "one_5m":
        return _short_one_5m_rejection_is_clear(zone, candles)
    return _short_rejection_is_clear(zone, candles)


def evaluate_thesis(thesis: BeecthorThesis, snapshot: MarketSnapshot, settings: Settings) -> Decision:
    validate_market_snapshot(snapshot, settings)

    if thesis.confidence < 0.55:
        return Decision(DecisionAction.WAIT, "Thesis confidence below threshold")

    bearish_short = thesis.macro_bias == "bearish" and thesis.preferred_setup in SHORT_SETUPS
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

    tactical_long = thesis.preferred_setup in LONG_SETUPS
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


def evaluate_confirmed_thesis(
    thesis: BeecthorThesis,
    snapshot: MarketSnapshot,
    candles: list[Candle],
    settings: Settings,
) -> Decision:
    validate_market_snapshot(snapshot, settings)

    if thesis.preferred_setup in {"wait", "no_trade"}:
        return Decision(DecisionAction.WAIT, "Thesis is wait/no-trade")
    if thesis.confidence < 0.55:
        return Decision(DecisionAction.WAIT, "Thesis confidence below threshold")

    if thesis.preferred_setup in SHORT_SETUPS:
        if thesis.macro_bias not in {"bearish", "mixed", "neutral", "unknown"}:
            return Decision(DecisionAction.WAIT, "Short setup contradicts macro bias")
        for zone in thesis.short_zones:
            if _short_confirmation_is_clear(zone, candles, settings):
                return _build_intent(
                    thesis=thesis,
                    snapshot=snapshot,
                    settings=settings,
                    direction=Direction.SHORT,
                    zone=zone,
                    reason=f"Clear 5m rejection from Beecthor short zone: {zone.label or zone.low}",
                    min_reward_risk=settings.strategy.min_reward_risk,
                    target_selection=settings.strategy.target_selection,
                )
        return Decision(DecisionAction.WAIT, "No clear 5m short rejection yet")

    if thesis.preferred_setup in LONG_SETUPS:
        for zone in thesis.long_zones:
            if _long_confirmation_is_clear(zone, candles, settings):
                return _build_intent(
                    thesis=thesis,
                    snapshot=snapshot,
                    settings=settings,
                    direction=Direction.LONG,
                    zone=zone,
                    reason=f"Clear 5m reclaim from Beecthor long zone: {zone.label or zone.low}",
                    min_reward_risk=settings.strategy.min_reward_risk,
                    target_selection=settings.strategy.target_selection,
                )
        return Decision(DecisionAction.WAIT, "No clear 5m long reclaim yet")

    return Decision(DecisionAction.WAIT, "No supported confirmed playbook for thesis")
