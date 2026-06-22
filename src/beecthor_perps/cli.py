from __future__ import annotations

import argparse
import json
import time
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Any

from .brokers.binance_usdm import BinanceUsdMFuturesClient
from .brokers.paper import PaperBroker
from .config import TESTNET_BASE_URL, Settings, load_env_file
from .engine import PerpsEngine
from .ledger import ActiveTradesStore, JsonlLedger, utc_now_iso
from .models import BeecthorThesis, Direction, MarketSnapshot, OrderIntent
from .notifications import NotificationLedger, TelegramNotifier, format_open_position_message
from .safety import validate_active_trade_limits, validate_order_intent
from .strategy import evaluate_thesis
from .thesis import load_thesis_file


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
ACTIVE_TRADES_FILE = REPO_ROOT / "data" / "active_trades.json"
LEGACY_ACTIVE_TRADE_FILE = REPO_ROOT / "data" / "active_trade.json"


def _settings(args: argparse.Namespace) -> Settings:
    env_file = Path(args.env_file) if getattr(args, "env_file", "") else DEFAULT_ENV_FILE
    return Settings.from_env(env_file=env_file)


def _testnet_binance_settings(args: argparse.Namespace) -> Settings:
    env_file = Path(args.env_file) if getattr(args, "env_file", "") else DEFAULT_ENV_FILE
    raw = load_env_file(env_file)
    return Settings.from_env(
        env={
            **raw,
            "PERPS_ENV": "testnet",
            "BROKER": "binance",
            "BINANCE_BASE_URL": TESTNET_BASE_URL,
            "SYMBOL_ALLOWLIST": raw.get("SYMBOL_ALLOWLIST", "BTCUSDC,BTCUSDT"),
            "DEFAULT_NOTIONAL_USDC": raw.get("DEFAULT_NOTIONAL_USDC", raw.get("DEFAULT_NOTIONAL_USDT", "100")),
            "MAX_NOTIONAL_USDC": raw.get("MAX_NOTIONAL_USDC", raw.get("MAX_NOTIONAL_USDT", "150")),
            "MAX_LEVERAGE": raw.get("MAX_LEVERAGE", "5"),
        }
    )


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def build_broker(settings: Settings):
    if settings.broker == "paper":
        return PaperBroker(REPO_ROOT / "logs" / "paper_ledger.jsonl")
    return BinanceUsdMFuturesClient(settings)


def build_notifier(settings: Settings) -> TelegramNotifier:
    return TelegramNotifier(settings, NotificationLedger(REPO_ROOT / "logs" / "notification_ledger.jsonl"))


def build_active_trades_store() -> ActiveTradesStore:
    return ActiveTradesStore(ACTIVE_TRADES_FILE, LEGACY_ACTIVE_TRADE_FILE)


def cmd_status(args: argparse.Namespace) -> int:
    settings = _settings(args)
    broker = build_broker(settings)
    _print_json({"settings": settings.sanitized(), "broker": broker.status()})
    return 0


def cmd_check_binance_demo(args: argparse.Namespace) -> int:
    settings = _testnet_binance_settings(args)
    client = BinanceUsdMFuturesClient(settings)
    result: dict[str, object] = {"settings": settings.sanitized(), "checks": []}
    checks: list[dict[str, object]] = result["checks"]  # type: ignore[assignment]

    def check(name: str, fn):
        try:
            value = fn()
            checks.append({"name": name, "ok": True, "result": value})
            return value
        except Exception as exc:
            checks.append({"name": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return None

    check("public_ping", client.ping)
    check("public_server_time", client.server_time)
    ticker = check(
        f"public_{args.symbol.lower()}_ticker",
        lambda: client._request("GET", "/fapi/v1/ticker/price", params={"symbol": args.symbol}),
    )
    exchange_info = check(
        f"public_exchange_info_{args.symbol.lower()}",
        lambda: client._request("GET", "/fapi/v1/exchangeInfo", params={"symbol": args.symbol}),
    )
    check("signed_account", client.account)

    price = float((ticker or {}).get("price") or args.reference_price)
    quantity = args.quantity
    intent = OrderIntent(
        symbol=args.symbol,
        direction=Direction.SHORT,
        quantity=quantity,
        notional_usdt=round(price * quantity, 2),
        leverage=2,
        entry_price_reference=price,
        stop_loss=round(price * 1.01, 2),
        take_profit=round(price * 0.99, 2),
        reason="Connectivity validation only: Binance /order/test does not place an order.",
        source_video_id="connectivity-test",
    )
    check(f"signed_order_test_market_short_{quantity:g}_{args.symbol.lower()}", lambda: client.new_test_order(intent))

    for item in checks:
        if item["name"] == "signed_account" and item.get("ok"):
            payload = item.get("result") or {}
            assets = payload.get("assets") or []
            positions = payload.get("positions") or []
            item["result"] = {
                "can_read_account": True,
                "feeTier": payload.get("feeTier"),
                "canTrade": payload.get("canTrade"),
                "assets_count": len(assets),
                "positions_count": len(positions),
                f"has_{args.symbol}_position_entry": any(pos.get("symbol") == args.symbol for pos in positions),
            }
        if item["name"] == f"public_exchange_info_{args.symbol.lower()}" and item.get("ok"):
            symbol_info = _symbol_info(exchange_info or {}, args.symbol)
            item["result"] = {
                "symbol": symbol_info.get("symbol"),
                "status": symbol_info.get("status"),
                "contractType": symbol_info.get("contractType"),
                "quantityPrecision": symbol_info.get("quantityPrecision"),
                "pricePrecision": symbol_info.get("pricePrecision"),
                "orderTypes": symbol_info.get("orderTypes"),
            }

    _print_json(result)
    return 0


def load_thesis(path: Path) -> BeecthorThesis:
    return load_thesis_file(path)


def cmd_evaluate(args: argparse.Namespace) -> int:
    settings = _settings(args)
    thesis = load_thesis(Path(args.thesis))
    snapshot = MarketSnapshot.now(args.symbol, args.price)
    decision = evaluate_thesis(thesis, snapshot, settings)
    _print_json(decision.to_dict())
    return 0


def cmd_record_paper(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if settings.broker != "paper":
        raise SystemExit("record-paper requires BROKER=paper")
    thesis = load_thesis(Path(args.thesis))
    snapshot = MarketSnapshot.now(args.symbol, args.price)
    decision = evaluate_thesis(thesis, snapshot, settings)
    if decision.intent is None:
        _print_json(decision.to_dict())
        return 0
    result = PaperBroker(REPO_ROOT / "logs" / "paper_ledger.jsonl").place_order_intent(decision.intent)
    _print_json({"decision": decision.to_dict(), "result": result})
    return 0


def cmd_check_telegram(args: argparse.Namespace) -> int:
    settings = _settings(args)
    notifier = build_notifier(settings)
    event_id = f"check_telegram:{int(time.time())}"
    result = notifier.send_once(
        event_id,
        "Beecthor Perps: prueba de notificaciones Telegram OK. No se ha tocado Binance.",
    )
    _print_json(result)
    return 0


def _position_amount(account: dict[str, Any], symbol: str) -> float:
    for position in account.get("positions", []) or []:
        if position.get("symbol") == symbol:
            return float(position.get("positionAmt") or 0)
    return 0.0


def _exchange_hedge_enabled(client: BinanceUsdMFuturesClient) -> bool:
    return bool(client.position_mode().get("dualSidePosition"))


def _nonzero_positions(account: dict[str, Any], symbols: list[str]) -> list[dict[str, Any]]:
    wanted = {symbol.upper() for symbol in symbols}
    result = []
    for position in account.get("positions", []) or []:
        symbol = str(position.get("symbol") or "").upper()
        if wanted and symbol not in wanted:
            continue
        amount = float(position.get("positionAmt") or 0)
        if amount == 0:
            continue
        result.append(
            {
                "symbol": symbol,
                "positionSide": position.get("positionSide", "BOTH"),
                "positionAmt": amount,
                "entryPrice": position.get("entryPrice"),
                "breakEvenPrice": position.get("breakEvenPrice"),
                "leverage": position.get("leverage"),
            }
        )
    return result


def _one_way_interference_reason(direction: Direction, symbol: str, position_amt: float) -> str:
    if direction == Direction.LONG and position_amt < 0:
        return (
            f"Refusing manual long: Binance is in One-way Mode and {symbol} has an existing short "
            f"amount {position_amt}. A BUY would reduce or close that short."
        )
    if direction == Direction.SHORT and position_amt > 0:
        return (
            f"Refusing manual short: Binance is in One-way Mode and {symbol} has an existing long "
            f"amount {position_amt}. A SELL would reduce or close that long."
        )
    return ""


def _symbol_filters(exchange_info: dict[str, Any], symbol: str) -> dict[str, dict[str, str]]:
    symbol_info = _symbol_info(exchange_info, symbol)
    return {item.get("filterType", ""): item for item in symbol_info.get("filters", [])}


def _symbol_info(exchange_info: dict[str, Any], symbol: str) -> dict[str, Any]:
    symbols = exchange_info.get("symbols") or []
    symbol_info = next((item for item in symbols if item.get("symbol") == symbol), None)
    if symbol_info is None:
        raise ValueError(f"Exchange info did not include {symbol}")
    return symbol_info


def _ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING) * step


def _quantity_from_quote_notional(
    *,
    client: BinanceUsdMFuturesClient,
    symbol: str,
    notional: float,
    price: float,
) -> float:
    filters = _symbol_filters(client.exchange_info(symbol), symbol)
    lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE") or {}
    min_notional_filter = filters.get("MIN_NOTIONAL") or {}
    step = Decimal(str(lot.get("stepSize") or "0.001"))
    min_qty = Decimal(str(lot.get("minQty") or "0"))
    min_notional = Decimal(str(min_notional_filter.get("notional") or "0"))
    reference_price = Decimal(str(price))
    requested_notional = Decimal(str(notional))
    required_notional = max(requested_notional, min_notional)
    quantity = max(required_notional / reference_price, min_qty)
    quantity = _ceil_to_step(quantity, step)
    if quantity * reference_price < min_notional:
        quantity = _ceil_to_step(min_notional / reference_price, step)
    return float(quantity)


def _manual_active_payload(
    intent: OrderIntent,
    result: dict[str, Any],
    label: str,
    position_mode: str,
) -> dict[str, Any]:
    entry = result.get("entry") or {}
    stop = result.get("stop") or {}
    take_profit = result.get("take_profit") or {}
    entry_order_id = _order_identifier(entry) or "unknown"
    return {
        "trade_id": f"{label}:{intent.symbol}:{intent.direction.value}:{entry_order_id}",
        "opened_at": utc_now_iso(),
        "status": "open",
        "symbol": intent.symbol,
        "direction": intent.direction.value,
        "position_side": intent.hedge_position_side if position_mode == "hedge" else "BOTH",
        "quantity": intent.quantity,
        "notional_usdc": intent.notional_usdt,
        "notional_usdt": intent.notional_usdt,
        "leverage": intent.leverage,
        "source_video_id": label,
        "entry_order_id": entry_order_id,
        "stop_order_id": _order_identifier(stop),
        "take_profit_order_id": _order_identifier(take_profit),
        "stop_order_kind": _order_kind(stop),
        "take_profit_order_kind": _order_kind(take_profit),
        "stop_loss": intent.stop_loss if intent.stop_loss > 0 else None,
        "stop_loss_omitted": intent.stop_loss <= 0,
        "take_profit": intent.take_profit,
        "label": label,
    }


def _intent_payload(intent: OrderIntent) -> dict[str, Any]:
    return {
        "symbol": intent.symbol,
        "direction": intent.direction.value,
        "quantity": intent.quantity,
        "notional_usdt": intent.notional_usdt,
        "leverage": intent.leverage,
        "entry_price_reference": intent.entry_price_reference,
        "stop_loss": intent.stop_loss if intent.stop_loss > 0 else None,
        "stop_loss_omitted": intent.stop_loss <= 0,
        "take_profit": intent.take_profit,
        "entry_side": intent.entry_side,
        "exit_side": intent.exit_side,
        "position_side": intent.hedge_position_side,
        "reason": intent.reason,
        "source_video_id": intent.source_video_id,
    }


def _order_identifier(payload: dict[str, Any]) -> Any:
    return payload.get("orderId") or payload.get("algoId")


def _order_kind(payload: dict[str, Any]) -> str:
    if payload.get("algoId"):
        return "algo"
    if payload.get("orderId"):
        return "order"
    return ""


def cmd_open_manual(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if settings.broker != "binance" or settings.perps_env != "testnet":
        raise SystemExit("open-manual requires BROKER=binance and PERPS_ENV=testnet")
    client = BinanceUsdMFuturesClient(settings)
    notifier = build_notifier(settings)
    active_store = build_active_trades_store()
    decision_ledger = JsonlLedger(REPO_ROOT / "logs" / "decision_ledger.jsonl")
    active_trades = active_store.load_all()

    symbol = args.symbol.upper()
    exchange_hedge_enabled = _exchange_hedge_enabled(client)
    if settings.position_mode == "hedge" and not exchange_hedge_enabled:
        raise SystemExit(
            "Refusing manual order: POSITION_MODE=hedge but Binance is still in One-way Mode. "
            "Run position-mode set-hedge only after all positions and orders are closed."
        )
    if settings.position_mode == "one_way" and exchange_hedge_enabled:
        raise SystemExit("Refusing manual order: POSITION_MODE=one_way but Binance is in Hedge Mode.")

    account = client.account()
    position_amt = _position_amount(account, symbol)
    direction = Direction(args.direction)
    if settings.position_mode == "one_way":
        interference = _one_way_interference_reason(direction, symbol, position_amt)
        if interference:
            raise SystemExit(interference)
        if abs(position_amt) > 0:
            raise SystemExit(f"Refusing manual order: existing One-way {symbol} position amount is {position_amt}")
        open_orders = client.open_orders(symbol)
        if open_orders:
            raise SystemExit(f"Refusing manual order: {symbol} has {len(open_orders)} open orders")
        open_algo_orders = client.open_algo_orders(symbol)
        if open_algo_orders:
            raise SystemExit(f"Refusing manual order: {symbol} has {len(open_algo_orders)} open algo orders")

    price = client.ticker_price(symbol)
    quantity = args.quantity
    if quantity is None:
        quantity = _quantity_from_quote_notional(
            client=client,
            symbol=symbol,
            notional=args.notional,
            price=price,
        )
    notional = round(quantity * price, 2)
    require_stop_loss = not args.no_stop_loss
    intent = OrderIntent(
        symbol=symbol,
        direction=direction,
        quantity=quantity,
        notional_usdt=notional,
        leverage=args.leverage,
        entry_price_reference=price,
        stop_loss=args.stop_loss or 0.0,
        take_profit=args.take_profit,
        reason=(
            f"Manual user order: {args.label}"
            if require_stop_loss
            else f"Manual Demo user order without stop loss: {args.label}"
        ),
        source_video_id=args.label,
    )
    validate_order_intent(intent, settings, require_stop_loss=require_stop_loss)
    validate_active_trade_limits(intent, settings, active_trades)
    payload = {
        "label": args.label,
        "dry_run": args.dry_run,
        "intent": _intent_payload(intent),
        "reference_price": price,
        "requested_notional": args.notional,
        "computed_notional": notional,
        "stop_loss_required": require_stop_loss,
    }
    if args.dry_run:
        _print_json({"ok": True, **payload})
        return 0

    result = client.place_order_intent(intent, require_stop_loss=require_stop_loss)
    active_payload = _manual_active_payload(intent, result, args.label, settings.position_mode)
    active_store.add(active_payload)
    event_id = f"position_opened:{active_payload['trade_id']}"
    notification = notifier.send_once(event_id, format_open_position_message(intent, settings, args.label))
    decision_ledger.append(
        "manual_position_opened",
        {
            "state": "in_position",
            "label": args.label,
            "intent": _intent_payload(intent),
            "trade": active_payload,
            "notification": notification,
        },
    )
    _print_json({"ok": True, "trade": active_payload, "result": result, "notification": notification})
    return 0


def cmd_position_mode_status(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if settings.broker != "binance" or settings.perps_env != "testnet":
        raise SystemExit("position-mode status requires BROKER=binance and PERPS_ENV=testnet")
    client = BinanceUsdMFuturesClient(settings)
    symbols = [symbol.upper() for symbol in (args.symbols or sorted(settings.safety.symbol_allowlist))]
    account = client.account()
    mode = client.position_mode()
    positions = _nonzero_positions(account, symbols)
    open_order_counts = {
        symbol: {
            "orders": len(client.open_orders(symbol)),
            "algo_orders": len(client.open_algo_orders(symbol)),
        }
        for symbol in symbols
    }
    _print_json(
        {
            "configured_position_mode": settings.position_mode,
            "exchange_dual_side_position": bool(mode.get("dualSidePosition")),
            "symbols": symbols,
            "positions": positions,
            "open_order_counts": open_order_counts,
        }
    )
    return 0


def cmd_position_mode_set_hedge(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if settings.broker != "binance" or settings.perps_env != "testnet":
        raise SystemExit("position-mode set-hedge requires BROKER=binance and PERPS_ENV=testnet")
    client = BinanceUsdMFuturesClient(settings)
    symbols = sorted(settings.safety.symbol_allowlist)
    account = client.account()
    positions = _nonzero_positions(account, symbols)
    open_order_counts = {
        symbol: len(client.open_orders(symbol)) + len(client.open_algo_orders(symbol))
        for symbol in symbols
    }
    active_order_symbols = {symbol: count for symbol, count in open_order_counts.items() if count > 0}
    if positions or active_order_symbols:
        raise SystemExit(
            "Refusing to enable Hedge Mode: Binance requires all positions and open orders to be closed first. "
            f"positions={positions}; open_orders={active_order_symbols}"
        )
    result = client.set_position_mode(True)
    _print_json({"ok": True, "result": result, "exchange_position_mode": client.position_mode()})
    return 0


def cmd_list_active_trades(args: argparse.Namespace) -> int:
    _print_json({"trades": build_active_trades_store().load_all()})
    return 0


def cmd_reconcile_trades(args: argparse.Namespace) -> int:
    settings = _settings(args)
    store = build_active_trades_store()
    active_trades = store.load_all()
    if not active_trades:
        _print_json({"state": "wait", "reason": "No active trades"})
        return 0
    engine = PerpsEngine(
        settings=settings,
        broker=build_broker(settings),
        notifier=build_notifier(settings),
        thesis_file=Path(settings.beecthor_thesis_file or "data/perps_theses/latest.json"),
        decision_ledger=JsonlLedger(REPO_ROOT / "logs" / "decision_ledger.jsonl"),
        active_trade_store=store,
        symbol=args.symbol,
    )
    _print_json(engine.reconcile_active_trades(active_trades))
    return 0


def cmd_run_engine(args: argparse.Namespace) -> int:
    settings = _settings(args)
    thesis_arg = args.thesis or settings.beecthor_thesis_file
    if not thesis_arg:
        raise SystemExit("run-engine requires --thesis or BEECTHOR_THESIS_FILE")
    thesis_file = Path(thesis_arg)
    engine = PerpsEngine(
        settings=settings,
        broker=build_broker(settings),
        notifier=build_notifier(settings),
        thesis_file=thesis_file,
        decision_ledger=JsonlLedger(REPO_ROOT / "logs" / "decision_ledger.jsonl"),
        active_trade_store=build_active_trades_store(),
        symbol=args.symbol,
    )
    if args.once:
        _print_json(engine.run_once())
        return 0

    while True:
        _print_json(engine.run_once())
        time.sleep(args.poll_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Beecthor perpetual futures automation")
    parser.add_argument("--env-file", default="", help="Path to .env file. Defaults to repo .env.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Show sanitized runtime settings")
    status.set_defaults(func=cmd_status)

    check_demo = subparsers.add_parser(
        "check-binance-demo",
        help="Run safe Binance Demo connectivity checks including /order/test",
    )
    check_demo.add_argument("--symbol", default="BTCUSDC", help="Futures symbol")
    check_demo.add_argument("--quantity", default=0.001, type=float, help="Test order quantity")
    check_demo.add_argument("--reference-price", default=100000.0, type=float, help="Fallback reference price")
    check_demo.set_defaults(func=cmd_check_binance_demo)

    evaluate = subparsers.add_parser("evaluate", help="Evaluate a Beecthor thesis without placing orders")
    evaluate.add_argument("--thesis", required=True, help="Path to thesis JSON")
    evaluate.add_argument("--price", required=True, type=float, help="Current BTC price")
    evaluate.add_argument("--symbol", default="BTCUSDC", help="Futures symbol")
    evaluate.set_defaults(func=cmd_evaluate)

    record = subparsers.add_parser("record-paper", help="Record a paper order intent when a setup is valid")
    record.add_argument("--thesis", required=True, help="Path to thesis JSON")
    record.add_argument("--price", required=True, type=float, help="Current BTC price")
    record.add_argument("--symbol", default="BTCUSDC", help="Futures symbol")
    record.set_defaults(func=cmd_record_paper)

    check_telegram = subparsers.add_parser("check-telegram", help="Send a Telegram test notification")
    check_telegram.set_defaults(func=cmd_check_telegram)

    open_manual = subparsers.add_parser("open-manual", help="Open a manual Binance Demo position with required TP")
    open_manual.add_argument("--symbol", default="BTCUSDC", help="Futures symbol")
    open_manual.add_argument("--direction", choices=[Direction.LONG.value, Direction.SHORT.value], required=True)
    open_manual.add_argument("--notional", default=100.0, type=float, help="Requested quote notional")
    open_manual.add_argument("--quantity", type=float, help="Explicit BTC quantity. Overrides --notional.")
    open_manual.add_argument("--leverage", default=5, type=int, help="Leverage to set before entry")
    open_manual.add_argument("--take-profit", required=True, type=float, help="Take-profit trigger price")
    stop_policy = open_manual.add_mutually_exclusive_group(required=True)
    stop_policy.add_argument("--stop-loss", type=float, help="Stop-loss trigger price")
    stop_policy.add_argument(
        "--no-stop-loss",
        action="store_true",
        help="Explicitly omit the stop-loss for this manual Binance Demo order only",
    )
    open_manual.add_argument("--label", default="jmt-order", help="Trace label/source for logs and notifications")
    open_manual.add_argument("--dry-run", action="store_true", help="Validate and print intent without placing orders")
    open_manual.set_defaults(func=cmd_open_manual)

    position_mode = subparsers.add_parser("position-mode", help="Inspect or change Binance position mode")
    position_mode_sub = position_mode.add_subparsers(dest="position_mode_command", required=True)
    position_status = position_mode_sub.add_parser("status", help="Show Binance Demo position mode and open exposure")
    position_status.add_argument("--symbols", nargs="*", help="Symbols to inspect. Defaults to SYMBOL_ALLOWLIST.")
    position_status.set_defaults(func=cmd_position_mode_status)
    position_set_hedge = position_mode_sub.add_parser("set-hedge", help="Enable Hedge Mode only when account is flat")
    position_set_hedge.set_defaults(func=cmd_position_mode_set_hedge)

    list_trades = subparsers.add_parser("list-active-trades", help="List locally tracked active trades")
    list_trades.set_defaults(func=cmd_list_active_trades)

    reconcile = subparsers.add_parser("reconcile-trades", help="Reconcile tracked active trades with Binance")
    reconcile.add_argument("--symbol", default="BTCUSDC", help="Default symbol for legacy active trades")
    reconcile.set_defaults(func=cmd_reconcile_trades)

    run_engine = subparsers.add_parser("run-engine", help="Run the V1 thesis monitor/executor")
    run_engine.add_argument("--thesis", default="", help="Path to latest perps thesis JSON")
    run_engine.add_argument("--symbol", default="BTCUSDC", help="Futures symbol")
    run_engine.add_argument("--once", action="store_true", help="Run one engine iteration and exit")
    run_engine.add_argument("--poll-seconds", default=3600, type=int, help="Delay between engine iterations")
    run_engine.set_defaults(func=cmd_run_engine)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
