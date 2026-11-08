"""Test rejimi botlari (`engine/test_bots.py`) testlari."""

import os
import unittest
from unittest.mock import patch

from engine import test_bots


class TestBotsRoomTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {test_bots.TEST_MODE_ENV: "1", "ALLOW_GUEST_AUTH": "true"})
        self.env.start()
        self.addCleanup(self.env.stop)
        test_bots._SESSIONS.clear()
        self.addCleanup(test_bots._SESSIONS.clear)

    def _room(self, game: str, host_id: int) -> str:
        if game == "bunker":
            from engine.game_manager import get_default_manager

            return get_default_manager().create_room(host_id, "Host", "host").code
        if game == "mafia":
            from bot.handlers import mafia_group

            return mafia_group.get_default_manager().create_game(0, host_id, "Host", "host").code
        if game == "spyfall":
            from games.spyfall.manager import get_default_manager

            return get_default_manager().create_room(host_id, "Host").code
        if game == "alias":
            from games.alias.engine import get_default_manager

            return get_default_manager().create_room(0, host_id, "Host", "host").code
        from games.bomb.manager import get_default_manager

        return get_default_manager().create_room(host_id, "Host").code

    def test_fill_room_adds_three_bots_and_starts(self) -> None:
        for index, game in enumerate(test_bots.GAMES):
            with self.subTest(game=game):
                code = self._room(game, 7_700_000 + index)
                result = test_bots.fill_room(game, code)
                self.assertTrue(result["ok"], msg=str(result))
                self.assertEqual(result["bots"], 3)

    def test_step_plays_every_game_to_the_end(self) -> None:
        for index, game in enumerate(test_bots.GAMES):
            with self.subTest(game=game):
                host_id = 7_710_000 + index
                code = self._room(game, host_id)
                self.assertTrue(test_bots.fill_room(game, code)["ok"])
                key = test_bots._key(game, code)
                for _ in range(80):
                    test_bots.step()
                    if key not in test_bots._SESSIONS:
                        break
                self.assertNotIn(key, test_bots._SESSIONS, msg=f"{game} tugamadi")
                report = " ".join(test_bots.status()["log"])
                self.assertIn(f"{game} {code.upper()}: tugadi", report)

    def test_unknown_game_is_rejected(self) -> None:
        result = test_bots.fill_room("stoltennis", "XXX000")
        self.assertFalse(result["ok"])
        self.assertIn("Noma'lum", result["error"])

    def test_watcher_only_fills_single_player_rooms(self) -> None:
        from engine.game_manager import get_default_manager

        manager = get_default_manager()
        room = manager.create_room(7_720_001, "Host", "host")
        manager.join_room(room.code, 7_720_002, "Friend", "friend")
        test_bots.step()
        self.assertNotIn(f"bunker:{room.code}", test_bots._SESSIONS)
