from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .models import BeecthorThesis


class ThesisError(ValueError):
    """Raised when the Beecthor perps thesis cannot be used safely."""


def _parse_utc(value: str) -> datetime:
    if not value:
        raise ThesisError("Thesis valid_until is missing")
    raw = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ThesisError(f"Thesis datetime is invalid: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_thesis_file(path: Path) -> BeecthorThesis:
    if not path.exists():
        raise ThesisError(f"Thesis file does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ThesisError("Thesis file must contain a JSON object")
    thesis = BeecthorThesis.from_dict(payload)
    validate_thesis(thesis)
    return thesis


def validate_thesis(thesis: BeecthorThesis, now: datetime | None = None) -> None:
    if thesis.schema_version != 1:
        raise ThesisError(f"Unsupported thesis schema_version: {thesis.schema_version}")
    if thesis.symbol != "BTCUSDT":
        raise ThesisError(f"Unsupported thesis symbol: {thesis.symbol}")
    if not thesis.video_id:
        raise ThesisError("Thesis video_id is missing")
    if thesis.confidence < 0 or thesis.confidence > 1:
        raise ThesisError("Thesis confidence must be between 0 and 1")

    current_time = now.astimezone(UTC) if now else datetime.now(UTC)
    valid_until = _parse_utc(thesis.valid_until)
    if valid_until <= current_time:
        raise ThesisError("Thesis is expired")

    for zone in [*thesis.long_zones, *thesis.short_zones]:
        if zone.low >= zone.high:
            raise ThesisError(f"Invalid zone range: {zone}")
        if zone.stop_loss <= 0:
            raise ThesisError("Zone stop_loss must be positive")
        if not zone.targets:
            raise ThesisError("Zone targets are required")
