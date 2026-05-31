from __future__ import annotations

from typing import Any, Protocol

from beecthor_perps.models import OrderIntent


class Broker(Protocol):
    def status(self) -> dict[str, Any]:
        """Return a sanitized account/broker status."""

    def place_order_intent(self, intent: OrderIntent) -> dict[str, Any]:
        """Place or record an already-validated order intent."""
