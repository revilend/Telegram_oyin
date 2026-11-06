"""«Portlovçi Bomba» integratsiyasi: manager, API, bot va Mini App."""

from __future__ import annotations

import asyncio
import os
import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("MINI_APP_URL", "https://revilend.games")
os.environ.setdefault("BOT_USERNAME", "revilend_gamesbot")

from fastapi.testclient import TestClient

from api.server import app
from bot.handlers import bomb_group, games_catalog
from games.bomb.cards import CardType
from games.bomb.engine import BombRoom, BombStatus
from games.bomb.manager import (
    BombManager,
    BombRoomError,
    get_default_manager,
    set_default_manager,
)

CONFIG = SimpleNamespace(bot_username="revilend_gamesbot")


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, object]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.messages.append((chat_id, text, kwargs.get("reply_markup")))


class BombManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = BombManager(seed=17)
        set_default_manager(self.manager)
        self.addCleanup(set_default_manager, None)

    def test_create_join_and_start_flow(self) -> None:
        room = self.manager.create_room(101, "Ali", chat_id=-100777)
        self.assertRegex(room.code, r"^BMB\d{3}$")
        self.assertEqual(room.host_id, 101)
        self.assertEqual(room.chat_id, -100777)

        self.manager.join(room.code, 102, "Vali")
        with self.assertRaises(BombRoomError):
            self.manager.start(room.code, 102)
        self.assertIs(room.status, BombStatus.LOBBY)

        started = self.manager.start(room.code, 101)
        self.assertIs(started.status, BombStatus.PLAYING)
        self.assertEqual(len(started.players[101].hand), 5)
        self.assertEqual(len(started.players[102].hand), 5)
        self.assertEqual(started.deck.count(CardType.BOMB), 1)

    def test_start_needs_two_players(self) -> None:
        room = self.manager.create_room(101, "Ali")
        with self.assertRaises(BombRoomError):
            self.manager.start(room.code, 101)


class BombApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"ALLOW_GUEST_AUTH": "true"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.manager = BombManager(seed=23)
        set_default_manager(self.manager)
        self.addCleanup(set_default_manager, None)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    @staticmethod
    def player(user_id: int, name: str) -> dict[str, object]:
        return {"user_id": user_id, "name": name}

    def _started_room(self) -> tuple[str, BombRoom]:
        created = self.client.post(
            "/api/bomb/create", json=self.player(201, "Ali")
        )
        self.assertEqual(created.status_code, 200, created.text)
        code = created.json()["state"]["code"]
        self.assertRegex(code, r"^BMB\d{3}$")
        joined = self.client.post(
            f"/api/bomb/{code}/join", json=self.player(202, "Vali")
        )
        self.assertEqual(joined.status_code, 200, joined.text)
        rejected = self.client.post(
            f"/api/bomb/{code}/start", json=self.player(202, "Vali")
        )
        self.assertEqual(rejected.status_code, 400, rejected.text)
        started = self.client.post(
            f"/api/bomb/{code}/start", json=self.player(201, "Ali")
        )
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(started.json()["state"]["status"], "PLAYING")
        return code, self.manager.get_room(code)

    def test_state_join_and_host_start(self) -> None:
        code, room = self._started_room()
        state = self.client.get(
            f"/api/bomb/{code}?user_id=202&name=Vali"
        )
        self.assertEqual(state.status_code, 200, state.text)
        payload = state.json()
        self.assertEqual(payload["state"]["code"], code)
        self.assertEqual(len(payload["me"]["hand"]), 5)
        self.assertEqual(payload["state"]["winner_reward"], 30)
        self.assertEqual(len(room.players), 2)

    def test_future_is_visible_only_to_its_owner(self) -> None:
        code, room = self._started_room()
        room.players[201].hand = [CardType.FUTURE]
        room.deck = [
            CardType.DEFUSE,
            CardType.BOMB,
            CardType.SKIP,
            CardType.ATTACK,
        ]

        played = self.client.post(
            f"/api/bomb/{code}/play",
            json={**self.player(201, "Ali"), "card_type": "FUTURE"},
        )
        self.assertEqual(played.status_code, 200, played.text)
        action = played.json()["action"]
        self.assertEqual(
            action["future_cards"], ["DEFUSE", "BOMB", "SKIP"]
        )
        self.assertEqual(
            played.json()["me"]["future_cards"], ["DEFUSE", "BOMB", "SKIP"]
        )

        other = self.client.get(f"/api/bomb/{code}?user_id=202&name=Vali")
        self.assertEqual(other.status_code, 200, other.text)
        self.assertEqual(other.json()["me"]["future_cards"], [])

    def test_only_current_player_can_draw(self) -> None:
        code, _room = self._started_room()
        response = self.client.post(
            f"/api/bomb/{code}/draw", json=self.player(202, "Vali")
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("navbatingiz emas", response.json()["detail"])

    def test_mini_app_and_bomb_assets_are_served(self) -> None:
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Portlovçi Bomba", page.text)
        self.assertIn("bomb-hand-scroll", page.text)
        self.assertIn("assets/images/bomb/bomb.png", page.text)

        image = self.client.get("/assets/images/bomb/attack.png")
        self.assertEqual(image.status_code, 200)
        self.assertTrue(image.headers["content-type"].startswith("image/"))


class BombGroupAnnouncementTest(unittest.TestCase):
    def _room(self) -> BombRoom:
        room = BombRoom("BMB501", rng=random.Random(4), chat_id=-100777)
        room.add_player(301, "Ali")
        room.add_player(302, "Vali")
        room.start()
        return room

    def test_future_action_is_announced_without_revealing_cards(self) -> None:
        room = self._room()
        room.players[301].hand = [CardType.FUTURE]
        room.deck = [
            CardType.BOMB,
            CardType.ATTACK,
            CardType.DEFUSE,
        ]
        result = room.play_action_card(301, CardType.FUTURE)
        bot = FakeBot()

        asyncio.run(bomb_group.announce_action(bot, room, result))

        chat_id, text, _markup = bot.messages[-1]
        self.assertEqual(chat_id, -100777)
        self.assertIn("Ali", text)
        self.assertIn("Kelajak", text)
        self.assertIn("faqat unga", text)
        self.assertNotIn("Portlovçi Bomba", text)

    def test_explosion_announcement_names_eliminated_player(self) -> None:
        room = self._room()
        room.players[301].hand = []
        room.deck = [CardType.BOMB]
        result = room.draw_card(301)
        bot = FakeBot()

        asyncio.run(bomb_group.announce_action(bot, room, result))

        _chat_id, text, _markup = bot.messages[-1]
        self.assertIn("portladi", text)
        self.assertIn("Ali", text)
        self.assertIn("Vali", text)
        self.assertIn("+30", text)

    def test_lobby_has_miniapp_join_and_start_buttons(self) -> None:
        room = BombRoom("BMB502")
        room.add_player(301, "Ali")
        with patch.object(bomb_group, "get_config", return_value=CONFIG):
            markup = bomb_group.lobby_keyboard(room)
        buttons = [row[0] for row in markup.inline_keyboard]
        self.assertIn("startapp=bomb_BMB502", buttons[0].url)
        self.assertTrue(
            buttons[1].callback_data.startswith(bomb_group.JOIN_PREFIX)
        )
        self.assertTrue(
            buttons[2].callback_data.startswith(bomb_group.START_PREFIX)
        )


class BombCatalogTest(unittest.TestCase):
    def test_catalog_lists_bomb_rules_and_button(self) -> None:
        self.assertIn("/bomb", games_catalog.BOMB_TEXT)
        self.assertIn("+30", games_catalog.BOMB_TEXT)
        with patch.object(games_catalog, "get_config", return_value=CONFIG):
            markup = games_catalog.catalog_keyboard()
        callbacks = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
        ]
        self.assertIn(games_catalog.BOMB_CALLBACK, callbacks)


if __name__ == "__main__":
    unittest.main()
