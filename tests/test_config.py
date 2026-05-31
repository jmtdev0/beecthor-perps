import unittest

from beecthor_perps.config import ConfigurationError, Settings


class ConfigTests(unittest.TestCase):
    def test_shadow_defaults_are_safe(self):
        settings = Settings.from_env(env={})
        self.assertEqual(settings.perps_env, "shadow")
        self.assertEqual(settings.broker, "paper")
        self.assertFalse(settings.is_real_money)

    def test_mainnet_requires_ack_and_subaccount(self):
        with self.assertRaises(ConfigurationError):
            Settings.from_env(
                env={
                    "PERPS_ENV": "mainnet",
                    "BROKER": "binance",
                    "BINANCE_BASE_URL": "https://fapi.binance.com",
                    "BINANCE_API_KEY": "key",
                    "BINANCE_API_SECRET": "secret",
                }
            )

    def test_testnet_requires_official_demo_endpoint(self):
        with self.assertRaises(ConfigurationError):
            Settings.from_env(
                env={
                    "PERPS_ENV": "testnet",
                    "BROKER": "binance",
                    "BINANCE_BASE_URL": "https://fapi.binance.com",
                }
            )

    def test_beecthor_testnet_key_aliases_are_supported(self):
        settings = Settings.from_env(
            env={
                "PERPS_ENV": "testnet",
                "BROKER": "binance",
                "BINANCE_BASE_URL": "https://demo-fapi.binance.com",
                "BINANCE_BEECTHOR_PERPS_TESTNET_API_KEY": "alias-key",
                "BINANCE_BEECTHOR_PERPS_TESTNET_API_SECRET": "alias-secret",
            }
        )
        self.assertEqual(settings.binance_api_key, "alias-key")
        self.assertEqual(settings.binance_api_secret, "alias-secret")


if __name__ == "__main__":
    unittest.main()
