from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class JsonlLedger:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": utc_now_iso(),
            "event_type": event_type,
            **payload,
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


class ActiveTradeStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


class ActiveTradesStore:
    def __init__(self, path: Path, legacy_path: Path | None = None) -> None:
        self.path = path
        self.legacy_path = legacy_path

    def load_all(self) -> list[dict[str, Any]]:
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return [trade for trade in payload if isinstance(trade, dict)]
            if isinstance(payload, dict):
                trades = payload.get("trades", [])
                if isinstance(trades, list):
                    return [trade for trade in trades if isinstance(trade, dict)]
            return []
        if self.legacy_path and self.legacy_path.exists():
            legacy = json.loads(self.legacy_path.read_text(encoding="utf-8"))
            if isinstance(legacy, dict):
                migrated = dict(legacy)
                migrated.setdefault("status", "open")
                migrated.setdefault("position_side", str(migrated.get("direction") or "").upper() or "BOTH")
                return [migrated]
        return []

    def save_all(self, trades: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"trades": trades}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        if self.legacy_path and self.legacy_path.exists():
            self.legacy_path.unlink()

    def add(self, payload: dict[str, Any]) -> None:
        trades = self.load_all()
        trades.append(payload)
        self.save_all(trades)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
        if self.legacy_path and self.legacy_path.exists():
            self.legacy_path.unlink()
