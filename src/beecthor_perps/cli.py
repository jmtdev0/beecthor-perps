from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .brokers.binance_usdm import BinanceUsdMFuturesClient
from .brokers.paper import PaperBroker
from .config import TESTNET_BASE_URL, Settings, load_env_file
from .engine import PerpsEngine
from .ledger import ActiveTradeStore, JsonlLedger
from .models import BeecthorThesis, Direction, MarketSnapshot, OrderIntent
from .notifications import NotificationLedger, TelegramNotifier
from .strategy import evaluate_thesis
from .thesis import load_thesis_file


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"


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
            "SYMBOL_ALLOWLIST": raw.get("SYMBOL_ALLOWLIST", "BTCUSDT"),
            "DEFAULT_NOTIONAL_USDT": raw.get("DEFAULT_NOTIONAL_USDT", "100"),
            "MAX_NOTIONAL_USDT": raw.get("MAX_NOTIONAL_USDT", "125"),
            "MAX_LEVERAGE": raw.get("MAX_LEVERAGE", "3"),
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
            symbols = (exchange_info or {}).get("symbols") or []
            symbol_info = symbols[0] if symbols else {}
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
        active_trade_store=ActiveTradeStore(REPO_ROOT / "data" / "active_trade.json"),
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
    check_demo.add_argument("--symbol", default="BTCUSDT", help="Futures symbol")
    check_demo.add_argument("--quantity", default=0.001, type=float, help="Test order quantity")
    check_demo.add_argument("--reference-price", default=100000.0, type=float, help="Fallback reference price")
    check_demo.set_defaults(func=cmd_check_binance_demo)

    evaluate = subparsers.add_parser("evaluate", help="Evaluate a Beecthor thesis without placing orders")
    evaluate.add_argument("--thesis", required=True, help="Path to thesis JSON")
    evaluate.add_argument("--price", required=True, type=float, help="Current BTCUSDT price")
    evaluate.add_argument("--symbol", default="BTCUSDT", help="Futures symbol")
    evaluate.set_defaults(func=cmd_evaluate)

    record = subparsers.add_parser("record-paper", help="Record a paper order intent when a setup is valid")
    record.add_argument("--thesis", required=True, help="Path to thesis JSON")
    record.add_argument("--price", required=True, type=float, help="Current BTCUSDT price")
    record.add_argument("--symbol", default="BTCUSDT", help="Futures symbol")
    record.set_defaults(func=cmd_record_paper)

    check_telegram = subparsers.add_parser("check-telegram", help="Send a Telegram test notification")
    check_telegram.set_defaults(func=cmd_check_telegram)

    run_engine = subparsers.add_parser("run-engine", help="Run the V1 thesis monitor/executor")
    run_engine.add_argument("--thesis", default="", help="Path to latest perps thesis JSON")
    run_engine.add_argument("--symbol", default="BTCUSDT", help="Futures symbol")
    run_engine.add_argument("--once", action="store_true", help="Run one engine iteration and exit")
    run_engine.add_argument("--poll-seconds", default=30, type=int, help="Delay between engine iterations")
    run_engine.set_defaults(func=cmd_run_engine)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
