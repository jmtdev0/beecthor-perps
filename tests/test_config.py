import unittest

from beecthor_perps.config import ConfigurationError, Settings


class ConfigTests(unittest.TestCase):
    def test_shadow_defaults_are_safe(self):
        settings = Settings.from_env(env={})
        self.assertEqual(settings.perps_env, "shadow")
        self.assertEqual(settings.broker, "paper")
        self.assertFalse(settings.is_real_money)
        self.assertEqual(settings.strategy.profile, "conservative")
        self.assertEqual(settings.strategy.min_reward_risk, 1.5)
        self.assertEqual(settings.strategy.target_selection, "first")
        self.assertEqual(settings.strategy.confirmation_policy, "two_5m")

    def test_demo_learning_strategy_defaults_are_more_active(self):
        settings = Settings.from_env(env={"STRATEGY_PROFILE": "demo_learning"})
        self.assertEqual(settings.strategy.profile, "demo_learning")
        self.assertEqual(settings.strategy.min_reward_risk, 1.0)
        self.assertEqual(settings.strategy.target_selection, "first_rr_qualified")
        self.assertEqual(settings.strategy.confirmation_policy, "one_5m")

    def test_strategy_overrides_are_supported(self):
        settings = Settings.from_env(
            env={
                "STRATEGY_PROFILE": "demo_learning",
                "MIN_REWARD_RISK": "1.3",
                "TARGET_SELECTION": "first",
                "CONFIRMATION_POLICY": "two_5m",
            }
        )
        self.assertEqual(settings.strategy.min_reward_risk, 1.3)
        self.assertEqual(settings.strategy.target_selection, "first")
        self.assertEqual(settings.strategy.confirmation_policy, "two_5m")

    def test_rejects_invalid_strategy_settings(self):
        invalid_envs = [
            {"STRATEGY_PROFILE": "turbo"},
            {"MIN_REWARD_RISK": "0"},
            {"TARGET_SELECTION": "last"},
            {"CONFIRMATION_POLICY": "tick"},
        ]
        for env in invalid_envs:
            with self.subTest(env=env):
                with self.assertRaises(ConfigurationError):
                    Settings.from_env(env=env)

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

    def test_telegram_notifications_require_credentials_when_enabled(self):
        with self.assertRaises(ConfigurationError):
            Settings.from_env(env={"TELEGRAM_NOTIFICATIONS_ENABLED": "true"})

    def test_telegram_notifications_can_be_enabled(self):
        settings = Settings.from_env(
            env={
                "TELEGRAM_NOTIFICATIONS_ENABLED": "true",
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_CHAT_ID": "chat",
            }
        )
        self.assertTrue(settings.telegram_notifications_enabled)
        self.assertEqual(settings.telegram_bot_token, "token")

    def test_telegram_personal_chat_id_is_preferred(self):
        settings = Settings.from_env(
            env={
                "TELEGRAM_NOTIFICATIONS_ENABLED": "true",
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_CHAT_ID": "group-chat",
                "TELEGRAM_PERSONAL_CHAT_ID": "personal-chat",
            }
        )
        self.assertEqual(settings.telegram_chat_id, "personal-chat")


if __name__ == "__main__":
    unittest.main()
