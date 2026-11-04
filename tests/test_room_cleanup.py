"""Inactive room cleanup tests for the three game managers."""
from __future__ import annotations

import time
import unittest

from bot.handlers.mafia_group import MafiaLobbyManager
from engine.game_manager import GameManager, RoomNotFoundError
from games.mafia.engine import GamePhase
from games.spyfall.engine import Phase
from games.spyfall.manager import SpyfallManager
from models.game import RoomStatus


class RoomCleanupTests(unittest.TestCase):
    def test_bunker_lobby_expires_after_fifteen_minutes(self) -> None:
        manager = GameManager(seed=1)
        room = manager.create_room(1, "A", "")
        removed = manager.expire_inactive(now=time.time() + 901)
        self.assertEqual(removed, [room.code])
        self.assertEqual(room.status, RoomStatus.EXPIRED)
        with self.assertRaises(RoomNotFoundError):
            manager.get_room(room.code)

    def test_bunker_active_room_finishes_after_thirty_minutes(self) -> None:
        manager = GameManager(seed=2)
        room = manager.create_room(1, "A", "")
        manager.join_room(room.code, 2, "B", "")
        manager.start_game(room.code)
        removed = manager.expire_inactive(now=time.time() + 1801)
        self.assertEqual(removed, [room.code])
        self.assertEqual(room.status, RoomStatus.FINISHED)

    def test_mafia_lobby_expires(self) -> None:
        manager = MafiaLobbyManager(seed=3)
        game = manager.create_game(-100, 1, "A")
        removed = manager.expire_inactive(now=time.time() + 901)
        self.assertEqual(removed, [game.code])
        self.assertEqual(manager._games, {})

    def test_spyfall_lobby_expires(self) -> None:
        manager = SpyfallManager(seed=4)
        room = manager.create_room(1, "A")
        removed = manager.expire_inactive(now=time.time() + 901)
        self.assertEqual(removed, [room.code])
        self.assertEqual(room.phase, Phase.LOBBY)
        with self.assertRaises(Exception):
            manager.get_room(room.code)


if __name__ == "__main__":
    unittest.main()
