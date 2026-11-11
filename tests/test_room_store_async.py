"""0-ms o'yin harakatlari: xona yozuvi Supabase'ni kutmaydi.

Bu testlar ommaviy oqim talabini qo'riqlaydi: harakat (karta, ovoz, navbat)
RAMda darhol bajarilishi, Supabase yozuvi esa fon oqimida ketishi kerak.
"""

from __future__ import annotations

import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")

from core import room_store  # noqa: E402


class _SlowClient:
    """Har bir so'rovga sun'iy kechikish qo'shadigan minimal PostgREST mijozi."""

    def __init__(self, latency: float = 0.25) -> None:
        self.latency = latency
        self.rows: dict[str, dict[str, dict]] = {}
        self.upserts: list[tuple[str, dict]] = []
        self.deletes: list[tuple[str, str]] = []

    def table(self, name: str):
        client = self

        class _Query:
            def __init__(self) -> None:
                self._payload = None
                self._code: str | None = None
                self._delete = False

            def upsert(self, payload, **_kwargs):
                self._payload = payload
                return self

            def select(self, *_args):
                return self

            def eq(self, column: str, value):
                if column == "code":
                    self._code = str(value)
                return self

            def limit(self, _count: int):
                return self

            def delete(self, **_kwargs):
                self._delete = True
                return self

            def execute(self):
                time.sleep(client.latency)
                if self._delete:
                    client.deletes.append((name, self._code or ""))
                    client.rows.get(name, {}).pop(self._code or "", None)
                    return SimpleNamespace(data=[])
                if isinstance(self._payload, dict):
                    client.upserts.append((name, self._payload))
                    client.rows.setdefault(name, {})[
                        str(self._payload["code"])
                    ] = self._payload["state"]
                    return SimpleNamespace(data=[])
                bucket = client.rows.get(name, {})
                if self._code is not None:
                    state = bucket.get(self._code)
                    return SimpleNamespace(
                        data=[{"state": state}] if state is not None else []
                    )
                return SimpleNamespace(
                    data=[{"state": state} for state in bucket.values()]
                )

        return _Query()


class RoomStoreAsyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = _SlowClient(latency=0.25)
        self.store = SimpleNamespace(enabled=True, client=self.client)
        patcher = patch("core.room_store.get_store", return_value=self.store)
        patcher.start()
        self.addCleanup(patcher.stop)
        room_store.flush_room_writes(1.0)
        # Fon oqimi bizdan oldin yozib yubormasin — coalescing aniq tekshirilsin.
        delay = patch.object(room_store, "WRITE_DELAY", 5.0)
        delay.start()
        self.addCleanup(delay.stop)
        self.addCleanup(room_store.flush_room_writes, 2.0)

    def test_save_state_does_not_wait_for_supabase(self) -> None:
        started = time.perf_counter()
        room_store.save_state(room_store.BOMB_ROOMS_TABLE, "bmb1", {"turn": 1})
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.05, "harakat DB javobini kutmasligi kerak")
        self.assertGreaterEqual(room_store.pending_writes(), 1)

    def test_writes_to_same_room_are_coalesced(self) -> None:
        before = len(self.client.upserts)
        for turn in range(10):
            room_store.save_state(room_store.BOMB_ROOMS_TABLE, "bmb2", {"turn": turn})
        room_store.flush_room_writes()

        written = [
            payload
            for table, payload in self.client.upserts[before:]
            if table == room_store.BOMB_ROOMS_TABLE and payload["code"] == "BMB2"
        ]
        self.assertEqual(len(written), 1, "10 harakat = 1 upsert bo'lishi kerak")
        self.assertEqual(written[0]["state"]["turn"], 9)
        self.assertEqual(room_store.pending_writes(), 0)

    def test_read_flushes_pending_state_first(self) -> None:
        room_store.save_state(room_store.BOMB_ROOMS_TABLE, "bmb3", {"turn": 42})
        state = room_store.load_state(room_store.BOMB_ROOMS_TABLE, "bmb3")

        self.assertIsNotNone(state)
        self.assertEqual(state["turn"], 42)
        self.assertEqual(room_store.pending_writes(), 0)

    def test_delete_drops_queued_state(self) -> None:
        room_store.save_state(room_store.ALIAS_ROOMS_TABLE, "al1", {"turn": 1})
        room_store.delete_state(room_store.ALIAS_ROOMS_TABLE, "al1")
        room_store.flush_room_writes()

        self.assertNotIn("AL1", self.client.rows.get(room_store.ALIAS_ROOMS_TABLE, {}))
        self.assertIn((room_store.ALIAS_ROOMS_TABLE, "AL1"), self.client.deletes)


if __name__ == "__main__":
    unittest.main()
