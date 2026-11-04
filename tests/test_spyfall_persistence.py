"""Josus xonalarini Supabase'dan tiklash testlari."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from games.spyfall.engine import Phase
from games.spyfall.manager import SpyfallManager


class FakeQuery:
    def __init__(self, table):
        self.table = table
        self.code = None
        self.payload = None

    def select(self, *_args):
        return self

    def eq(self, _column, value):
        self.code = value
        return self

    def limit(self, _count):
        return self

    def upsert(self, payload, **_kwargs):
        self.payload = payload
        return self

    def execute(self):
        if self.payload is not None:
            self.table.rows[self.payload["code"]] = self.payload["state"]
            return SimpleNamespace(data=[])
        state = self.table.rows.get(self.code)
        return SimpleNamespace(data=[{"state": state}] if state else [])


class FakeClient:
    def __init__(self):
        self.rows = {}

    def table(self, _name):
        return FakeQuery(self)


class SpyfallPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient()
        self.store = SimpleNamespace(enabled=True, client=self.client)
        self.patcher = patch(
            "games.spyfall.manager.get_store", return_value=self.store
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _room(self):
        manager = SpyfallManager(seed=3)
        room = manager.create_room(801, "Ali", chat_id=-100500)
        manager.join(room.code, 802, "Vali")
        manager.join(room.code, 803, "Zilola")
        manager.start(room.code, 801, now=1000)
        return manager, room

    def test_room_is_restored_after_memory_is_lost(self) -> None:
        manager, room = self._room()
        spy_id = sorted(room.spy_ids)[0]
        self.assertIn(room.code, self.client.rows)

        manager.clear()
        restored = manager.get_room(room.code)
        self.assertEqual(restored.code, room.code)
        self.assertEqual(restored.chat_id, -100500)
        self.assertEqual(restored.host_id, 801)
        self.assertEqual(restored.phase, Phase.PLAYING)
        self.assertEqual(restored.location.key, room.location.key)
        self.assertEqual(restored.spy_ids, room.spy_ids)
        self.assertEqual(restored.deadline, 1000 + 300)
        self.assertIn(spy_id, restored.spy_ids)
        self.assertTrue(restored.player_view(spy_id)["is_spy"])
        self.assertEqual(
            restored.players[spy_id].hint_exclusions,
            room.players[spy_id].hint_exclusions,
        )

    def test_finished_room_keeps_result(self) -> None:
        manager, room = self._room()
        spy_id = sorted(room.spy_ids)[0]
        wrong = next(
            location.key
            for location in __import__(
                "games.spyfall.locations", fromlist=["LOCATIONS"]
            ).LOCATIONS
            if location.key != room.location.key
        )
        manager.guess(room.code, spy_id, wrong)
        manager.clear()

        restored = manager.get_room(room.code)
        self.assertEqual(restored.phase, Phase.FINISHED)
        self.assertEqual(restored.winner.value, "players")
        self.assertTrue(restored.rewards_granted)
        self.assertEqual(restored.location.key, room.location.key)

    def test_code_is_case_insensitive(self) -> None:
        manager, room = self._room()
        manager.clear()
        self.assertEqual(manager.get_room(room.code.lower()).code, room.code)


if __name__ == "__main__":
    unittest.main()
