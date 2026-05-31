import unittest

from beecthor_perps.config import Settings
from beecthor_perps.models import Direction, OrderIntent
from beecthor_perps.safety import SafetyViolation, validate_order_intent


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings.from_env(env={})

    def test_rejects_symbol_outside_allowlist(self):
        intent = OrderIntent(
            symbol="ETHUSDT",
            direction=Direction.SHORT,
            quantity=0.01,
            notional_usdt=25,
            leverage=2,
            entry_price_reference=78000,
            stop_loss=79500,
            take_profit=75500,
            reason="test",
        )
        with self.assertRaises(SafetyViolation):
            validate_order_intent(intent, self.settings)

    def test_rejects_invalid_short_stop_direction(self):
        intent = OrderIntent(
            symbol="BTCUSDT",
            direction=Direction.SHORT,
            quantity=0.01,
            notional_usdt=25,
            leverage=2,
            entry_price_reference=78000,
            stop_loss=77000,
            take_profit=75500,
            reason="test",
        )
        with self.assertRaises(SafetyViolation):
            validate_order_intent(intent, self.settings)


if __name__ == "__main__":
    unittest.main()
