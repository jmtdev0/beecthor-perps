import tempfile
import unittest
from pathlib import Path

from beecthor_perps.config import Settings
from beecthor_perps.engine import _classify_close
from beecthor_perps.notifications import NotificationLedger, TelegramNotifier


class NotificationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
