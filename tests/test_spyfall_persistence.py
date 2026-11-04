"""Supabase persistence tests for Spyfall rooms."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from games import spyfall_api


class SpyfallPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        with spyfall_api._lock:
            spyfall_api._rooms.clear()

    def test_room_is_restored_after_in_memory_state_is_lost(self) -> None:
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

        client = FakeClient()
        store = SimpleNamespace(enabled=True, client=client)
        room = {
            "code": "SPY777",
            "host_id": 701,
            "status": "PLAYING",
            "players": {
                701: {"user_id": 701, "name": "Ali"},
                702: {"user_id": 702, "name": "Vali"},
                703: {"user_id": 703, "name": "Zilola"},
            },
            "roles": {701: "spy", 702: "player", 703: "player"},
            "location": "Muzey",
            "spy_id": 701,
            "votes": {702: 701},
            "winner": None,
        }

        with patch.object(spyfall_api, "get_store", return_value=store):
            spyfall_api._persist_room(room)
            with spyfall_api._lock:
                spyfall_api._rooms.clear()
            restored = spyfall_api._room("SPY777")

        self.assertEqual(restored["host_id"], 701)
        self.assertEqual(restored["players"][702]["name"], "Vali")
        self.assertEqual(restored["roles"][701], "spy")
        self.assertEqual(restored["votes"], {702: 701})
        self.assertEqual(restored["location"], "Muzey")


if __name__ == "__main__":
    unittest.main()
