from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

from beecthor_perps.config import Settings
from beecthor_perps.models import OrderIntent
from beecthor_perps.safety import validate_order_intent


class BinanceUsdMFuturesClient:
    """Small USD-M Futures REST client with no wallet or transfer endpoints."""

    def __init__(self, settings: Settings, timeout_seconds: int = 10) -> None:
        if settings.broker != "binance":
            raise ValueError("BinanceUsdMFuturesClient requires BROKER=binance")
        self.settings = settings
        self.base_url = settings.binance_base_url.rstrip("/")
        self.api_key = settings.binance_api_key
        self.api_secret = settings.binance_api_secret
        self.timeout_seconds = timeout_seconds

    def status(self) -> dict[str, Any]:
        return {
            "broker": "binance_usdm",
            "perps_env": self.settings.perps_env,
            "base_url": self.base_url,
            "has_api_key": bool(self.api_key),
            "has_api_secret": bool(self.api_secret),
        }

    def sign(self, params: dict[str, Any]) -> str:
        query = urlencode(params, doseq=True)
        return hmac.new(self.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        signed: bool = False,
    ) -> Any:
        import requests

        payload = dict(params or {})
        headers = {}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key
        if signed:
            payload.setdefault("timestamp", int(time.time() * 1000))
            payload.setdefault("recvWindow", 5000)
            payload["signature"] = self.sign(payload)
        response = requests.request(
            method,
            f"{self.base_url}{path}",
            params=payload if method.upper() == "GET" else None,
            data=payload if method.upper() != "GET" else None,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        if not response.text:
            return {}
        return response.json()

    def ping(self) -> Any:
        return self._request("GET", "/fapi/v1/ping")

    def server_time(self) -> Any:
        return self._request("GET", "/fapi/v1/time")

    def account(self) -> Any:
        return self._request("GET", "/fapi/v2/account", signed=True)

    def new_test_order(self, intent: OrderIntent) -> Any:
        validate_order_intent(intent, self.settings)
        return self._request("POST", "/fapi/v1/order/test", params=self._entry_order_params(intent), signed=True)

    def place_order_intent(self, intent: OrderIntent) -> dict[str, Any]:
        validate_order_intent(intent, self.settings)
        if self.settings.perps_env == "mainnet":
            raise RuntimeError("Mainnet order placement is intentionally not enabled in the first scaffold")

        entry = self._request("POST", "/fapi/v1/order", params=self._entry_order_params(intent), signed=True)
        stop = self._request("POST", "/fapi/v1/order", params=self._stop_order_params(intent), signed=True)
        take_profit = self._request("POST", "/fapi/v1/order", params=self._take_profit_order_params(intent), signed=True)
        return {"ok": True, "entry": entry, "stop": stop, "take_profit": take_profit}

    def _entry_order_params(self, intent: OrderIntent) -> dict[str, Any]:
        return {
            "symbol": intent.symbol,
            "side": intent.entry_side,
            "type": "MARKET",
            "quantity": self._format_quantity(intent.quantity),
        }

    def _stop_order_params(self, intent: OrderIntent) -> dict[str, Any]:
        return {
            "symbol": intent.symbol,
            "side": intent.exit_side,
            "type": "STOP_MARKET",
            "stopPrice": self._format_price(intent.stop_loss),
            "closePosition": "true",
            "workingType": "MARK_PRICE",
        }

    def _take_profit_order_params(self, intent: OrderIntent) -> dict[str, Any]:
        return {
            "symbol": intent.symbol,
            "side": intent.exit_side,
            "type": "TAKE_PROFIT_MARKET",
            "stopPrice": self._format_price(intent.take_profit),
            "closePosition": "true",
            "workingType": "MARK_PRICE",
        }

    @staticmethod
    def _format_quantity(value: float) -> str:
        return f"{value:.6f}".rstrip("0").rstrip(".")

    @staticmethod
    def _format_price(value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")
