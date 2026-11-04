"""Haftalik liga kalendar hisoblash testlari."""
import unittest
from datetime import datetime, timezone

from core.leaderboard import week_start_utc


class WeeklyLeaderboardTests(unittest.TestCase):
    def test_week_starts_on_monday_utc(self) -> None:
        moment = datetime(2026, 11, 4, 18, 30, tzinfo=timezone.utc)
        self.assertEqual(week_start_utc(moment).isoformat(), "2026-11-02")

    def test_sunday_belongs_to_previous_monday(self) -> None:
        moment = datetime(2026, 11, 8, 23, 59, tzinfo=timezone.utc)
        self.assertEqual(week_start_utc(moment).isoformat(), "2026-11-02")


if __name__ == "__main__":
    unittest.main()
