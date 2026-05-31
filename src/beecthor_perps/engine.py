from __future__ import annotations

from pathlib import Path
from typing import Any

from .brokers.binance_usdm import BinanceUsdMFuturesClient, ProtectiveOrderFailure
from .config import Settings
from .ledger import ActiveTradeStore, JsonlLedger, utc_now_iso
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
        active_trade_store: ActiveTradeStore,
        symbol: str = "BTCUSDT",
    ) -> None:
        self.settings = settings
        self.broker = broker
        self.notifier = notifier
        self.thesis_file = thesis_file
        self.decision_ledger = decision_ledger
        self.active_trade_store = active_trade_store
        self.symbol = symbol.upper()

    def run_once(self) -> dict[str, Any]:
        active_trade = self.active_trade_store.load()
        if active_trade:
            return self.reconcile_active_trade(active_trade)

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
        external_position_amt = _position_amount(account, self.symbol)
        if abs(external_position_amt) > 0:
            self.decision_ledger.append(
                "external_position_detected",
                {
                    "state": EngineState.IN_POSITION.value,
                    "symbol": self.symbol,
                    "position_amt": external_position_amt,
                    "reason": "Existing exchange position detected without local active trade state",
                },
            )
            return {
                "state": EngineState.IN_POSITION.value,
                "symbol": self.symbol,
                "position_amt": external_position_amt,
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

        active_payload = _active_trade_payload(thesis, decision.to_dict(), result)
        self.active_trade_store.save(active_payload)
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

    def reconcile_active_trade(self, active_trade: dict[str, Any]) -> dict[str, Any]:
        if self.settings.broker != "binance" or not isinstance(self.broker, BinanceUsdMFuturesClient):
            return self._record_state(EngineState.IN_POSITION, "Active trade exists; broker reconciliation unavailable")

        symbol = str(active_trade.get("symbol") or self.symbol).upper()
        account = self.broker.account()
        amount = _position_amount(account, symbol)
        if abs(amount) > 0:
            self.decision_ledger.append(
                "position_still_open",
                {"state": EngineState.IN_POSITION.value, "symbol": symbol, "position_amt": amount},
            )
            return {"state": EngineState.IN_POSITION.value, "symbol": symbol, "position_amt": amount}

        orders = self.broker.all_orders(symbol, limit=30)
        classification = _classify_close(active_trade, orders)
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
            {"state": EngineState.WAIT.value, "symbol": symbol, "classification": classification},
        )
        self.active_trade_store.clear()
        return {"state": EngineState.WAIT.value, "symbol": symbol, "classification": classification}

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
        }
        self.decision_ledger.append("state", payload)
        return payload


def _price_near_any_zone(thesis: BeecthorThesis, price: float) -> bool:
    for zone in [*thesis.long_zones, *thesis.short_zones]:
        width = max(zone.high - zone.low, zone.high * 0.005)
        if zone.low - width <= price <= zone.high + width:
            return True
    return False


def _active_trade_payload(thesis: BeecthorThesis, decision: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    intent = decision.get("intent") or {}
    entry = result.get("entry") or {}
    stop = result.get("stop") or {}
    take_profit = result.get("take_profit") or {}
    entry_order_id = entry.get("orderId", "unknown")
    trade_id = f"{thesis.video_id}:{intent.get('symbol')}:{intent.get('direction')}:{entry_order_id}"
    return {
        "trade_id": trade_id,
        "opened_at": utc_now_iso(),
        "symbol": intent.get("symbol"),
        "direction": intent.get("direction"),
        "quantity": intent.get("quantity"),
        "source_video_id": thesis.video_id,
        "entry_order_id": entry_order_id,
        "stop_order_id": stop.get("orderId"),
        "take_profit_order_id": take_profit.get("orderId"),
        "stop_loss": intent.get("stop_loss"),
        "take_profit": intent.get("take_profit"),
    }


def _sanitize_order_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(result.get("ok")),
        "entry_order_id": (result.get("entry") or {}).get("orderId"),
        "stop_order_id": (result.get("stop") or {}).get("orderId"),
        "take_profit_order_id": (result.get("take_profit") or {}).get("orderId"),
    }


def _position_amount(account: dict[str, Any], symbol: str) -> float:
    for position in account.get("positions", []) or []:
        if position.get("symbol") == symbol:
            return float(position.get("positionAmt") or 0)
    return 0.0


def _classify_close(active_trade: dict[str, Any], orders: list[dict[str, Any]]) -> str:
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
    return "unknown"
