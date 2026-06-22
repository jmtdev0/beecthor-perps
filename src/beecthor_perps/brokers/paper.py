from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from beecthor_perps.models import OrderIntent


class PaperBroker:
    def __init__(self, ledger_path: Path) -> None:
        self.ledger_path = ledger_path

    def status(self) -> dict[str, Any]:
        return {"broker": "paper", "ledger_path": str(self.ledger_path)}

    def place_order_intent(self, intent: OrderIntent, *, require_stop_loss: bool = True) -> dict[str, Any]:
        payload = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "mode": "paper",
            "intent": {
                "symbol": intent.symbol,
                "direction": intent.direction.value,
                "quantity": intent.quantity,
                "notional_usdt": intent.notional_usdt,
                "leverage": intent.leverage,
                "entry_price_reference": intent.entry_price_reference,
                "stop_loss": intent.stop_loss,
                "take_profit": intent.take_profit,
                "reason": intent.reason,
                "source_video_id": intent.source_video_id,
            },
        }
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
        return {"ok": True, "mode": "paper", "ledger_path": str(self.ledger_path)}
