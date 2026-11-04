"""Guruhdagi /spy, /josus lobby va e'lonlari testlari."""

from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("MINI_APP_URL", "https://revilend.games")
os.environ.setdefault("BOT_USERNAME", "revilend_gamesbot")

from bot.handlers import spy_group
from games.spyfall.locations import LOCATIONS
from games.spyfall.manager import SpyfallManager, get_default_manager

CONFIG = SimpleNamespace(bot_username="revilend_gamesbot")


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, object]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.messages.append((chat_id, text, kwargs.get("reply_markup")))


class FakeMessage:
    def __init__(
        self,
        user_id: int = 701,
        name: str = "Ali Valiyev",
        chat_id: int = -100777,
        chat_type: str = "group",
    ) -> None:
        self.from_user = SimpleNamespace(id=user_id, full_name=name)
        self.chat = SimpleNamespace(id=chat_id, type=chat_type)
        self.bot = FakeBot()
        self.answers: list[tuple[str, object]] = []
        self.replies: list[str] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append((text, kwargs.get("reply_markup")))

    async def reply(self, text: str, **kwargs) -> None:
        self.replies.append(text)


class FakeCallback:
    def __init__(self, data: str, user_id: int = 701, name: str = "Ali") -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id, full_name=name)
        self.message = SimpleNamespace(chat=SimpleNamespace(id=-100777, type="group"))
        self.bot = FakeBot()
        self.answered: list[str] = []

    async def answer(self, text: str = "", **_kwargs) -> None:
        self.answered.append(text)


class SpyGroupLobbyTest(unittest.TestCase):
    def setUp(self) -> None:
        get_default_manager().clear()
        self.addCleanup(get_default_manager().clear)
        self.patcher = patch.object(spy_group, "get_config", return_value=CONFIG)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_spy_command_opens_lobby(self) -> None:
        message = FakeMessage()
        asyncio.run(spy_group.create_spy_game(message))
        text, markup = message.answers[-1]
        self.assertIn("JOSUS (SPYFALL)", text)
        self.assertIn("kishi", text)

        buttons = [row[0] for row in markup.inline_keyboard]
        self.assertEqual(len(buttons), 3)
        self.assertTrue(buttons[0].url.startswith("https://t.me/revilend_gamesbot?startapp=spy_SPY"))
        self.assertTrue(buttons[1].callback_data.startswith(spy_group.JOIN_PREFIX))
        self.assertTrue(buttons[2].callback_data.startswith(spy_group.START_PREFIX))

    def test_josus_alias_also_opens_lobby(self) -> None:
        message = FakeMessage(user_id=702, name="Vali")
        asyncio.run(spy_group.create_spy_game(message))
        self.assertIn("JOSUS", message.answers[-1][0])

    def test_lobby_in_private_chat_redirects_to_group(self) -> None:
        message = FakeMessage(chat_id=702, chat_type="private")
        asyncio.run(spy_group.create_spy_game_private(message))
        self.assertIn("guruhda", message.answers[-1][0])

    def test_join_callback_adds_player(self) -> None:
        manager = get_default_manager()
        room = manager.create_room(701, "Ali", chat_id=-100777)
        callback = FakeCallback(f"{spy_group.JOIN_PREFIX}{room.code}", user_id=702, name="Vali")
        asyncio.run(spy_group.join_spy_game(callback))

        self.assertIn("qo'shildingiz", callback.answered[-1])
        updated = manager.get_room(room.code)
        self.assertIn(702, updated.players)
        sent = callback.bot.messages[-1][1]
        self.assertIn("Vali", sent)

    def test_non_host_cannot_start(self) -> None:
        manager = get_default_manager()
        room = manager.create_room(701, "Ali", chat_id=-100777)
        manager.join(room.code, 702, "Vali")
        manager.join(room.code, 703, "Zilola")
        callback = FakeCallback(f"{spy_group.START_PREFIX}{room.code}", user_id=702)
        asyncio.run(spy_group.start_spy_game(callback))

        self.assertIn("faqat xona egasi", callback.answered[-1])
        self.assertEqual(manager.get_room(room.code).phase.value, "LOBBY")

    def test_host_starts_and_group_gets_announcement(self) -> None:
        manager = get_default_manager()
        room = manager.create_room(701, "Ali", chat_id=-100777)
        manager.join(room.code, 702, "Vali")
        manager.join(room.code, 703, "Zilola")
        callback = FakeCallback(f"{spy_group.START_PREFIX}{room.code}")
        asyncio.run(spy_group.start_spy_game(callback))

        self.assertEqual(manager.get_room(room.code).phase.value, "PLAYING")
        texts = [text for _chat, text, _markup in callback.bot.messages]
        self.assertTrue(any("O'YINI BOSHLANDI" in text for text in texts), texts)

    def test_finish_announcement_shows_location_and_reward(self) -> None:
        manager = SpyfallManager(seed=5)
        room = manager.create_room(701, "Ali", chat_id=-100777)
        manager.join(room.code, 702, "Vali")
        manager.join(room.code, 703, "Zilola")
        started = manager.start(room.code, 701)
        spy_id = sorted(started.spy_ids)[0]
        wrong = next(
            location.key for location in LOCATIONS if location.key != started.location.key
        )
        manager.guess(room.code, spy_id, wrong)

        bot = FakeBot()
        asyncio.run(spy_group.announce_room(bot, manager.get_room(room.code), "finish"))
        chat_id, text, _markup = bot.messages[-1]
        self.assertEqual(chat_id, -100777)
        self.assertIn("TINCH AHOLI", text)
        self.assertIn(started.location.name, text)
        self.assertIn("+25", text)
        self.assertIn(started.players[spy_id].display_name(), text)

    def test_announcement_is_skipped_without_chat(self) -> None:
        manager = SpyfallManager(seed=5)
        room = manager.create_room(701, "Ali")
        manager.join(room.code, 702, "Vali")
        manager.join(room.code, 703, "Zilola")
        manager.start(room.code, 701)
        bot = FakeBot()
        asyncio.run(spy_group.announce_room(bot, manager.get_room(room.code), "start"))
        self.assertEqual(bot.messages, [])

    def test_spy_count_for_player_amounts(self) -> None:
        self.assertEqual(spy_group.spy_count_for(3), 1)
        self.assertEqual(spy_group.spy_count_for(6), 1)
        self.assertEqual(spy_group.spy_count_for(7), 2)
        self.assertEqual(spy_group.spy_count_for(12), 2)


if __name__ == "__main__":
    unittest.main()
