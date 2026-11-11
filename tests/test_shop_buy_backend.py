"""Xarid faqat backend API orqali (frontend Supabase'ga yozmaydi)."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.economy import EconomyStore
from core.shop import ShopError, ShopStore, flush_transactions


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.filters: dict[str, object] = {}
        self._op = "select"
        self._payload = None

    def select(self, *_a, **_k):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def limit(self, _v):
        return self

    def insert(self, payload, **_k):
        self._op = "insert"
        self._payload = payload
        return self

    def upsert(self, payload, **_k):
        self._op = "upsert"
        self._payload = payload
        return self

    def update(self, payload, **_k):
        self._op = "update"
        self._payload = payload
        return self

    def execute(self):
        if self._op == "insert":
            if self.table in {"shop_transactions", "transactions"} and self.client.fail_transactions:
                raise RuntimeError("RLS: insert 42501")
            row = dict(self._payload or {})
            if self.table == "users":
                self.client.users[int(row["telegram_id"])] = row
            elif self.table == "user_inventory":
                key = (int(row["user_id"]), str(row["item_slug"]))
                self.client.inventory[key] = row
            elif self.table in {"shop_transactions", "transactions"}:
                self.client.transactions.append(row)
            return SimpleNamespace(data=[])
        if self._op == "upsert":
            row = dict(self._payload or {})
            if self.table == "users":
                key = int(row["telegram_id"])
                self.client.users[key] = {**self.client.users.get(key, {}), **row}
            elif self.table == "user_inventory":
                key = (int(row["user_id"]), str(row["item_slug"]))
                self.client.inventory[key] = row
            return SimpleNamespace(data=[])
        if self._op == "update":
            if self.table == "users" and "telegram_id" in self.filters:
                key = int(self.filters["telegram_id"])
                if key in self.client.users:
                    self.client.users[key].update(self._payload or {})
            return SimpleNamespace(data=[])
        if self.table == "users":
            rows = [
                dict(r)
                for r in self.client.users.values()
                if all(r.get(k) == v for k, v in self.filters.items())
            ]
        elif self.table == "user_inventory":
            rows = [
                dict(r)
                for r in self.client.inventory.values()
                if all(r.get(k) == v for k, v in self.filters.items())
            ]
        else:
            rows = []
        return SimpleNamespace(data=rows[:1] if rows else [])


class _Client:
    def __init__(self, fail_transactions: bool = False):
        self.users = {}
        self.inventory = {}
        self.transactions = []
        self.fail_transactions = fail_transactions

    def table(self, name: str):
        return _Query(self, name)


class ShopBuyBackendTest(unittest.TestCase):
    def _stores(self, fail_transactions: bool = False):
        fake = _Client(fail_transactions)
        economy = EconomyStore(url="", key="", client=fake)
        shop = ShopStore(economy=economy, client=fake)
        return fake, economy, shop

    def test_service_role_key_is_preferred_over_anon(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://x.supabase.co",
                "SUPABASE_KEY": "anon-key",
                "SUPABASE_SERVICE_ROLE_KEY": "service-key",
            },
        ):
            store = EconomyStore()
        self.assertEqual(store.key, "service-key")

    def test_buy_writes_inventory_and_transaction_via_backend(self) -> None:
        fake, economy, shop = self._stores()
        economy.ensure_user(7788)
        economy.add_coins(7788, 1000)
        result = shop.buy(7788, "frame_gold", 1)
        payload = result.as_dict()
        self.assertTrue(payload["success"])
        self.assertIn("new_balance", payload)
        self.assertEqual(payload["new_balance"], payload["coins"])
        entry = shop.entry(7788, "frame_gold")
        self.assertEqual(entry.quantity, 1)
        flush_transactions()
        self.assertTrue(fake.transactions)

    def test_transaction_write_failure_still_completes_purchase(self) -> None:
        """Tarix yozilmasa ham xarid bajariladi (tanga yechiladi, buyum beriladi)."""
        fake, economy, shop = self._stores(fail_transactions=True)
        economy.ensure_user(7789)
        economy.add_coins(7789, 1000)
        account = economy.ensure_user(7789)
        balance_before = account.coins
        result = shop.buy(7789, "frame_gold", 1)
        payload = result.as_dict()
        self.assertTrue(payload["success"])
        self.assertEqual(
            economy.ensure_user(7789).coins,
            balance_before - result.total_price,
        )
        self.assertEqual(shop.entry(7789, "frame_gold").quantity, 1)
        flush_transactions()
        self.assertFalse(fake.transactions)


if __name__ == "__main__":
    unittest.main()
