from __future__ import annotations

from pathlib import Path
from typing import Any

from .brokers.binance_usdm import BinanceUsdMFuturesClient, ProtectiveOrderFailure
from .config import Settings
from .ledger import ActiveTradesStore, JsonlLedger, utc_now_iso
from .models import BeecthorThesis, DecisionAction, EngineState, MarketSnapshot
from .notifications import (
    TelegramNotifier,
    format_close_position_message,
    format_critical_protection_message,
    format_open_position_message,
)
from .strategy import evaluate_confirmed_thesis
from .thesis import ThesisError, load_thesis_file


class PerpsEngine:
    def __init__(
        self,
        *,
        settings: Settings,
        broker: Any,
        notifier: TelegramNotifier,
        thesis_file: Path,
        decision_ledger: JsonlLedger,
        active_trade_store: ActiveTradesStore,
        symbol: str = "BTCUSDC",
    ) -> None:
        self.settings = settings
        self.broker = broker
        self.notifier = notifier
        self.thesis_file = thesis_file
        self.decision_ledger = decision_ledger
        self.active_trade_store = active_trade_store
        self.symbol = symbol.upper()

    def run_once(self) -> dict[str, Any]:
        active_trades = self.active_trade_store.load_all()
        if active_trades:
            return self.reconcile_active_trades(active_trades)

        try:
            thesis = load_thesis_file(self.thesis_file)
        except (OSError, ThesisError, ValueError) as exc:
            return self._record_state(EngineState.WAIT, f"No usable thesis: {exc}")

        if thesis.preferred_setup in {"wait", "no_trade"}:
            return self._record_state(EngineState.WAIT, "Latest Beecthor thesis is wait/no-trade", thesis)

        if self.settings.broker != "binance" or self.settings.perps_env != "testnet":
            return self._record_state(
                EngineState.DISABLED,
                "V1 automatic execution requires BROKER=binance and PERPS_ENV=testnet",
                thesis,
            )

        if not isinstance(self.broker, BinanceUsdMFuturesClient):
            return self._record_state(EngineState.DISABLED, "Configured broker is not Binance USD-M", thesis)

        account = self.broker.account()
        external_positions = _symbol_position_amounts(account, self.symbol)
        if any(abs(amount) > 0 for amount in external_positions.values()):
            self.decision_ledger.append(
                "external_position_detected",
                {
                    "state": EngineState.IN_POSITION.value,
                    "symbol": self.symbol,
                    "positions": external_positions,
                    "reason": "Existing exchange position detected without local active trade state",
                },
            )
            return {
                "state": EngineState.IN_POSITION.value,
                "symbol": self.symbol,
                "positions": external_positions,
                "reason": "Existing exchange position detected; no new trade will be opened",
            }

        snapshot = MarketSnapshot.now(self.symbol, self.broker.ticker_price(self.symbol))
        candles = self.broker.klines(self.symbol, interval="5m", limit=6)
        decision = evaluate_confirmed_thesis(thesis, snapshot, candles, self.settings)
        state = EngineState.TRADE_READY if decision.action == DecisionAction.TRADE else EngineState.WAIT
        if decision.action == DecisionAction.WAIT and _price_near_any_zone(thesis, snapshot.price):
            state = EngineState.ARMED

        self.decision_ledger.append(
            "decision",
            {
                "state": state.value,
                "decision": decision.to_dict(),
                "strategy": self.settings.strategy.sanitized(),
                "selected_take_profit": decision.intent.take_profit if decision.intent else None,
                "thesis_video_id": thesis.video_id,
                "price": snapshot.price,
            },
        )

        if decision.intent is None:
            return {"state": state.value, "decision": decision.to_dict()}

        try:
            result = self.broker.place_order_intent(decision.intent)
        except ProtectiveOrderFailure as exc:
            detail = exc.sanitized()
            event_id = f"critical_protection:{thesis.video_id}:{self.symbol}:{detail.get('entry_order_id')}"
            self.notifier.send_once(event_id, format_critical_protection_message(decision.intent, detail))
            self.decision_ledger.append(
                "critical_protection_failure",
                {"state": EngineState.DISABLED.value, "detail": detail, "intent": decision.to_dict()},
            )
            return {"state": EngineState.DISABLED.value, "error": "protective_order_failure", "detail": detail}

        active_payload = _active_trade_payload(thesis, decision.to_dict(), result, self.settings.position_mode)
        self.active_trade_store.add(active_payload)
        event_id = f"position_opened:{active_payload['trade_id']}"
        self.notifier.send_once(
            event_id,
            format_open_position_message(decision.intent, self.settings, thesis.preferred_setup),
        )
        self.decision_ledger.append(
            "position_opened",
            {"state": EngineState.IN_POSITION.value, "trade": active_payload},
        )
        return {"state": EngineState.IN_POSITION.value, "decision": decision.to_dict(), "result": _sanitize_order_result(result)}

    def reconcile_active_trades(self, active_trades: list[dict[str, Any]]) -> dict[str, Any]:
        if self.settings.broker != "binance" or not isinstance(self.broker, BinanceUsdMFuturesClient):
            return self._record_state(EngineState.IN_POSITION, "Active trades exist; broker reconciliation unavailable")

        account = self.broker.account()
        orders_by_symbol: dict[str, list[dict[str, Any]]] = {}
        algo_by_symbol: dict[str, list[dict[str, Any]]] = {}
        remaining: list[dict[str, Any]] = []
        closed: list[dict[str, Any]] = []

        for active_trade in active_trades:
            symbol = str(active_trade.get("symbol") or self.symbol).upper()
            if symbol not in orders_by_symbol:
                orders_by_symbol[symbol] = self.broker.all_orders(symbol, limit=50)
                algo_by_symbol[symbol] = self.broker.all_algo_orders(symbol, limit=50)

            classification = _classify_close(active_trade, orders_by_symbol[symbol], algo_by_symbol[symbol])
            if classification == "unknown":
                position_side = str(active_trade.get("position_side") or "BOTH").upper()
                amount = _position_amount(account, symbol, position_side)
                if abs(amount) > 0:
                    remaining.append(active_trade)
                    continue
                classification = "unknown_external_close"

            cancel_result = _cancel_sibling_protection(self.broker, active_trade, classification)
            closed_trade = {**active_trade, "status": "closed", "closed_at": utc_now_iso(), "classification": classification}
            closed.append(closed_trade)
            event_id = f"position_closed:{active_trade.get('trade_id')}:{classification}"
            self.notifier.send_once(
                event_id,
                format_close_position_message(
                    classification,
                    symbol,
                    str(active_trade.get("source_video_id", "")),
                ),
            )
            self.decision_ledger.append(
                "position_closed",
                {
                    "state": EngineState.WAIT.value,
                    "symbol": symbol,
                    "trade_id": active_trade.get("trade_id"),
                    "classification": classification,
                    "cancel_sibling": cancel_result,
                },
            )

        if remaining:
            self.active_trade_store.save_all(remaining)
            self.decision_ledger.append(
                "positions_still_open",
                {"state": EngineState.IN_POSITION.value, "open_count": len(remaining), "closed_count": len(closed)},
            )
            return {"state": EngineState.IN_POSITION.value, "open_count": len(remaining), "closed_count": len(closed)}

        self.active_trade_store.clear()
        self.decision_ledger.append(
            "all_positions_closed",
            {
                "state": EngineState.WAIT.value,
                "closed_count": len(closed),
            },
        )
        return {"state": EngineState.WAIT.value, "closed_count": len(closed)}

    def _record_state(
        self,
        state: EngineState,
        reason: str,
        thesis: BeecthorThesis | None = None,
    ) -> dict[str, Any]:
        payload = {
            "state": state.value,
            "reason": reason,
            "thesis_video_id": thesis.video_id if thesis else "",
            "strategy": self.settings.strategy.sanitized(),
        }
        self.decision_ledger.append("state", payload)
        return payload


def _price_near_any_zone(thesis: BeecthorThesis, price: float) -> bool:
    for zone in [*thesis.long_zones, *thesis.short_zones]:
        width = max(zone.high - zone.low, zone.high * 0.005)
        if zone.low - width <= price <= zone.high + width:
            return True
    return False


def _active_trade_payload(
    thesis: BeecthorThesis,
    decision: dict[str, Any],
    result: dict[str, Any],
    position_mode: str,
) -> dict[str, Any]:
    intent = decision.get("intent") or {}
    entry = result.get("entry") or {}
    stop = result.get("stop") or {}
    take_profit = result.get("take_profit") or {}
    entry_order_id = _order_identifier(entry) or "unknown"
    trade_id = f"{thesis.video_id}:{intent.get('symbol')}:{intent.get('direction')}:{entry_order_id}"
    return {
        "trade_id": trade_id,
        "opened_at": utc_now_iso(),
        "status": "open",
        "symbol": intent.get("symbol"),
        "direction": intent.get("direction"),
        "position_side": _active_position_side(intent.get("direction"), position_mode),
        "quantity": intent.get("quantity"),
        "notional_usdc": intent.get("notional_usdt"),
        "leverage": intent.get("leverage"),
        "source_video_id": thesis.video_id,
        "entry_order_id": entry_order_id,
        "stop_order_id": _order_identifier(stop),
        "take_profit_order_id": _order_identifier(take_profit),
        "stop_order_kind": _order_kind(stop),
        "take_profit_order_kind": _order_kind(take_profit),
        "stop_loss": intent.get("stop_loss"),
        "take_profit": intent.get("take_profit"),
    }


def _active_position_side(direction: Any, position_mode: str) -> str:
    if position_mode != "hedge":
        return "BOTH"
    return "LONG" if direction == "long" else "SHORT"


def _sanitize_order_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(result.get("ok")),
        "entry_order_id": _order_identifier(result.get("entry") or {}),
        "stop_order_id": _order_identifier(result.get("stop") or {}),
        "take_profit_order_id": _order_identifier(result.get("take_profit") or {}),
    }


def _position_amount(account: dict[str, Any], symbol: str, position_side: str = "BOTH") -> float:
    for position in account.get("positions", []) or []:
        if position.get("symbol") != symbol:
            continue
        reported_side = str(position.get("positionSide") or "BOTH").upper()
        if position_side == "BOTH" or reported_side == position_side:
            return float(position.get("positionAmt") or 0)
    return 0.0


def _symbol_position_amounts(account: dict[str, Any], symbol: str) -> dict[str, float]:
    positions: dict[str, float] = {}
    for position in account.get("positions", []) or []:
        if position.get("symbol") == symbol:
            side = str(position.get("positionSide") or "BOTH").upper()
            positions[side] = float(position.get("positionAmt") or 0)
    return positions or {"BOTH": 0.0}


def _order_identifier(payload: dict[str, Any]) -> Any:
    return payload.get("orderId") or payload.get("algoId")


def _order_kind(payload: dict[str, Any]) -> str:
    if payload.get("algoId"):
        return "algo"
    if payload.get("orderId"):
        return "order"
    return ""


def _cleanup_open_orders(broker: BinanceUsdMFuturesClient, symbol: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label, fn in {
        "orders": broker.cancel_open_orders,
        "algo_orders": broker.cancel_open_algo_orders,
    }.items():
        try:
            result[label] = fn(symbol)
        except Exception as exc:
            result[label] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return result


def _cancel_sibling_protection(
    broker: BinanceUsdMFuturesClient,
    active_trade: dict[str, Any],
    classification: str,
) -> dict[str, Any]:
    symbol = str(active_trade.get("symbol") or "").upper()
    if not symbol:
        return {"skipped": "missing_symbol"}
    if classification == "take_profit":
        return _cancel_trade_order(
            broker,
            symbol,
            active_trade.get("stop_order_kind"),
            active_trade.get("stop_order_id"),
        )
    if classification == "stop_loss":
        return _cancel_trade_order(
            broker,
            symbol,
            active_trade.get("take_profit_order_kind"),
            active_trade.get("take_profit_order_id"),
        )
    if classification == "unknown_external_close":
        return {
            "stop": _cancel_trade_order(
                broker,
                symbol,
                active_trade.get("stop_order_kind"),
                active_trade.get("stop_order_id"),
            ),
            "take_profit": _cancel_trade_order(
                broker,
                symbol,
                active_trade.get("take_profit_order_kind"),
                active_trade.get("take_profit_order_id"),
            ),
        }
    return {"skipped": classification}


def _cancel_trade_order(
    broker: BinanceUsdMFuturesClient,
    symbol: str,
    order_kind: Any,
    order_id: Any,
) -> dict[str, Any]:
    if not order_id:
        return {"skipped": "missing_order_id"}
    try:
        if str(order_kind or "").lower() == "algo":
            return {"ok": True, "result": broker.cancel_algo_order(symbol, order_id)}
        return {"ok": True, "result": broker.cancel_order(symbol, order_id)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _classify_close(
    active_trade: dict[str, Any],
    orders: list[dict[str, Any]],
    algo_orders: list[dict[str, Any]] | None = None,
) -> str:
    stop_id = str(active_trade.get("stop_order_id") or "")
    take_profit_id = str(active_trade.get("take_profit_order_id") or "")
    for order in orders:
        order_id = str(order.get("orderId") or "")
        status = str(order.get("status") or "").upper()
        if status != "FILLED":
            continue
        if order_id and order_id == take_profit_id:
            return "take_profit"
        if order_id and order_id == stop_id:
            return "stop_loss"
    for order in algo_orders or []:
        order_id = str(order.get("algoId") or "")
        status = str(order.get("algoStatus") or "").upper()
        actual_order_id = str(order.get("actualOrderId") or "")
        triggered = status in {"TRIGGERED", "FINISHED"} or bool(actual_order_id)
        if not triggered:
            continue
        if order_id and order_id == take_profit_id:
            return "take_profit"
        if order_id and order_id == stop_id:
            return "stop_loss"
    return "unknown"
