import unittest

from beecthor_perps.config import Settings
from beecthor_perps.models import BeecthorThesis, DecisionAction, MarketSnapshot
from beecthor_perps.strategy import evaluate_thesis


class StrategyTests(unittest.TestCase):
    def test_short_resistance_triggers_inside_zone(self):
        settings = Settings.from_env(env={})
        thesis = BeecthorThesis.from_dict(
            {
                "video_id": "test-video",
                "macro_bias": "bearish",
                "preferred_setup": "short_resistance",
                "confidence": 0.7,
                "short_zones": [
                    {"low": 78000, "high": 78500, "stop_loss": 79500, "targets": [75500, 73000]}
                ],
            }
        )
        decision = evaluate_thesis(thesis, MarketSnapshot.now("BTCUSDT", 78200), settings)
        self.assertEqual(decision.action, DecisionAction.TRADE)
        self.assertIsNotNone(decision.intent)
        self.assertEqual(decision.intent.direction.value, "short")

    def test_short_resistance_waits_outside_zone(self):
        settings = Settings.from_env(env={})
        thesis = BeecthorThesis.from_dict(
            {
                "video_id": "test-video",
                "macro_bias": "bearish",
                "preferred_setup": "short_resistance",
                "confidence": 0.7,
                "short_zones": [
                    {"low": 78000, "high": 78500, "stop_loss": 79500, "targets": [75500, 73000]}
                ],
            }
        )
        decision = evaluate_thesis(thesis, MarketSnapshot.now("BTCUSDT", 77000), settings)
        self.assertEqual(decision.action, DecisionAction.WAIT)


if __name__ == "__main__":
    unittest.main()
