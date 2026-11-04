"""Mafiya guruh moderatsiyasi: xona qidiruvi, arvoh rejimi va faza nazorati."""

from __future__ import annotations

import inspect
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("MINI_APP_URL", "https://revilend.games")
os.environ.setdefault("BOT_USERNAME", "revilend_gamesbot")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")

from bot.handlers import mafia_group
from bot.handlers.mafia_group import (
    MODERATED_PHASES,
    MafiaLobbyManager,
    _active_game_for_chat,
    mafia_chat_moderator,
)
from games.mafia.engine import GamePhase, MafiaPlayer, Winner

CHAT_ID = -100777


class ModeratorMessage:
    """Handler faqat shu maydonlarni ishlatadi."""

    def __init__(self, user_id: int, text: str = "salom") -> None:
        self.chat = SimpleNamespace(id=CHAT_ID, type="supergroup")
        self.from_user = SimpleNamespace(
            id=user_id, full_name="Ali Valiyev", username="ali"
        )
        self.text = text
        self.deleted = 0
        self.replies: list[str] = []

    async def delete(self) -> None:
        self.deleted += 1

    async def reply(self, text: str, **kwargs) -> None:
        self.replies.append(text)


class MafiaModeratorCommandFilterTest(unittest.IsolatedAsyncioTestCase):
    """Guruh buyruqlari catch-all moderatorda yutilmasligi kerak."""

    async def _matches(self, text: str) -> bool:
        handler = next(
            item
            for item in mafia_group.router.message.handlers
            if item.callback.__name__ == "mafia_chat_moderator"
        )
        message = ModeratorMessage(999, text)
        for filter_object in handler.filters:
            result = filter_object.call(message)
            if inspect.isawaitable(result):
                result = await result
            if not result:
                return False
        return True

    async def test_game_commands_are_not_swallowed(self) -> None:
        for text in (
            "/bunker@revilend_gamesbot",
            "/newgame@revilend_gamesbot",
            "/spy@revilend_gamesbot",
            "/mafia@revilend_gamesbot",
            "/bunker",
            "/spy",
        ):
            with self.subTest(text=text):
                self.assertFalse(await self._matches(text))

    async def test_plain_group_text_still_matches(self) -> None:
        self.assertTrue(await self._matches("salom"))


class MafiaModeratorLookupTest(unittest.TestCase):
    def test_finds_game_by_its_chat_id(self) -> None:
        manager = MafiaLobbyManager(seed=12)
        game = manager.create_game(-100123, 1, "Host")
        with patch("bot.handlers.mafia_group.get_default_manager", return_value=manager):
            self.assertIs(_active_game_for_chat(-100123), game)
            self.assertIsNone(_active_game_for_chat(-100999))

    def test_ignores_finished_game(self) -> None:
        manager = MafiaLobbyManager(seed=13)
        game = manager.create_game(-100123, 1, "Host")
        game.room.finish(Winner.TOWN)
        with patch("bot.handlers.mafia_group.get_default_manager", return_value=manager):
            self.assertIsNone(_active_game_for_chat(-100123))


class MafiaModeratorGhostModeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        mafia_group._last_words_spoken.clear()
        self.addCleanup(mafia_group._last_words_spoken.clear)
        self.manager = MafiaLobbyManager(seed=21)
        self.game = self.manager.create_game(CHAT_ID, 1, "Host")
        self.game.room.add_player(MafiaPlayer(2, "Vali"))

    def _set_phase(self, phase: GamePhase) -> None:
        self.game.room.phase = phase

    async def _send(self, message: ModeratorMessage) -> ModeratorMessage:
        with patch.object(
            mafia_group, "get_default_manager", return_value=self.manager
        ):
            await mafia_chat_moderator(message)
        return message

    async def test_moderated_phases_exclude_lobby(self) -> None:
        self.assertEqual(
            MODERATED_PHASES,
            (GamePhase.NIGHT, GamePhase.DAY_REPORT, GamePhase.VOTING),
        )
        self._set_phase(GamePhase.LOBBY)
        stranger = await self._send(ModeratorMessage(999))
        self.assertEqual(stranger.deleted, 0)

    async def test_stranger_messages_are_deleted_during_active_phases(self) -> None:
        for phase in MODERATED_PHASES:
            with self.subTest(phase=phase):
                self._set_phase(phase)
                stranger = await self._send(ModeratorMessage(999))
                self.assertEqual(stranger.deleted, 1)
                self.assertEqual(stranger.replies, [])

    async def test_alive_player_is_not_moderated(self) -> None:
        self._set_phase(GamePhase.NIGHT)
        message = await self._send(ModeratorMessage(1))
        self.assertEqual(message.deleted, 0)
        self.assertEqual(message.replies, [])

    async def test_dead_player_gets_one_last_word(self) -> None:
        self._set_phase(GamePhase.VOTING)
        self.game.room.eliminate(2)

        last_word = await self._send(ModeratorMessage(2, "Men begunoh edim!"))
        self.assertEqual(last_word.deleted, 0)
        self.assertEqual(len(last_word.replies), 1)
        self.assertIn("so'nggi so'z", last_word.replies[0])

        ghost = await self._send(ModeratorMessage(2, "Yana gapiraman"))
        self.assertEqual(ghost.deleted, 1)
        self.assertEqual(ghost.replies, [])

        again = await self._send(ModeratorMessage(2, "Va yana"))
        self.assertEqual(again.deleted, 1)

    async def test_last_word_ignores_commands(self) -> None:
        self._set_phase(GamePhase.NIGHT)
        self.game.room.eliminate(2)
        command = await self._send(ModeratorMessage(2, "/start"))
        self.assertEqual(command.deleted, 0)
        self.assertEqual(command.replies, [])


if __name__ == "__main__":
    unittest.main()
