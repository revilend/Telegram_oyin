"""Tests for Mafia group moderator room lookup."""

import unittest
from unittest.mock import patch

from bot.handlers.mafia_group import MafiaLobbyManager, _active_game_for_chat
from games.mafia.engine import Winner


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


if __name__ == "__main__":
    unittest.main()
