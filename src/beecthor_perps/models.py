from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"


class DecisionAction(StrEnum):
    WAIT = "wait"
    TRADE = "trade"
    REJECT = "reject"


class EngineState(StrEnum):
    WAIT = "wait"
    ARMED = "armed"
    TRADE_READY = "trade_ready"
    IN_POSITION = "in_position"
    DISABLED = "disabled"


@dataclass(frozen=True)
class PriceZone:
    low: float
    high: float
    stop_loss: float
    targets: list[float]
    label: str = ""

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high


@dataclass(frozen=True)
class BeecthorThesis:
    video_id: str
    created_at: str
    macro_bias: str
    preferred_setup: str
    valid_until: str
    confidence: float
    schema_version: int = 1
    symbol: str = "BTCUSDT"
    generated_at: str = ""
    short_zones: list[PriceZone] = field(default_factory=list)
    long_zones: list[PriceZone] = field(default_factory=list)
    invalidation_levels: list[Any] = field(default_factory=list)
    no_trade_conditions: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BeecthorThesis":
        def zones(key: str) -> list[PriceZone]:
            parsed: list[PriceZone] = []
            for raw_zone in payload.get(key, []) or []:
                parsed.append(
                    PriceZone(
                        low=float(raw_zone["low"]),
                        high=float(raw_zone["high"]),
                        stop_loss=float(raw_zone["stop_loss"]),
                        targets=[float(value) for value in raw_zone.get("targets", [])],
                        label=str(raw_zone.get("label", "")),
                    )
                )
            return parsed

        return cls(
            video_id=str(payload.get("video_id", "")),
            created_at=str(payload.get("created_at", "")),
            macro_bias=str(payload.get("macro_bias", "unknown")).lower(),
            preferred_setup=str(payload.get("preferred_setup", "no_trade")).lower(),
            valid_until=str(payload.get("valid_until", "")),
            confidence=float(payload.get("confidence", 0.0)),
            schema_version=int(payload.get("schema_version", 1)),
            symbol=str(payload.get("symbol", "BTCUSDT")).upper(),
            generated_at=str(payload.get("generated_at", "")),
            short_zones=zones("short_zones"),
            long_zones=zones("long_zones"),
            invalidation_levels=list(payload.get("invalidation_levels", []) or []),
            no_trade_conditions=[str(item) for item in payload.get("no_trade_conditions", []) or []],
            notes=str(payload.get("notes", "")),
        )


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    price: float
    observed_at: datetime
    recent_high: float | None = None
    recent_low: float | None = None

    @classmethod
    def now(cls, symbol: str, price: float) -> "MarketSnapshot":
        return cls(symbol=symbol.upper(), price=price, observed_at=datetime.now(UTC))


@dataclass(frozen=True)
class Candle:
    symbol: str
    interval: str
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    close_time: datetime
    closed: bool = True


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    direction: Direction
    quantity: float
    notional_usdt: float
    leverage: int
    entry_price_reference: float
    stop_loss: float
    take_profit: float
    reason: str
    source_video_id: str = ""

    @property
    def entry_side(self) -> str:
        return "BUY" if self.direction == Direction.LONG else "SELL"

    @property
    def exit_side(self) -> str:
        return "SELL" if self.direction == Direction.LONG else "BUY"


@dataclass(frozen=True)
class Decision:
    action: DecisionAction
    reason: str
    intent: OrderIntent | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"action": self.action.value, "reason": self.reason}
        if self.intent:
            result["intent"] = {
                "symbol": self.intent.symbol,
                "direction": self.intent.direction.value,
                "quantity": self.intent.quantity,
                "notional_usdt": self.intent.notional_usdt,
                "leverage": self.intent.leverage,
                "entry_price_reference": self.intent.entry_price_reference,
                "stop_loss": self.intent.stop_loss,
                "take_profit": self.intent.take_profit,
                "entry_side": self.intent.entry_side,
                "exit_side": self.intent.exit_side,
                "reason": self.intent.reason,
                "source_video_id": self.intent.source_video_id,
            }
        return result
