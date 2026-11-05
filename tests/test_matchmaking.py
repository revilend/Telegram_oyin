"""Global navbat, tozalovchi va haftalik liga testlari."""

from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import server as server_module
from api.server import app
from core.economy import EconomyStore
from core.leaderboard import build_leaderboard, medal_for, week_bounds
from engine.cleaner import RoomCleaner
from engine.game_manager import GameManager
from engine.matchmaking import Matchmaker, get_matchmaker
from models.game import RoomStatus


def _players(count: int) -> list[dict[str, object]]:
    return [
        {"user_id": 90000 + index, "name": f"Player {index}", "username": f"p{index}"}
        for index in range(count)
    ]


class MatchmakerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.matches: list[dict[str, object]] = []
        self.notified: list[dict[str, object]] = []
        self.matchmaker = Matchmaker(min_players={"bunker": 3, "mafia": 4})

        def factory(game_type, players):
            match = {
                "game_type": game_type,
                "code": f"TST{len(self.matches)}",
                "players": len(players),
            }
            self.matches.append(match)
            return match

        self.matchmaker.set_room_factory(factory)
        self.matchmaker.set_notifier(
            lambda players, match: self.notified.append(
                {"players": len(players), "code": match["code"]}
            )
        )

    def test_queue_counts_and_auto_match(self) -> None:
        first = self.matchmaker.join(1, "bunker", name="Ali")
        self.assertEqual(first["count"], 1)
        self.assertEqual(first["need"], 2)
        self.assertIsNone(first["match"])

        again = self.matchmaker.join(1, "bunker", name="Ali")
        self.assertEqual(again["count"], 1, "Bir o'yinchi ikki marta qo'shilmasin")

        self.matchmaker.join(2, "bunker", name="Vali")
        final = self.matchmaker.join(3, "bunker", name="Zilola")
        self.assertIsNotNone(final["match"])
        self.assertEqual(final["match"]["game_type"], "bunker")
        self.assertEqual(final["count"], 0)
        self.assertEqual(len(self.matches), 1)
        self.assertEqual(self.notified, [{"players": 3, "code": "TST0"}])

    def test_leave_removes_player(self) -> None:
        self.matchmaker.join(5, "mafia", name="Aziz")
        left = self.matchmaker.leave(5, "mafia")
        self.assertTrue(left["left"])
        self.assertEqual(left["count"], 0)
        self.assertFalse(self.matchmaker.leave(5, "mafia")["left"])

    def test_factory_failure_keeps_queue(self) -> None:
        def broken(game_type, players):
            raise RuntimeError("xona ochilmadi")

        self.matchmaker.set_room_factory(broken)
        for user_id in (11, 12):
            self.matchmaker.join(user_id, "bunker", name=f"P{user_id}")
        result = self.matchmaker.join(13, "bunker", name="P13")
        self.assertIsNone(result["match"])
        self.assertEqual(result["count"], 3, "Xatodan keyin navbat saqlanishi kerak")

    def test_recent_match_is_visible_to_all_participants(self) -> None:
        for user_id in (21, 22, 23):
            self.matchmaker.join(user_id, "bunker", name=f"P{user_id}")
        self.assertEqual(self.matchmaker.recent_match(21)["code"], "TST0")
        self.assertEqual(self.matchmaker.recent_match(23)["code"], "TST0")
        self.assertIsNone(self.matchmaker.recent_match(99))
        self.assertIsNone(self.matchmaker.recent_match(21, "mafia"))

    def test_unknown_game_type_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            self.matchmaker.join(1, "shaxmat")


class CleanerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = GameManager(seed=7)
        self.patcher = patch(
            "engine.cleaner._bunker_sweep",
            lambda lobby_idle, game_idle: self.manager.expire_stale(
                lobby_idle_seconds=lobby_idle, game_idle_seconds=game_idle
            ),
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_idle_lobby_expires(self) -> None:
        room = self.manager.create_room(5001, "Ali", "ali")
        self.manager._room_times[room.code] = time.time() - 16 * 60

        cleaner = RoomCleaner(
            interval_seconds=300,
            lobby_idle_seconds=15 * 60,
            game_idle_seconds=30 * 60,
            sweepers={"bunker": lambda lobby, game: self.manager.expire_stale(
                lobby_idle_seconds=lobby, game_idle_seconds=game
            )},
        )
        report = cleaner.sweep_once()
        self.assertEqual(report["bunker"]["expired"], 1)
        self.assertEqual(cleaner.total_expired, 1)
        self.assertIsNone(self.manager._rooms.get(room.code))

    def test_fresh_lobby_is_kept(self) -> None:
        room = self.manager.create_room(5002, "Vali", "vali")
        cleaner = RoomCleaner(
            sweepers={"bunker": lambda lobby, game: self.manager.expire_stale(
                lobby_idle_seconds=lobby, game_idle_seconds=game
            )}
        )
        report = cleaner.sweep_once()
        self.assertEqual(report["bunker"]["expired"], 0)
        self.assertIsNotNone(self.manager._rooms.get(room.code))

    def test_bunker_room_status_becomes_expired(self) -> None:
        room = self.manager.create_room(5003, "Zilola", "zilola")
        self.manager._room_times[room.code] = time.time() - 20 * 60
        self.manager.expire_stale(lobby_idle_seconds=60, game_idle_seconds=120)
        self.assertIs(room.status, RoomStatus.EXPIRED)


class LeaderboardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EconomyStore(url="", key="", client=None)

    def test_week_bounds_start_monday(self) -> None:
        start, end = week_bounds()
        self.assertEqual(start.weekday(), 0)
        self.assertEqual(start.hour, 0)
        self.assertEqual((end - start).days, 7)

    def test_medals_for_top_three(self) -> None:
        self.assertEqual(medal_for(1), "gold")
        self.assertEqual(medal_for(2), "silver")
        self.assertEqual(medal_for(3), "bronze")
        self.assertIsNone(medal_for(4))

    def test_weekly_board_uses_week_games(self) -> None:
        self.store.record_finished_game("BNKL1", [81001, 81002], [81001])
        board = build_leaderboard("week", 10, 81001, economy=self.store)
        self.assertEqual(board["period"], "week")
        self.assertEqual(board["top"][0]["user_id"], 81001)
        self.assertEqual(board["top"][0]["medal"], "gold")
        self.assertEqual(board["top"][0]["points"], 3)
        self.assertTrue(board["me"]["is_me"])


class ApiFeatureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {"ALLOW_GUEST_AUTH": "true"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(app)
        self.economy = EconomyStore(url="", key="", client=None)
        self.patcher = patch.object(
            server_module, "get_economy", return_value=self.economy
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        get_matchmaker().reset()

    def tearDown(self) -> None:
        self.client.close()
        get_matchmaker().reset()

    def test_join_and_leave_matchmaking(self) -> None:
        joined = self.client.post(
            "/api/matchmaking/join",
            json={"game_type": "mafia", "user_id": 82001, "name": "Ali"},
        )
        self.assertEqual(joined.status_code, 200, joined.text)
        payload = joined.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["min"], 6)
        self.assertFalse(payload["match"])

        status = self.client.get(
            "/api/matchmaking?game_type=mafia&user_id=82001"
        ).json()
        self.assertEqual(status["count"], 1)
        self.assertEqual(status["position"], 1)

        left = self.client.post(
            "/api/matchmaking/leave",
            json={"game_type": "mafia", "user_id": 82001},
        )
        self.assertTrue(left.json()["left"])

    def test_unknown_game_type_returns_400(self) -> None:
        response = self.client.post(
            "/api/matchmaking/join",
            json={"game_type": "shaxmat", "user_id": 82002},
        )
        self.assertEqual(response.status_code, 400, response.text)

    def test_top_endpoint_weekly_period(self) -> None:
        self.economy.record_finished_game("BNKL9", [82003], [82003])
        payload = self.client.get(
            "/api/top?period=week&limit=5&user_id=82003"
        ).json()
        self.assertEqual(payload["period"], "week")
        self.assertTrue(payload["top"])
        self.assertEqual(payload["top"][0]["user_id"], 82003)
        self.assertEqual(payload["top"][0]["medal"], "gold")

    def test_profile_includes_recent_history(self) -> None:
        self.economy.record_finished_game("BNKL7", [82004], [82004])
        payload = self.client.get("/api/me?user_id=82004").json()
        self.assertIn("history", payload)
        self.assertEqual(len(payload["history"]), 1)
        self.assertEqual(payload["history"][0]["room_code"], "BNKL7")
        self.assertTrue(payload["history"][0]["won"])


if __name__ == "__main__":
    unittest.main()
