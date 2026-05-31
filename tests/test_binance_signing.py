import unittest

from beecthor_perps.brokers.binance_usdm import BinanceUsdMFuturesClient
from beecthor_perps.config import Settings


class BinanceSigningTests(unittest.TestCase):
    def test_hmac_signature_matches_known_vector(self):
        settings = Settings.from_env(
            env={
                "PERPS_ENV": "testnet",
                "BROKER": "binance",
                "BINANCE_BASE_URL": "https://demo-fapi.binance.com",
                "BINANCE_API_KEY": "key",
                "BINANCE_API_SECRET": "secret",
            }
        )
        client = BinanceUsdMFuturesClient(settings)
        signature = client.sign({"symbol": "BTCUSDT", "side": "BUY", "timestamp": 123456789})
        self.assertEqual(signature, "58c9f32397d2b82d1282029a3c66f58af0d4a4cce97155b640678233e1bc0e67")


if __name__ == "__main__":
    unittest.main()
