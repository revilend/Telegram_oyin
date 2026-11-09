"""Supabase-first (database-first) arxitektura testlari."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.economy import EconomyStore
from core.persistence import (
    ADMIN_USER_ID,
    ensure_admin_profile,
    ensure_persistence_or_raise,
    persistence_status,
)
from core.shop import ShopStore


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.filters: dict[str, object] = {}
        self._op = "select"
        self._payload: object = None

    def select(self, *_args, **_kwargs):
        self._op = "select"
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def limit(self, _value):
        return self

    def insert(self, payload, **_kwargs):
        self._op = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, **_kwargs):
        self._op = "upsert"
        self._payload = payload
        return self

    def update(self, payload, **_kwargs):
        self._op = "update"
        self._payload = payload
        return self

    def _rows(self) -> list[dict]:
        if self.table == "users":
            source = list(self.client.users.values())
        elif self.table == "user_inventory":
            source = [dict(row) for row in self.client.inventory.values()]
        else:
            source = []
        return [
            dict(row)
            for row in source
            if all(row.get(key) == value for key, value in self.filters.items())
        ]

    def execute(self):
        if self._op == "insert" and isinstance(self._payload, dict):
            row = dict(self._payload)
            if self.table == "users":
                self.client.users[int(row["telegram_id"])] = row
            elif self.table == "user_inventory":
                key = (int(row["user_id"]), str(row["item_slug"]))
                self.client.inventory[key] = row
            return SimpleNamespace(data=[])
        if self._op == "upsert" and isinstance(self._payload, dict):
            row = dict(self._payload)
            if self.table == "users":
                key = int(row["telegram_id"])
                self.client.users[key] = {**self.client.users.get(key, {}), **row}
            elif self.table == "user_inventory":
                key = (int(row["user_id"]), str(row["item_slug"]))
                self.client.inventory[key] = row
            return SimpleNamespace(data=[])
        if self._op == "update" and isinstance(self._payload, dict):
            if self.table == "users" and "telegram_id" in self.filters:
                key = int(self.filters["telegram_id"])
                if key in self.client.users:
                    self.client.users[key].update(self._payload)
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=self._rows()[:1] if self._op == "select" else [])


class _Client:
    """users + user_inventory'ni xotirada tutadigan minimal Supabase fake."""

    def __init__(self):
        self.users: dict[int, dict] = {}
        self.inventory: dict[tuple[int, str], dict] = {}

    def table(self, name: str):
        return _Query(self, name)


class PersistenceTest(unittest.TestCase):
    def _stores(self):
        fake = _Client()
        economy = EconomyStore(url="", key="", client=fake)
        shop = ShopStore(economy=economy, client=fake)
        return economy, shop

    def test_admin_profile_is_created_with_recovery_values(self) -> None:
        economy, shop = self._stores()
        ok = ensure_admin_profile(economy, shop)
        self.assertTrue(ok)
        account = economy.ensure_user(ADMIN_USER_ID)
        self.assertGreaterEqual(account.coins, 100_000_000)
        self.assertGreaterEqual(account.bonus_streak, 4)
        self.assertGreaterEqual(account.streak_days, 4)
        entry = shop.entry(ADMIN_USER_ID, "frame_fire_dragon")
        self.assertEqual(entry.quantity, 1)
        self.assertTrue(entry.is_equipped)

    def test_existing_admin_profile_is_never_zeroed(self) -> None:
        economy, shop = self._stores()
        economy.ensure_user(ADMIN_USER_ID)
        economy.add_coins(ADMIN_USER_ID, 5)
        before = economy.ensure_user(ADMIN_USER_ID).coins
        ensure_admin_profile(economy, shop)
        after = economy.ensure_user(ADMIN_USER_ID)
        self.assertGreaterEqual(after.coins, before)

    def test_persistence_or_raise_allows_memory_in_test_mode(self) -> None:
        with patch.dict(os.environ, {"ALLOW_GUEST_AUTH": "true"}):
            ensure_persistence_or_raise()

    def test_persistence_or_raise_blocks_prod_without_supabase(self) -> None:
        with patch.dict(
            os.environ,
            {"ALLOW_GUEST_AUTH": "", "ALLOW_IN_MEMORY_FALLBACK": ""},
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                ensure_persistence_or_raise()

    def test_persistence_status_keys(self) -> None:
        status = persistence_status()
        self.assertIn("economy", status)
        self.assertIn("shop", status)


if __name__ == "__main__":
    unittest.main()
