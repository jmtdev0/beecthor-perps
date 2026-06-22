import tempfile
import unittest
from pathlib import Path

from beecthor_perps.config import Settings
from beecthor_perps.engine import _active_position_side, _cancel_sibling_protection, _classify_close
from beecthor_perps.notifications import NotificationLedger, TelegramNotifier, quote_asset


class NotificationTests(unittest.TestCase):
    def test_quote_asset_supports_both_btc_demo_pairs(self):
        self.assertEqual(quote_asset("BTCUSDC"), "USDC")
        self.assertEqual(quote_asset("BTCUSDT"), "USDT")

    def test_send_once_deduplicates_events(self):
        settings = Settings.from_env(
            env={
                "TELEGRAM_NOTIFICATIONS_ENABLED": "true",
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_CHAT_ID": "chat",
            }
        )
        calls = []

        def fake_sender(url, payload):
            calls.append((url, payload))

        with tempfile.TemporaryDirectory() as tmpdir:
            notifier = TelegramNotifier(
                settings,
                NotificationLedger(Path(tmpdir) / "notifications.jsonl"),
                sender=fake_sender,
            )
            first = notifier.send_once("event-1", "hello")
            second = notifier.send_once("event-1", "hello")

        self.assertTrue(first["ok"])
        self.assertTrue(second["skipped"])
        self.assertEqual(len(calls), 1)

    def test_classifies_take_profit_and_stop_loss_closures(self):
        active_trade = {"stop_order_id": 11, "take_profit_order_id": 22}

        self.assertEqual(
            _classify_close(active_trade, [{"orderId": 22, "status": "FILLED"}]),
            "take_profit",
        )
        self.assertEqual(
            _classify_close(active_trade, [{"orderId": 11, "status": "FILLED"}]),
            "stop_loss",
        )
        self.assertEqual(
            _classify_close(active_trade, [{"orderId": 33, "status": "FILLED"}]),
            "unknown",
        )

    def test_classifies_algo_take_profit_and_stop_loss_closures(self):
        active_trade = {"stop_order_id": 101, "take_profit_order_id": 202}

        self.assertEqual(
            _classify_close(active_trade, [], [{"algoId": 202, "algoStatus": "TRIGGERED"}]),
            "take_profit",
        )
        self.assertEqual(
            _classify_close(active_trade, [], [{"algoId": 101, "algoStatus": "FINISHED"}]),
            "stop_loss",
        )
        self.assertEqual(
            _classify_close(active_trade, [], [{"algoId": 202, "algoStatus": "NEW"}]),
            "unknown",
        )

    def test_active_position_side_matches_position_mode(self):
        self.assertEqual(_active_position_side("long", "one_way"), "BOTH")
        self.assertEqual(_active_position_side("short", "one_way"), "BOTH")
        self.assertEqual(_active_position_side("long", "hedge"), "LONG")
        self.assertEqual(_active_position_side("short", "hedge"), "SHORT")

    def test_take_profit_cancels_stop_sibling(self):
        broker = FakeBroker()
        active_trade = {
            "symbol": "BTCUSDC",
            "stop_order_kind": "algo",
            "stop_order_id": 101,
            "take_profit_order_kind": "algo",
            "take_profit_order_id": 202,
        }

        result = _cancel_sibling_protection(broker, active_trade, "take_profit")

        self.assertTrue(result["ok"])
        self.assertEqual(broker.cancelled_algo, [("BTCUSDC", 101)])

    def test_stop_loss_cancels_take_profit_sibling(self):
        broker = FakeBroker()
        active_trade = {
            "symbol": "BTCUSDC",
            "stop_order_kind": "algo",
            "stop_order_id": 101,
            "take_profit_order_kind": "algo",
            "take_profit_order_id": 202,
        }

        result = _cancel_sibling_protection(broker, active_trade, "stop_loss")

        self.assertTrue(result["ok"])
        self.assertEqual(broker.cancelled_algo, [("BTCUSDC", 202)])


class FakeBroker:
    def __init__(self):
        self.cancelled_orders = []
        self.cancelled_algo = []

    def cancel_order(self, symbol, order_id):
        self.cancelled_orders.append((symbol, order_id))
        return {"orderId": order_id}

    def cancel_algo_order(self, symbol, algo_id):
        self.cancelled_algo.append((symbol, algo_id))
        return {"algoId": algo_id}


if __name__ == "__main__":
    unittest.main()
