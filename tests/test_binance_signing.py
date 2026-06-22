import unittest
from unittest.mock import patch

from beecthor_perps.brokers.binance_usdm import BinanceUsdMFuturesClient
from beecthor_perps.config import Settings
from beecthor_perps.models import Direction, OrderIntent


class BinanceSigningTests(unittest.TestCase):
    def _client(self, **env):
        settings = Settings.from_env(
            env={
                "PERPS_ENV": "testnet",
                "BROKER": "binance",
                "BINANCE_BASE_URL": "https://demo-fapi.binance.com",
                "BINANCE_API_KEY": "key",
                "BINANCE_API_SECRET": "secret",
                **env,
            }
        )
        return BinanceUsdMFuturesClient(settings)

    def _intent(self, direction=Direction.LONG):
        return OrderIntent(
            symbol="BTCUSDC",
            direction=direction,
            quantity=0.002,
            notional_usdt=128,
            leverage=5,
            entry_price_reference=64000,
            stop_loss=63000 if direction == Direction.LONG else 65000,
            take_profit=66000 if direction == Direction.LONG else 62000,
            reason="test",
        )

    def test_hmac_signature_matches_known_vector(self):
        client = self._client()
        signature = client.sign({"symbol": "BTCUSDT", "side": "BUY", "timestamp": 123456789})
        self.assertEqual(signature, "58c9f32397d2b82d1282029a3c66f58af0d4a4cce97155b640678233e1bc0e67")

    def test_hedge_entry_includes_position_side(self):
        client = self._client(POSITION_MODE="hedge")
        params = client._entry_order_params(self._intent(Direction.LONG))
        self.assertEqual(params["positionSide"], "LONG")
        self.assertEqual(params["side"], "BUY")

    def test_hedge_protective_orders_use_quantity_not_close_position(self):
        client = self._client(POSITION_MODE="hedge")
        intent = self._intent(Direction.SHORT)
        stop = client._stop_algo_params(intent)
        take_profit = client._take_profit_algo_params(intent)

        self.assertEqual(stop["positionSide"], "SHORT")
        self.assertEqual(stop["quantity"], "0.002")
        self.assertNotIn("closePosition", stop)
        self.assertEqual(take_profit["positionSide"], "SHORT")
        self.assertEqual(take_profit["quantity"], "0.002")
        self.assertNotIn("closePosition", take_profit)

    def test_one_way_protective_orders_keep_close_position(self):
        client = self._client(POSITION_MODE="one_way")
        stop = client._stop_algo_params(self._intent(Direction.LONG))
        self.assertEqual(stop["positionSide"], "BOTH")
        self.assertEqual(stop["closePosition"], "true")
        self.assertNotIn("quantity", stop)

    def test_manual_demo_order_can_place_take_profit_without_stop(self):
        client = self._client(POSITION_MODE="one_way")
        original = self._intent(Direction.LONG)
        intent = OrderIntent(**{**original.__dict__, "stop_loss": 0})

        with patch.object(client, "set_leverage", return_value={"leverage": 5}), patch.object(
            client,
            "_request",
            side_effect=[{"orderId": 10}, {"algoId": 20}],
        ) as request:
            result = client.place_order_intent(intent, require_stop_loss=False)

        self.assertIsNone(result["stop"])
        self.assertEqual(result["take_profit"]["algoId"], 20)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[1].kwargs["params"]["type"], "TAKE_PROFIT_MARKET")


if __name__ == "__main__":
    unittest.main()
