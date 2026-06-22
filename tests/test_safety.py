import unittest

from beecthor_perps.config import Settings
from beecthor_perps.models import Direction, OrderIntent
from beecthor_perps.safety import SafetyViolation, validate_active_trade_limits, validate_order_intent


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

    def test_accepts_btcusdt_in_default_allowlist(self):
        intent = OrderIntent(
            symbol="BTCUSDT",
            direction=Direction.SHORT,
            quantity=0.002,
            notional_usdt=130,
            leverage=2,
            entry_price_reference=65000,
            stop_loss=66000,
            take_profit=63000,
            reason="test",
        )

        validate_order_intent(intent, self.settings)

    def test_rejects_invalid_short_stop_direction(self):
        intent = OrderIntent(
            symbol="BTCUSDC",
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

    def test_rejects_total_open_position_limit(self):
        intent = OrderIntent(
            symbol="BTCUSDC",
            direction=Direction.LONG,
            quantity=0.001,
            notional_usdt=100,
            leverage=2,
            entry_price_reference=64000,
            stop_loss=63000,
            take_profit=66000,
            reason="test",
        )
        active = [
            {"direction": "long", "notional_usdc": 100, "status": "open"},
            {"direction": "short", "notional_usdc": 100, "status": "open"},
            {"direction": "short", "notional_usdc": 50, "status": "open"},
        ]
        with self.assertRaises(SafetyViolation):
            validate_active_trade_limits(intent, self.settings, active)

    def test_rejects_open_position_limit_per_side(self):
        intent = OrderIntent(
            symbol="BTCUSDC",
            direction=Direction.SHORT,
            quantity=0.001,
            notional_usdt=50,
            leverage=2,
            entry_price_reference=64000,
            stop_loss=65000,
            take_profit=62000,
            reason="test",
        )
        active = [
            {"direction": "short", "notional_usdc": 50, "status": "open"},
            {"direction": "short", "notional_usdc": 50, "status": "open"},
        ]
        with self.assertRaises(SafetyViolation):
            validate_active_trade_limits(intent, self.settings, active)

    def test_rejects_total_notional_limit(self):
        intent = OrderIntent(
            symbol="BTCUSDC",
            direction=Direction.LONG,
            quantity=0.001,
            notional_usdt=101,
            leverage=2,
            entry_price_reference=64000,
            stop_loss=63000,
            take_profit=66000,
            reason="test",
        )
        active = [
            {"direction": "long", "notional_usdc": 100, "status": "open"},
            {"direction": "short", "notional_usdc": 100, "status": "open"},
        ]
        with self.assertRaises(SafetyViolation):
            validate_active_trade_limits(intent, self.settings, active)


if __name__ == "__main__":
    unittest.main()
