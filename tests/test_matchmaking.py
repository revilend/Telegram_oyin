"""Global matchmaking navbati uchun birlik testlar."""
from __future__ import annotations

import unittest

from engine.matchmaking import Matchmaking, MatchmakingError


class MatchmakingTests(unittest.IsolatedAsyncioTestCase):
    async def test_waiting_counter_and_match(self) -> None:
        created = []
        notices = []

        def create_room(game, players):
            created.append((game, players))
            return "BNK123"

        async def notify(user_id, message):
            notices.append((user_id, message))

        queue = Matchmaking(
            room_factory=create_room,
            notifier=notify,
            thresholds={"bunker": 2, "mafia": 6, "spyfall": 3},
        )
        first = await queue.join_queue(11, "bunker", name="Ali")
        self.assertEqual(first["status"], "waiting")
        self.assertEqual(first["count"], 1)
        status = await queue.status("bunker")
        self.assertEqual(status["count"], 1)

        second = await queue.join_queue(12, "bunker", name="Vali")
        self.assertEqual(second["status"], "matched")
        self.assertEqual(second["room_code"], "BNK123")
        self.assertEqual(len(created), 1)
        self.assertEqual({item[0] for item in notices}, {11, 12})
        self.assertEqual((await queue.status("bunker"))["count"], 0)

    async def test_duplicate_user_moves_between_game_queues(self) -> None:
        queue = Matchmaking(thresholds={"bunker": 5, "mafia": 6, "spyfall": 3})
        await queue.join_queue(22, "bunker")
        await queue.join_queue(22, "spyfall")
        self.assertEqual((await queue.status("bunker"))["count"], 0)
        self.assertEqual((await queue.status("spyfall"))["count"], 1)

    async def test_leave_removes_user(self) -> None:
        queue = Matchmaking()
        await queue.join_queue(33, "mafia")
        removed = await queue.leave_queue(33)
        self.assertEqual(removed, {"mafia": 1})
        self.assertEqual((await queue.status("mafia"))["count"], 0)

    async def test_failed_room_creation_keeps_queue(self) -> None:
        def fail(_game, _players):
            raise RuntimeError("room unavailable")

        queue = Matchmaking(
            room_factory=fail,
            thresholds={"bunker": 1, "mafia": 6, "spyfall": 3},
        )
        with self.assertRaises(RuntimeError):
            await queue.join_queue(44, "bunker")
        self.assertEqual((await queue.status("bunker"))["count"], 1)

    async def test_unknown_game_is_rejected(self) -> None:
        queue = Matchmaking()
        with self.assertRaises(MatchmakingError):
            await queue.join_queue(55, "unknown")


if __name__ == "__main__":
    unittest.main()
