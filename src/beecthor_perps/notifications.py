from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import requests

from .config import Settings
from .models import OrderIntent


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class NotificationLedger:
    """Small JSONL ledger used to avoid duplicate Telegram notifications."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def seen(self, event_id: str) -> bool:
        if not self.path.exists():
            return False
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("event_id") == event_id:
                    return True
        return False

    def record(self, event_id: str, message: str, result: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": _utc_now(),
            "event_id": event_id,
            "message": message,
            "result": result,
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class TelegramNotifier:
    settings: Settings
    ledger: NotificationLedger
    sender: Callable[[str, dict[str, Any]], Any] | None = None

    def send_once(self, event_id: str, message: str) -> dict[str, Any]:
        if self.ledger.seen(event_id):
            return {"ok": True, "skipped": True, "reason": "duplicate_event"}
        if not self.settings.telegram_notifications_enabled:
            return {"ok": True, "skipped": True, "reason": "telegram_disabled"}

        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.settings.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            if self.sender is None:
                response = requests.post(url, json=payload, timeout=20)
                response.raise_for_status()
                result = {"ok": True, "status_code": response.status_code}
            else:
                self.sender(url, payload)
                result = {"ok": True, "status_code": "fake"}
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self.ledger.record(event_id, message, result)
        return result


def format_open_position_message(intent: OrderIntent, settings: Settings, setup: str) -> str:
    return "\n".join(
        [
            "🟢 <b>Beecthor Perps: posición abierta</b>",
            f"Entorno: <b>{settings.perps_env}</b>",
            f"Símbolo: <b>{intent.symbol}</b>",
            f"Dirección: <b>{intent.direction.value.upper()}</b>",
            f"Cantidad: <b>{intent.quantity:g}</b>",
            f"Notional aprox.: <b>{intent.notional_usdt:.2f} USDT</b>",
            f"Leverage: <b>{intent.leverage}x</b>",
            f"Entrada ref.: <b>{intent.entry_price_reference:.2f}</b>",
            f"Stop: <b>{intent.stop_loss:.2f}</b>",
            f"Take-profit: <b>{intent.take_profit:.2f}</b>",
            f"Setup: <b>{setup}</b>",
            f"Vídeo: <b>{intent.source_video_id or 'unknown'}</b>",
        ]
    )


def format_close_position_message(classification: str, symbol: str, source_video_id: str) -> str:
    title = {
        "take_profit": "✅ <b>Beecthor Perps: take-profit completado</b>",
        "stop_loss": "🔴 <b>Beecthor Perps: stop-loss / take-loss ejecutado</b>",
    }.get(classification, "⚪ <b>Beecthor Perps: posición cerrada sin clasificar</b>")
    return "\n".join(
        [
            title,
            f"Símbolo: <b>{symbol}</b>",
            f"Vídeo: <b>{source_video_id or 'unknown'}</b>",
        ]
    )


def format_critical_protection_message(intent: OrderIntent, detail: dict[str, Any]) -> str:
    return "\n".join(
        [
            "🚨 <b>Beecthor Perps: error crítico de protección</b>",
            f"Símbolo: <b>{intent.symbol}</b>",
            f"Dirección: <b>{intent.direction.value.upper()}</b>",
            "La entrada pudo haberse creado, pero SL/TP no quedaron completos.",
            "El bot intentó cierre de emergencia y cancelación de órdenes abiertas.",
            f"Detalle seguro: <code>{json.dumps(detail, ensure_ascii=False)}</code>",
        ]
    )
