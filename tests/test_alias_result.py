"""Alias yakuniy natijasi: MVP tahlili va Mini App havolasi testlari."""

import base64
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot.config import get_config
from bot.handlers import alias_group
from games.alias.engine import AliasPlayer


class FakeRoom:
    code = "ALI777"
    total_rounds = 6
    stop_reason = "completed"

    def __init__(self) -> None:
        self.players = {
            501: AliasPlayer(user_id=501, name="Ali", username="ali", score=35),
            502: AliasPlayer(user_id=502, name="Vali", username="", score=20),
            503: AliasPlayer(user_id=503, name="Hasan", username="hasan", score=10),
        }

    def leaderboard(self):
        return sorted(
            self.players.values(),
            key=lambda player: (-player.score, player.name.lower()),
        )

    def winners(self):
        return [self.leaderboard()[0]]


class AliasResultTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "BOT_TOKEN": "123456:TEST",
                "ADMIN_ID": "424242",
                "MINI_APP_URL": "https://example.com/app",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        get_config.cache_clear()
        self.addCleanup(get_config.cache_clear)
        self.room = FakeRoom()

    def test_results_text_includes_mvp_and_analysis(self) -> None:
        text = alias_group.results_text(self.room)
        self.assertIn("Öyin MVPsi", text)
        self.assertIn("@ali", text)
        self.assertIn("35 oçko", text)
        self.assertIn("Tahlil", text)
        self.assertIn("Öynalgan raundlar", text)

    def test_results_keyboard_builds_webapp_link(self) -> None:
        keyboard = alias_group.results_keyboard(self.room)
        self.assertIsNotNone(keyboard)
        button = keyboard.inline_keyboard[0][0]
        self.assertIn("Natija va MVP", button.text)
        url = button.web_app.url
        self.assertIn("alias_result=", url)
        token = url.split("alias_result=", 1)[1]
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual(payload["code"], "ALI777")
        self.assertEqual(payload["winners"], [501])
        self.assertEqual(payload["players"][0]["score"], 35)
        self.assertEqual(payload["rounds"], 6)

    def test_results_keyboard_without_mini_app(self) -> None:
        with patch.object(
            alias_group,
            "get_config",
            return_value=SimpleNamespace(mini_app_url=""),
        ):
            self.assertIsNone(alias_group.results_keyboard(self.room))


if __name__ == "__main__":
    unittest.main()
