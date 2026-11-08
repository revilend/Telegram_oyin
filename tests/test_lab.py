"""Virtual bot simulyatori (`/test_game`) testlari."""

import os
import unittest
from unittest.mock import patch

from engine.test_lab import GAMES, format_report, run_game


class VirtualBotLabTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "ALLOW_GUEST_AUTH": "true",
                "SUPABASE_URL": "",
                "SUPABASE_KEY": "",
                "BOT_TOKEN": "",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_every_game_plays_to_the_end_with_bots(self) -> None:
        for game in GAMES:
            with self.subTest(game=game):
                result = run_game(game)
                self.assertEqual(len(result["reports"]), 1)
                report = result["reports"][0]
                self.assertTrue(report["ok"], msg=f"{game}: {report.get('log')}")
                self.assertTrue(report["log"])
                self.assertNotIn("Xato", " ".join(report["log"]))

    def test_bunker_and_mafia_record_stats_for_players(self) -> None:
        for game in ("bunker", "mafia"):
            with self.subTest(game=game):
                report = run_game(game)["reports"][0]
                played = sum(1 for value in report["deltas"].values() if value["games_played"] > 0)
                self.assertGreaterEqual(played, 2)
                self.assertTrue(
                    any(value["wins"] > 0 for value in report["deltas"].values()),
                    msg=f"{game}: g'olib statistikasi yozilmadi",
                )

    def test_unknown_game_returns_helpful_error(self) -> None:
        result = run_game("stoltennis")
        self.assertFalse(result["ok"])
        self.assertIn("Noma'lum", result["error"])

    def test_report_escapes_html(self) -> None:
        text = format_report(
            {"ok": True, "reports": [{"game": "<b>x</b>", "ok": True, "log": ["a & b"], "deltas": {}}]}
        )
        self.assertIn("&lt;", text)
        self.assertIn("a &amp; b", text)
        self.assertNotIn("<b>X</b>", text)
