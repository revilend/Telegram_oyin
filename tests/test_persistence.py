"""Saqlash hooklari va Supabase mapping testlari."""

import unittest
from typing import Any

from core.db import SupabaseStore
from engine.game_manager import GameManager
from models.game import GameRoom


class ManagerPersistenceTest(unittest.TestCase):
    def test_change_handler_receives_every_mutation(self) -> None:
        manager = GameManager(seed=42)
        events: list[tuple[str, str, dict[int, int]]] = []
        manager.set_change_handler(
            lambda room, votes: events.append(
                (room.code, room.status.value, dict(votes))
            )
        )

        room = manager.create_room(1, "Ali", "ali", bunker_capacity=2)
        manager.join_room(room.code, 2, "Vali", "vali")
        manager.start_game(room.code)
        manager.reveal_card(room.code, 1, "profession")
        manager.cast_vote(room.code, 1, 2)
        manager.tally_votes(room.code)

        self.assertEqual(
            [status for _, status, _ in events],
            ["LOBBY", "LOBBY", "PLAYING", "PLAYING", "VOTING", "FINISHED"],
        )
        self.assertEqual(events[4][2], {1: 2})
        self.assertEqual(events[5][2], {})

    def test_loader_restores_room_and_votes(self) -> None:
        source = GameManager(seed=7)
        room = source.create_room(11, "Ali", "ali", bunker_capacity=2)
        source.join_room(room.code, 12, "Vali", "vali")
        source.start_game(room.code)
        source.reveal_card(room.code, 11, "health")
        source.cast_vote(room.code, 11, 12)

        snapshot = GameRoom.model_validate(room.model_dump(mode="json"))
        votes = {11: 12}

        target = GameManager(seed=8)
        calls: list[str] = []

        def loader(code: str):
            calls.append(code)
            return (snapshot, votes) if code == room.code else None

        target.set_room_loader(loader)
        restored = target.get_room(room.code.lower())

        self.assertEqual(restored.code, room.code)
        self.assertTrue(restored.players[11].cards["health"].is_revealed)
        self.assertEqual(restored.players[12].votes_against, 1)
        self.assertEqual(calls, [room.code])

        eliminated = target.tally_votes(room.code)
        self.assertIsNotNone(eliminated)
        self.assertEqual(eliminated.user_id, 12)
        self.assertEqual(len(calls), 1, "Xona ikkinchi marta yuklanmasligi kerak")

    def test_loader_missing_room_raises(self) -> None:
        manager = GameManager(seed=9)
        manager.set_room_loader(lambda code: None)
        with self.assertRaises(Exception) as ctx:
            manager.get_room("BNK000")
        self.assertIn("topilmadi", str(ctx.exception))


class _FakeResponse:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _FakeQuery:
    def __init__(self, client: "_FakeClient", table: str) -> None:
        self.client = client
        self.table_name = table
        self.mode = "select"
        self.filters: dict[str, Any] = {}
        self.limit_value: int | None = None

    def select(self, *columns: str) -> "_FakeQuery":
        self.mode = "select"
        return self

    def upsert(self, rows: Any, on_conflict: str | None = None) -> "_FakeQuery":
        self.client.upsert(self.table_name, [rows] if isinstance(rows, dict) else rows)
        self.mode = "upsert"
        return self

    def eq(self, column: str, value: Any) -> "_FakeQuery":
        self.filters[column] = value
        return self

    def limit(self, value: int) -> "_FakeQuery":
        self.limit_value = value
        return self

    def execute(self) -> _FakeResponse:
        if self.mode != "select":
            return _FakeResponse([])
        rows = [
            row
            for row in self.client.tables.get(self.table_name, [])
            if all(row.get(key) == value for key, value in self.filters.items())
        ]
        if self.limit_value is not None:
            rows = rows[: self.limit_value]
        return _FakeResponse([dict(row) for row in rows])


class _FakeClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "rooms": [],
            "room_players": [],
        }

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)

    def upsert(self, table: str, rows: list[dict[str, Any]]) -> None:
        if table == "rooms":
            merged = {row["code"]: row for row in self.tables[table]}
            merged.update({row["code"]: row for row in rows})
            self.tables[table] = list(merged.values())
            return
        merged_players = {
            (row["room_code"], row["user_id"]): row for row in self.tables[table]
        }
        merged_players.update(
            {(row["room_code"], row["user_id"]): row for row in rows}
        )
        self.tables[table] = list(merged_players.values())


class SupabaseMappingTest(unittest.TestCase):
    def test_round_trip_rooms_and_players(self) -> None:
        manager = GameManager(seed=21)
        room = manager.create_room(31, "Ali", "ali", bunker_capacity=2)
        manager.join_room(room.code, 32, "Vali", "vali")
        manager.start_game(room.code)
        manager.reveal_card(room.code, 31, "luggage")
        manager.cast_vote(room.code, 31, 32)

        store = SupabaseStore(client=_FakeClient())
        try:
            store.save_room(room, votes={31: 32})
            loaded = store.load_room(room.code)
        finally:
            store.close()

        self.assertIsNotNone(loaded)
        loaded_room, votes = loaded
        self.assertEqual(loaded_room.code, room.code)
        self.assertEqual(loaded_room.status.value, "VOTING")
        self.assertEqual(len(loaded_room.players), 2)
        self.assertTrue(loaded_room.players[31].cards["luggage"].is_revealed)
        self.assertEqual(loaded_room.players[32].votes_against, 1)
        self.assertEqual(votes, {31: 32})

    def test_disabled_store_is_noop(self) -> None:
        store = SupabaseStore(url="", key="", client=None)
        if store.enabled:
            self.skipTest("Muhitda SUPABASE_URL/SUPABASE_KEY o'rnatilgan")
        store.persist(GameRoom(room_id="x", code="BNK123", host_id=1), {})
        self.assertIsNone(store.load_room("BNK123"))
        store.close()


if __name__ == "__main__":
    unittest.main()
