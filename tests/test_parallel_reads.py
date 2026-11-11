"""Parallel o'qishlar lock bilan serializatsiya qilinmasligini tekshirish.

Ilgari ``EconomyStore`` global lock'i Supabase SELECT'lari davomida ham
ushlab turilardi, shuning uchun ``asyncio.gather(to_thread(...))`` bilan
yuborilgan so'rovlar ketma-ket bajarilardi (tezlik oshmaydi). Endi lock
faqat kesh va in-memory holatni himoyalaydi.
"""

from __future__ import annotations

import asyncio
import os
import time
import unittest

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")

from core.economy import EconomyStore  # noqa: E402

LATENCY = 0.2


def _row(user_id: int) -> dict:
    return {
        "telegram_id": user_id,
        "username": f"user{user_id}",
        "full_name": f"User {user_id}",
        "coins": 100,
        "total_purchased": 0,
        "games_played": 0,
        "wins": 0,
        "bunker_wins": 0,
        "mafia_wins": 0,
        "spy_wins": 0,
        "alias_wins": 0,
        "bomb_wins": 0,
        "referral_count": 0,
        "last_bonus_at": "",
        "last_daily_claim": "",
        "bonus_streak": 0,
        "streak_days": 0,
        "role": "user",
        "is_blocked": False,
        "block_reason": "",
        "is_bot": False,
        "language_code": "",
        "created_at": "2025-01-01T00:00:00+00:00",
    }


class _SlowQuery:
    def __init__(self, client, table: str, mode: str, payload=None) -> None:
        self._client = client
        self._table = table
        self._mode = mode
        self._payload = payload
        self._filters: list[tuple[str, object]] = []

    def eq(self, column: str, value: object):
        self._filters.append((column, value))
        return self

    def gte(self, column: str, value: object):
        self._filters.append((column, value))
        return self

    def lte(self, column: str, value: object):
        self._filters.append((column, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _count: int):
        return self

    def select(self, *_args):
        self._mode = "select"
        return self

    def execute(self):
        time.sleep(LATENCY)
        if self._mode != "select":
            return type("Response", (), {"data": [dict(self._payload or {})]})()
        rows = list(self._client.rows.get(self._table, []))
        for column, value in self._filters:
            rows = [row for row in rows if row.get(column) == value]
        return type("Response", (), {"data": rows})()


class _SlowTable:
    def __init__(self, client, name: str) -> None:
        self._client = client
        self._name = name

    def select(self, *_args):
        return _SlowQuery(self._client, self._name, "select")

    def insert(self, payload, **_kwargs):
        return _SlowQuery(self._client, self._name, "insert", payload)

    def upsert(self, payload, **_kwargs):
        return _SlowQuery(self._client, self._name, "upsert", payload)

    def update(self, payload):
        return _SlowQuery(self._client, self._name, "update", payload)

    def delete(self, **_kwargs):
        return _SlowQuery(self._client, self._name, "delete")


class _SlowClient:
    def __init__(self) -> None:
        self.rows = {"users": [_row(1), _row(2)], "referrals": []}

    def table(self, name: str) -> _SlowTable:
        return _SlowTable(self, name)


class ParallelReadsTest(unittest.TestCase):
    def test_gathered_reads_overlap_instead_of_serializing(self) -> None:
        store = EconomyStore(client=_SlowClient())
        store.invalidate_user()

        async def run():
            return await asyncio.gather(
                asyncio.to_thread(store.find_user, 1),
                asyncio.to_thread(store.has_user, 2),
            )

        started = time.perf_counter()
        found, exists = asyncio.run(run())
        elapsed = time.perf_counter() - started

        self.assertEqual(found.user_id, 1)
        self.assertTrue(exists)
        # Ikkita 0.2 s so'rov parallel bo'lsa ~0.2 s, ketma-ket bo'lsa ~0.4 s.
        self.assertLess(elapsed, LATENCY * 1.65, f"o'qishlar ketma-ket ketdi: {elapsed:.2f} s")

    def test_cached_reads_stay_instant(self) -> None:
        store = EconomyStore(client=_SlowClient())
        store.invalidate_user()
        store.find_user(1)
        started = time.perf_counter()
        self.assertIsNotNone(store.find_user(1))
        self.assertLess(time.perf_counter() - started, LATENCY / 2)


if __name__ == "__main__":
    unittest.main()
