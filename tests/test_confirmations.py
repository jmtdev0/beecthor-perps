import unittest
from datetime import UTC, datetime, timedelta

from beecthor_perps.config import Settings
from beecthor_perps.models import BeecthorThesis, Candle, MarketSnapshot, PriceZone
from beecthor_perps.strategy import evaluate_confirmed_thesis


def candle(minutes: int, high: float, low: float, close: float) -> Candle:
    base = datetime(2026, 5, 31, 10, 0, tzinfo=UTC)
    open_time = base + timedelta(minutes=minutes)
    return Candle(
        symbol="BTCUSDC",
        interval="5m",
        open_time=open_time,
        open=close,
        high=high,
        low=low,
        close=close,
        close_time=open_time + timedelta(minutes=5),
        closed=True,
    )


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings.from_env(env={})
        self.demo_learning_settings = Settings.from_env(env={"STRATEGY_PROFILE": "demo_learning"})

    def test_detects_clear_long_reclaim(self):
        thesis = BeecthorThesis(
            video_id="abc123",
            created_at="2026-05-31T10:00:00Z",
            macro_bias="bearish",
            preferred_setup="long_support_sweep_reclaim",
            valid_until="2026-06-01T10:00:00Z",
            confidence=0.8,
            long_zones=[PriceZone(low=73000, high=73500, stop_loss=72500, targets=[76000], label="support")],
        )
        candles = [
            candle(0, high=73600, low=72950, close=73300),
            candle(5, high=73700, low=73100, close=73620),
            candle(10, high=73800, low=73510, close=73700),
        ]

        decision = evaluate_confirmed_thesis(
            thesis,
            MarketSnapshot.now("BTCUSDC", 73700),
            candles,
            self.settings,
        )

        self.assertEqual(decision.action.value, "trade")
        self.assertEqual(decision.intent.direction.value, "long")

    def test_rejects_ambiguous_long_reclaim(self):
        thesis = BeecthorThesis(
            video_id="abc123",
            created_at="2026-05-31T10:00:00Z",
            macro_bias="bearish",
            preferred_setup="long_support_sweep_reclaim",
            valid_until="2026-06-01T10:00:00Z",
            confidence=0.8,
            long_zones=[PriceZone(low=73000, high=73500, stop_loss=72500, targets=[76000], label="support")],
        )
        candles = [
            candle(0, high=73600, low=72950, close=73300),
            candle(5, high=73600, low=73100, close=73480),
            candle(10, high=73800, low=73510, close=73700),
        ]

        decision = evaluate_confirmed_thesis(
            thesis,
            MarketSnapshot.now("BTCUSDC", 73700),
            candles,
            self.settings,
        )

        self.assertEqual(decision.action.value, "wait")

    def test_detects_clear_short_rejection(self):
        thesis = BeecthorThesis(
            video_id="abc123",
            created_at="2026-05-31T10:00:00Z",
            macro_bias="bearish",
            preferred_setup="short_resistance_bearish_regime",
            valid_until="2026-06-01T10:00:00Z",
            confidence=0.8,
            short_zones=[PriceZone(low=78000, high=79000, stop_loss=80000, targets=[73000], label="resistance")],
        )
        candles = [
            candle(0, high=78500, low=77900, close=78100),
            candle(5, high=79100, low=77700, close=77900),
            candle(10, high=77950, low=77500, close=77700),
        ]

        decision = evaluate_confirmed_thesis(
            thesis,
            MarketSnapshot.now("BTCUSDC", 77700),
            candles,
            self.settings,
        )

        self.assertEqual(decision.action.value, "trade")
        self.assertEqual(decision.intent.direction.value, "short")

    def test_conservative_requires_two_5m_candles(self):
        thesis = BeecthorThesis(
            video_id="abc123",
            created_at="2026-05-31T10:00:00Z",
            macro_bias="bearish",
            preferred_setup="long_support_sweep_reclaim",
            valid_until="2026-06-01T10:00:00Z",
            confidence=0.8,
            long_zones=[PriceZone(low=72700, high=73500, stop_loss=72000, targets=[75000, 78200], label="support")],
        )
        candles = [candle(0, high=73600, low=72950, close=73520)]

        decision = evaluate_confirmed_thesis(
            thesis,
            MarketSnapshot.now("BTCUSDC", 73520),
            candles,
            self.settings,
        )

        self.assertEqual(decision.action.value, "wait")

    def test_demo_learning_long_uses_first_target_that_meets_rr(self):
        thesis = BeecthorThesis(
            video_id="abc123",
            created_at="2026-05-31T10:00:00Z",
            macro_bias="bearish",
            preferred_setup="long_support_sweep_reclaim",
            valid_until="2026-06-01T10:00:00Z",
            confidence=0.8,
            long_zones=[PriceZone(low=72700, high=73500, stop_loss=72000, targets=[75000, 78200], label="support")],
        )
        candles = [candle(0, high=73600, low=72950, close=73520)]

        decision = evaluate_confirmed_thesis(
            thesis,
            MarketSnapshot.now("BTCUSDC", 73520),
            candles,
            self.demo_learning_settings,
        )

        self.assertEqual(decision.action.value, "trade")
        self.assertEqual(decision.intent.direction.value, "long")
        self.assertEqual(decision.intent.take_profit, 78200)

    def test_demo_learning_short_uses_first_target_that_meets_rr(self):
        thesis = BeecthorThesis(
            video_id="abc123",
            created_at="2026-05-31T10:00:00Z",
            macro_bias="bearish",
            preferred_setup="short_resistance_bearish_regime",
            valid_until="2026-06-01T10:00:00Z",
            confidence=0.8,
            short_zones=[PriceZone(low=72000, high=74000, stop_loss=76500, targets=[68000, 65000], label="resistance")],
        )
        candles = [candle(0, high=72500, low=70900, close=71000)]

        decision = evaluate_confirmed_thesis(
            thesis,
            MarketSnapshot.now("BTCUSDC", 71000),
            candles,
            self.demo_learning_settings,
        )

        self.assertEqual(decision.action.value, "trade")
        self.assertEqual(decision.intent.direction.value, "short")
        self.assertEqual(decision.intent.take_profit, 65000)

    def test_demo_learning_rejects_when_no_target_meets_rr(self):
        thesis = BeecthorThesis(
            video_id="abc123",
            created_at="2026-05-31T10:00:00Z",
            macro_bias="bearish",
            preferred_setup="short_resistance_bearish_regime",
            valid_until="2026-06-01T10:00:00Z",
            confidence=0.8,
            short_zones=[PriceZone(low=72000, high=74000, stop_loss=76500, targets=[68000], label="resistance")],
        )
        candles = [candle(0, high=72500, low=70900, close=71000)]

        decision = evaluate_confirmed_thesis(
            thesis,
            MarketSnapshot.now("BTCUSDC", 71000),
            candles,
            self.demo_learning_settings,
        )

        self.assertEqual(decision.action.value, "reject")
        self.assertEqual(decision.reason, "No take-profit target reaches 1.0R")


if __name__ == "__main__":
    unittest.main()
