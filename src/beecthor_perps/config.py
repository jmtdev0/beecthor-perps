from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


MAINNET_BASE_URL = "https://fapi.binance.com"
TESTNET_BASE_URL = "https://demo-fapi.binance.com"


class ConfigurationError(ValueError):
    """Raised when runtime configuration is unsafe or incomplete."""


def _bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _float(value: str | None, default: float) -> float:
    if value in (None, ""):
        return default
    return float(value)


def _int(value: str | None, default: int) -> int:
    if value in (None, ""):
        return default
    return int(value)


def _csv(value: str | None, default: set[str]) -> set[str]:
    if not value:
        return set(default)
    return {item.strip().upper() for item in value.split(",") if item.strip()}


def _first_present(values: Mapping[str, str], *keys: str) -> str:
    for key in keys:
        value = values.get(key, "").strip()
        if value:
            return value
    return ""


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class SafetyLimits:
    symbol_allowlist: set[str]
    default_notional_usdt: float
    max_notional_usdt: float
    max_leverage: int
    daily_loss_limit_usdt: float
    max_open_positions: int
    market_data_max_age_seconds: int


@dataclass(frozen=True)
class StrategySettings:
    profile: str
    min_reward_risk: float
    target_selection: str
    confirmation_policy: str

    def sanitized(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "min_reward_risk": self.min_reward_risk,
            "target_selection": self.target_selection,
            "confirmation_policy": self.confirmation_policy,
        }


@dataclass(frozen=True)
class Settings:
    perps_env: str
    broker: str
    beecthor_thesis_file: str
    binance_base_url: str
    binance_api_key: str
    binance_api_secret: str
    account_role: str
    confirmed_subaccount_id: str
    real_money_ack: bool
    telegram_notifications_enabled: bool
    telegram_bot_token: str
    telegram_chat_id: str
    safety: SafetyLimits
    strategy: StrategySettings

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        env_file: Path | None = None,
    ) -> "Settings":
        merged: dict[str, str] = {}
        if env_file is not None:
            merged.update(load_env_file(env_file))
        merged.update(dict(os.environ if env is None else env))

        perps_env = merged.get("PERPS_ENV", "shadow").strip().lower()
        default_base_url = TESTNET_BASE_URL if perps_env in {"shadow", "testnet"} else MAINNET_BASE_URL
        strategy_profile = merged.get("STRATEGY_PROFILE", "conservative").strip().lower()
        strategy_defaults = {
            "conservative": {
                "min_reward_risk": 1.5,
                "target_selection": "first",
                "confirmation_policy": "two_5m",
            },
            "demo_learning": {
                "min_reward_risk": 1.0,
                "target_selection": "first_rr_qualified",
                "confirmation_policy": "one_5m",
            },
        }
        profile_defaults = strategy_defaults.get(strategy_profile, strategy_defaults["conservative"])
        default_notional = _first_present(merged, "DEFAULT_NOTIONAL_USDC", "DEFAULT_NOTIONAL_USDT")
        max_notional = _first_present(merged, "MAX_NOTIONAL_USDC", "MAX_NOTIONAL_USDT")
        daily_loss_limit = _first_present(merged, "DAILY_LOSS_LIMIT_USDC", "DAILY_LOSS_LIMIT_USDT")
        safety = SafetyLimits(
            symbol_allowlist=_csv(merged.get("SYMBOL_ALLOWLIST"), {"BTCUSDC"}),
            default_notional_usdt=_float(default_notional, 100.0),
            max_notional_usdt=_float(max_notional, 150.0),
            max_leverage=_int(merged.get("MAX_LEVERAGE"), 5),
            daily_loss_limit_usdt=_float(daily_loss_limit, 25.0),
            max_open_positions=_int(merged.get("MAX_OPEN_POSITIONS"), 1),
            market_data_max_age_seconds=_int(merged.get("MARKET_DATA_MAX_AGE_SECONDS"), 20),
        )
        strategy = StrategySettings(
            profile=strategy_profile,
            min_reward_risk=_float(
                merged.get("MIN_REWARD_RISK"),
                float(profile_defaults["min_reward_risk"]),
            ),
            target_selection=merged.get(
                "TARGET_SELECTION",
                str(profile_defaults["target_selection"]),
            )
            .strip()
            .lower(),
            confirmation_policy=merged.get(
                "CONFIRMATION_POLICY",
                str(profile_defaults["confirmation_policy"]),
            )
            .strip()
            .lower(),
        )
        settings = cls(
            perps_env=perps_env,
            broker=merged.get("BROKER", "paper").strip().lower(),
            beecthor_thesis_file=merged.get("BEECTHOR_THESIS_FILE", "").strip(),
            binance_base_url=merged.get("BINANCE_BASE_URL", default_base_url).strip().rstrip("/"),
            binance_api_key=_first_present(
                merged,
                "BINANCE_API_KEY",
                "BINANCE_BEECTHOR_PERPS_TESTNET_API_KEY",
            ),
            binance_api_secret=_first_present(
                merged,
                "BINANCE_API_SECRET",
                "BINANCE_BEECTHOR_PERPS_TESTNET_API_SECRET",
            ),
            account_role=merged.get("ACCOUNT_ROLE", "testnet").strip().lower(),
            confirmed_subaccount_id=merged.get("BINANCE_CONFIRMED_SUBACCOUNT_ID", "").strip(),
            real_money_ack=_bool(merged.get("I_UNDERSTAND_THIS_IS_REAL_MONEY"), False),
            telegram_notifications_enabled=_bool(merged.get("TELEGRAM_NOTIFICATIONS_ENABLED"), False),
            telegram_bot_token=merged.get("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=_first_present(
                merged,
                "TELEGRAM_PERSONAL_CHAT_ID",
                "TELEGRAM_CHAT_ID",
            ),
            safety=safety,
            strategy=strategy,
        )
        settings.validate_startup()
        return settings

    @property
    def is_real_money(self) -> bool:
        return self.perps_env == "mainnet"

    def validate_startup(self) -> None:
        if self.perps_env not in {"shadow", "testnet", "mainnet"}:
            raise ConfigurationError("PERPS_ENV must be one of: shadow, testnet, mainnet")
        if self.broker not in {"paper", "binance"}:
            raise ConfigurationError("BROKER must be one of: paper, binance")
        if not self.safety.symbol_allowlist:
            raise ConfigurationError("SYMBOL_ALLOWLIST cannot be empty")
        if self.safety.default_notional_usdt <= 0:
            raise ConfigurationError("DEFAULT_NOTIONAL_USDC/USDT must be positive")
        if self.safety.max_notional_usdt <= 0:
            raise ConfigurationError("MAX_NOTIONAL_USDC/USDT must be positive")
        if self.safety.default_notional_usdt > self.safety.max_notional_usdt:
            raise ConfigurationError("DEFAULT_NOTIONAL_USDC/USDT cannot exceed MAX_NOTIONAL_USDC/USDT")
        if self.safety.max_leverage < 1:
            raise ConfigurationError("MAX_LEVERAGE must be >= 1")
        if self.strategy.profile not in {"conservative", "demo_learning"}:
            raise ConfigurationError("STRATEGY_PROFILE must be one of: conservative, demo_learning")
        if self.strategy.min_reward_risk <= 0:
            raise ConfigurationError("MIN_REWARD_RISK must be positive")
        if self.strategy.target_selection not in {"first", "first_rr_qualified"}:
            raise ConfigurationError("TARGET_SELECTION must be one of: first, first_rr_qualified")
        if self.strategy.confirmation_policy not in {"two_5m", "one_5m"}:
            raise ConfigurationError("CONFIRMATION_POLICY must be one of: two_5m, one_5m")
        if self.telegram_notifications_enabled and (not self.telegram_bot_token or not self.telegram_chat_id):
            raise ConfigurationError(
                "Telegram notifications require TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
            )

        if self.perps_env == "testnet" and self.binance_base_url != TESTNET_BASE_URL:
            raise ConfigurationError(f"Testnet must use {TESTNET_BASE_URL}")

        if self.perps_env == "mainnet":
            if self.binance_base_url != MAINNET_BASE_URL:
                raise ConfigurationError(f"Mainnet must use {MAINNET_BASE_URL}")
            if self.account_role != "subaccount":
                raise ConfigurationError("Mainnet requires ACCOUNT_ROLE=subaccount")
            if not self.confirmed_subaccount_id:
                raise ConfigurationError("Mainnet requires BINANCE_CONFIRMED_SUBACCOUNT_ID")
            if not self.real_money_ack:
                raise ConfigurationError("Mainnet requires I_UNDERSTAND_THIS_IS_REAL_MONEY=true")
            if not self.binance_api_key or not self.binance_api_secret:
                raise ConfigurationError("Mainnet requires Binance API credentials")

    def sanitized(self) -> dict[str, object]:
        return {
            "perps_env": self.perps_env,
            "broker": self.broker,
            "beecthor_thesis_file": self.beecthor_thesis_file,
            "binance_base_url": self.binance_base_url,
            "has_binance_api_key": bool(self.binance_api_key),
            "has_binance_api_secret": bool(self.binance_api_secret),
            "account_role": self.account_role,
            "confirmed_subaccount_id": bool(self.confirmed_subaccount_id),
            "real_money_ack": self.real_money_ack,
            "telegram_notifications_enabled": self.telegram_notifications_enabled,
            "has_telegram_bot_token": bool(self.telegram_bot_token),
            "has_telegram_chat_id": bool(self.telegram_chat_id),
            "safety": {
                "symbol_allowlist": sorted(self.safety.symbol_allowlist),
                "default_notional_usdt": self.safety.default_notional_usdt,
                "max_notional_usdt": self.safety.max_notional_usdt,
                "max_leverage": self.safety.max_leverage,
                "daily_loss_limit_usdt": self.safety.daily_loss_limit_usdt,
                "max_open_positions": self.safety.max_open_positions,
                "market_data_max_age_seconds": self.safety.market_data_max_age_seconds,
            },
            "strategy": self.strategy.sanitized(),
        }
