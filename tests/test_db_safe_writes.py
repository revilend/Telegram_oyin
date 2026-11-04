"""Supabase yozuvlarida PGRST204 (yetishmayotgan ustun) testlari."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.db import (
    PLAYERS_TABLE,
    ROOMS_TABLE,
    SupabaseStore,
    execute_with_column_retry,
    missing_column,
    safe_insert,
    safe_update,
    safe_upsert,
)
from models.game import GameRoom, Player


def pgrst204(column: str, table: str = "users") -> Exception:
    exc = Exception(
        f"Could not find the '{column}' column of '{table}' in the schema cache "
        "(code: PGRST204)"
    )
    exc.code = "PGRST204"  # type: ignore[attr-defined]
    return exc


class FakeQuery:
    def __init__(
        self,
        client: "FakeClient",
        table: str,
        mode: str,
        payload=None,
        on_conflict=None,
    ) -> None:
        self.client = client
        self.table = table
        self.mode = mode
        self.payload = payload
        self.on_conflict = on_conflict
        self.filters: list[tuple[str, object]] = []

    def eq(self, column: str, value: object) -> "FakeQuery":
        self.filters.append((column, value))
        return self

    def limit(self, _count: int) -> "FakeQuery":
        return self

    def select(self, *_args) -> "FakeQuery":
        self.mode = "select"
        return self

    def execute(self):
        if self.mode == "select":
            rows = self.client.select_rows.get(self.table, [])
            return SimpleNamespace(data=rows)

        rejected = self.client.reject_columns.get(self.table, set())
        rows = self.payload if isinstance(self.payload, list) else [self.payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            for column in rejected:
                if column in row:
                    raise pgrst204(column, self.table)
        for table, error in self.client.fail_tables.items():
            if table == self.table:
                raise error
        self.client.writes.append(
            {
                "table": self.table,
                "mode": self.mode,
                "payload": self.payload,
                "filters": list(self.filters),
                "on_conflict": self.on_conflict,
            }
        )
        return SimpleNamespace(data=[])


class FakeTable:
    def __init__(self, client: "FakeClient", name: str) -> None:
        self.client = client
        self.name = name

    def insert(self, payload, **kwargs) -> FakeQuery:
        return FakeQuery(self.client, self.name, "insert", payload)

    def upsert(self, payload, on_conflict=None, **_kwargs) -> FakeQuery:
        return FakeQuery(self.client, self.name, "upsert", payload, on_conflict)

    def update(self, payload) -> FakeQuery:
        return FakeQuery(self.client, self.name, "update", payload)

    def select(self, *_args) -> FakeQuery:
        return FakeQuery(self.client, self.name, "select")


class FakeClient:
    def __init__(
        self,
        reject_columns: dict[str, set[str]] | None = None,
        fail_tables: dict[str, Exception] | None = None,
        select_rows: dict[str, list[dict]] | None = None,
    ) -> None:
        self.reject_columns = reject_columns or {}
        self.fail_tables = fail_tables or {}
        self.select_rows = select_rows or {}
        self.writes: list[dict] = []

    def table(self, name: str) -> FakeTable:
        return FakeTable(self, name)


class MissingColumnParseTest(unittest.TestCase):
    def test_postgrest_message(self) -> None:
        self.assertEqual(
            missing_column(pgrst204("updated_at", "users")), "updated_at"
        )

    def test_quoted_postgres_message(self) -> None:
        exc = Exception('column "updated_at" of relation "users" does not exist')
        self.assertEqual(missing_column(exc), "updated_at")

    def test_qualified_postgres_message(self) -> None:
        exc = Exception("column users.updated_at does not exist")
        self.assertEqual(missing_column(exc), "updated_at")

    def test_other_errors_are_not_retried(self) -> None:
        self.assertIsNone(missing_column(RuntimeError("baza ishlamayapti")))
        self.assertIsNone(missing_column(Exception("duplicate key value")))


class SafeWriteTest(unittest.TestCase):
    def test_safe_insert_drops_missing_column(self) -> None:
        client = FakeClient({"users": {"updated_at"}})
        row = {"telegram_id": 1, "coins": 100, "updated_at": "2026"}
        safe_insert(client, "users", row)
        self.assertEqual(len(client.writes), 1)
        self.assertNotIn("updated_at", client.writes[0]["payload"])
        self.assertEqual(client.writes[0]["payload"]["coins"], 100)

    def test_safe_upsert_drops_missing_column_for_rows(self) -> None:
        client = FakeClient({"room_players": {"updated_at"}})
        rows = [
            {"room_code": "BNK1", "user_id": 1, "updated_at": "x"},
            {"room_code": "BNK1", "user_id": 2, "updated_at": "x"},
        ]
        safe_upsert(client, "room_players", rows, on_conflict="room_code,user_id")
        sent = client.writes[0]["payload"]
        self.assertEqual(len(sent), 2)
        self.assertTrue(all("updated_at" not in row for row in sent))
        self.assertEqual(client.writes[0]["on_conflict"], "room_code,user_id")

    def test_safe_update_drops_missing_column_and_keeps_filters(self) -> None:
        client = FakeClient({"users": {"updated_at"}})
        safe_update(
            client,
            "users",
            {"coins": 25, "updated_at": "x"},
            {"telegram_id": 7},
        )
        write = client.writes[0]
        self.assertEqual(write["payload"], {"coins": 25})
        self.assertEqual(write["filters"], [("telegram_id", 7)])

    def test_unknown_error_is_raised(self) -> None:
        client = FakeClient(fail_tables={"users": RuntimeError("tarmoq xatosi")})
        with self.assertRaises(RuntimeError):
            safe_insert(client, "users", {"telegram_id": 1})

    def test_retry_limit(self) -> None:
        client = FakeClient()
        calls = {"count": 0}

        class Query:
            def execute(self):
                calls["count"] += 1
                raise pgrst204("updated_at")

        with self.assertRaises(Exception):
            execute_with_column_retry(lambda _payload: Query(), {"updated_at": 1})
        # Bir marta ustun olib tashlanadi, keyin takroriy xato yuzaga chiqadi.
        self.assertEqual(calls["count"], 2)

    def test_save_room_strips_missing_columns(self) -> None:
        client = FakeClient(
            {
                ROOMS_TABLE: {"updated_at", "bunker_capacity"},
                PLAYERS_TABLE: {"updated_at"},
            }
        )
        store = SupabaseStore(client=client)
        room = GameRoom(
            room_id="room-1",
            code="BNK101",
            host_id=1,
            players={1: Player(user_id=1, username="ali", full_name="Ali", is_host=True)},
        )
        store.save_room(room, votes={1: 1})

        tables = [write["table"] for write in client.writes]
        self.assertEqual(tables, [ROOMS_TABLE, PLAYERS_TABLE])
        room_row = client.writes[0]["payload"]
        self.assertNotIn("updated_at", room_row)
        self.assertNotIn("bunker_capacity", room_row)
        self.assertEqual(room_row["code"], "BNK101")
        player_row = client.writes[1]["payload"][0]
        self.assertEqual(player_row["user_id"], 1)
        self.assertNotIn("updated_at", player_row)


if __name__ == "__main__":
    unittest.main()
