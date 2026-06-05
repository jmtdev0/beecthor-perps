import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from beecthor_perps.models import BeecthorThesis
from beecthor_perps.thesis import ThesisError, load_thesis_file, validate_thesis


class ThesisTests(unittest.TestCase):
    def test_loads_valid_latest_thesis(self):
        valid_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        payload = {
            "schema_version": 1,
            "symbol": "BTCUSDT",
            "video_id": "abc123",
            "created_at": "2026-05-31T10:00:00Z",
            "valid_until": valid_until,
            "macro_bias": "bearish",
            "preferred_setup": "wait",
            "confidence": 0.0,
            "long_zones": [],
            "short_zones": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "latest.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            thesis = load_thesis_file(path)

        self.assertEqual(thesis.video_id, "abc123")
        self.assertEqual(thesis.symbol, "BTCUSDT")

    def test_loads_valid_btcusdc_thesis(self):
        valid_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        payload = {
            "schema_version": 1,
            "symbol": "BTCUSDC",
            "video_id": "abc123",
            "created_at": "2026-05-31T10:00:00Z",
            "valid_until": valid_until,
            "macro_bias": "bearish",
            "preferred_setup": "wait",
            "confidence": 0.0,
            "long_zones": [],
            "short_zones": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "latest.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            thesis = load_thesis_file(path)

        self.assertEqual(thesis.symbol, "BTCUSDC")

    def test_rejects_expired_thesis(self):
        payload = {
            "schema_version": 1,
            "symbol": "BTCUSDT",
            "video_id": "abc123",
            "created_at": "2026-05-31T10:00:00Z",
            "valid_until": "2026-05-31T11:00:00Z",
            "macro_bias": "bearish",
            "preferred_setup": "wait",
            "confidence": 0.0,
            "long_zones": [],
            "short_zones": [],
        }
        thesis = BeecthorThesis.from_dict(payload)
        with self.assertRaises(ThesisError):
            validate_thesis(thesis, now=datetime(2026, 5, 31, 12, 0, tzinfo=UTC))


if __name__ == "__main__":
    unittest.main()
