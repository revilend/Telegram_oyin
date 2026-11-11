"""In-memory TTL kesh va 60 sekundlik profil keshining ishlashini tekshirish.

Bu testlar ommaviy yuklamadagi asosiy talabni qo'riqlaydi: takroriy tugma
bosishlarda Supabase'ga qo'shimcha o'qish so'rovi ketmasligi kerak.
"""

from __future__ import annotations

import os
import time
import unittest
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")

from core.cache import TTLCache, cache_stats  # noqa: E402
from core.economy import PROFILE_CACHE_TTL, EconomyStore  # noqa: E402


def _row(user_id: int) -> dict:
    return {
        "telegram_id": user_id,
        "username": "ali",
        "full_name": "Ali Valiyev",
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


class _CountingClient:
    """Har bir SELECT/UPDATE ni sanaydigan minimal Supabase mijozi."""

    def __init__(self) -> None:
        self.rows = {"users": [_row(1)]}
        self.selects = 0
        self.updates = 0

    def table(self, name: str):
        client = self

        class _Query:
            def __init__(self) -> None:
                self.filters: dict[str, object] = {}

            def select(self, *_args):
                return self

            def eq(self, column: str, value: object):
                self.filters[column] = value
                return self

            def limit(self, _count: int):
                return self

            def update(self, payload):
                client.updates += 1
                for row in client.rows.get(name, []):
                    if all(row.get(k) == v for k, v in self.filters.items()):
                        row.update(payload)
                return self

            def execute(self):
                if name == "users" and not client.updates:
                    client.selects += 1
                rows = [
                    dict(row)
                    for row in client.rows.get(name, [])
                    if all(row.get(k) == v for k, v in self.filters.items())
                ]
                return SimpleNamespace(data=rows[:1])

        return _Query()


class TTLCacheTest(unittest.TestCase):
    def test_set_get_and_expiry(self) -> None:
        cache: TTLCache[int] = TTLCache(ttl=0.05)
        cache.set("a", 1)
        self.assertEqual(cache.get("a"), 1)
        time.sleep(0.08)
        self.assertIsNone(cache.get("a"))

    def test_max_size_evicts_oldest(self) -> None:
        cache: TTLCache[str] = TTLCache(ttl=60, max_size=2)
        cache.set(1, "a")
        cache.set(2, "b")
        cache.set(3, "c")
        self.assertIsNone(cache.get(1))
        self.assertEqual(cache.get(3), "c")
        self.assertEqual(len(cache), 2)

    def test_stats_and_clear(self) -> None:
        cache: TTLCache[int] = TTLCache(ttl=60)
        cache.set("x", 1)
        cache.get("x")
        cache.get("y")
        stats = cache_stats(cache)
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["hit_rate"], 0.5)
        cache.clear()
        self.assertIsNone(cache.get("x"))
        self.assertEqual(len(cache), 0)


class ProfileCacheTest(unittest.TestCase):
    def test_repeat_reads_hit_cache_without_db_query(self) -> None:
        client = _CountingClient()
        store = EconomyStore(url="", key="", client=client)

        store.ensure_user(1, "ali", "Ali Valiyev")
        self.assertEqual(client.selects, 1)

        for _ in range(20):
            store.ensure_user(1, "ali", "Ali Valiyev")
            store.account_for(1)
            store.find_user(1)
        self.assertEqual(client.selects, 1, "takroriy o'qishlar keshdan bo'lishi kerak")

    def test_write_invalidates_cache(self) -> None:
        client = _CountingClient()
        store = EconomyStore(url="", key="", client=client)
        store.ensure_user(1, "ali", "Ali Valiyev")
        store.invalidate_user(1)
        store.ensure_user(1, "ali", "Ali Valiyev")
        self.assertEqual(client.selects, 2)

    def test_profile_cache_ttl_is_60_seconds(self) -> None:
        self.assertGreaterEqual(PROFILE_CACHE_TTL, 60.0)


if __name__ == "__main__":
    unittest.main()
