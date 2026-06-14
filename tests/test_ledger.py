import json
import tempfile
import unittest
from pathlib import Path

from beecthor_perps.ledger import ActiveTradesStore


class ActiveTradesStoreTests(unittest.TestCase):
    def test_loads_legacy_single_active_trade(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy = root / "active_trade.json"
            current = root / "active_trades.json"
            legacy.write_text(
                json.dumps(
                    {
                        "trade_id": "legacy",
                        "symbol": "BTCUSDC",
                        "direction": "short",
                        "quantity": 0.002,
                    }
                ),
                encoding="utf-8",
            )

            trades = ActiveTradesStore(current, legacy).load_all()

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["trade_id"], "legacy")
        self.assertEqual(trades[0]["status"], "open")
        self.assertEqual(trades[0]["position_side"], "SHORT")

    def test_add_writes_new_multi_trade_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = ActiveTradesStore(root / "active_trades.json", root / "active_trade.json")
            store.add({"trade_id": "one", "direction": "long"})
            store.add({"trade_id": "two", "direction": "short"})

            payload = json.loads((root / "active_trades.json").read_text(encoding="utf-8"))

        self.assertEqual([trade["trade_id"] for trade in payload["trades"]], ["one", "two"])


if __name__ == "__main__":
    unittest.main()
