import unittest

from beecthor_perps.cli import _one_way_interference_reason
from beecthor_perps.models import Direction


class CliSafetyTests(unittest.TestCase):
    def test_rejects_long_that_would_reduce_one_way_short(self):
        reason = _one_way_interference_reason(Direction.LONG, "BTCUSDC", -0.002)
        self.assertIn("A BUY would reduce or close that short", reason)

    def test_rejects_short_that_would_reduce_one_way_long(self):
        reason = _one_way_interference_reason(Direction.SHORT, "BTCUSDC", 0.002)
        self.assertIn("A SELL would reduce or close that long", reason)

    def test_allows_same_direction_or_flat_one_way(self):
        self.assertEqual(_one_way_interference_reason(Direction.LONG, "BTCUSDC", 0), "")
        self.assertEqual(_one_way_interference_reason(Direction.SHORT, "BTCUSDC", -0.002), "")


if __name__ == "__main__":
    unittest.main()
