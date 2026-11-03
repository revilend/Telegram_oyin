"""Hamyon, cheklar va booster tarixi uchun testlar."""

import unittest
from typing import Any

from core.economy import (
    APPROVED,
    PENDING,
    REJECTED,
    START_COINS,
    EconomyError,
    EconomyStore,
    InsufficientCoinsError,
)


class _FakeResponse:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _FakeQuery:
    """Supabase query builder'ning minimal taqlidi."""

    def __init__(self, client: "_FakeUsersClient", table: str) -> None:
        self.client = client
        self.table_name = table
        self.mode = "select"
        self.columns = "*"
        self.filters: dict[str, Any] = {}
        self.limit_value: int | None = None
        self.row: dict[str, Any] = {}
        self.changes: dict[str, Any] = {}

    def select(self, columns: str = "*") -> "_FakeQuery":
        self.mode = "select"
        self.columns = columns
        return self

    def insert(self, row: dict[str, Any]) -> "_FakeQuery":
        self.mode = "insert"
        self.row = dict(row)
        return self

    def update(self, changes: dict[str, Any]) -> "_FakeQuery":
        self.mode = "update"
        self.changes = dict(changes)
        return self

    def eq(self, column: str, value: Any) -> "_FakeQuery":
        self.filters[column] = value
        return self

    def limit(self, value: int) -> "_FakeQuery":
        self.limit_value = value
        return self

    def execute(self) -> _FakeResponse:
        self.client.queries.append((self.table_name, self.mode, dict(self.filters)))
        rows = self.client.tables.setdefault(self.table_name, [])
        if self.mode == "insert":
            rows.append(dict(self.row))
            return _FakeResponse([dict(self.row)])
        if self.mode == "update":
            for row in rows:
                if all(row.get(k) == v for k, v in self.filters.items()):
                    row.update(self.changes)
            return _FakeResponse([])
        matched = [
            dict(row)
            for row in rows
            if all(row.get(k) == v for k, v in self.filters.items())
        ]
        if self.limit_value is not None:
            matched = matched[: self.limit_value]
        return _FakeResponse(matched)


class _FakeUsersClient:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {"users": list(rows or [])}
        self.queries: list[tuple[str, str, dict[str, Any]]] = []

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)


class EconomyStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EconomyStore(url="", key="", client=None)

    def test_wallet_starts_with_welcome_coins_and_add_spend(self) -> None:
        account = self.store.ensure_user(100, "ali", "Ali")
        self.assertEqual(account.coins, START_COINS)
        self.assertEqual(account.games_played, 0)

        self.store.add_coins(100, 500)
        self.assertEqual(self.store.get_user(100).coins, START_COINS + 500)
        self.assertEqual(self.store.spend_coins(100, 120).coins, START_COINS + 380)
        with self.assertRaises(InsufficientCoinsError):
            self.store.spend_coins(100, 10_000)
        self.assertEqual(self.store.get_user(100).coins, START_COINS + 380)

    def test_new_user_gets_start_coins_once(self) -> None:
        self.assertEqual(self.store.ensure_user(150).coins, START_COINS)
        self.store.spend_coins(150, START_COINS)
        self.assertEqual(self.store.ensure_user(150).coins, 0)

    def test_payment_approval_credits_once(self) -> None:
        payment = self.store.create_payment(200, "vali", "Vali", 500, "file-id")
        self.assertEqual(payment.status, PENDING)
        self.assertEqual(payment.price_uzs, 10_000)

        approved = self.store.approve_payment(payment.id, 1)
        self.assertEqual(approved.status, APPROVED)
        account = self.store.get_user(200)
        self.assertEqual(account.coins, START_COINS + 500)
        self.assertEqual(account.total_purchased, 500)

        with self.assertRaises(EconomyError):
            self.store.approve_payment(payment.id, 1)
        self.assertEqual(self.store.get_user(200).coins, START_COINS + 500)

    def test_payment_rejection_does_not_credit(self) -> None:
        payment = self.store.create_payment(201, "", "Zilola", 1500, "receipt")
        rejected = self.store.reject_payment(payment.id, 1)
        self.assertEqual(rejected.status, REJECTED)
        self.assertEqual(self.store.get_user(201).coins, START_COINS)
        with self.assertRaises(EconomyError):
            self.store.reject_payment(payment.id, 1)

    def test_unknown_package_and_empty_receipt(self) -> None:
        with self.assertRaises(EconomyError):
            self.store.create_payment(202, "", "X", 999, "file")
        with self.assertRaises(EconomyError):
            self.store.create_payment(202, "", "X", 500, "")

    def test_booster_usage_is_recorded_once(self) -> None:
        self.assertFalse(self.store.has_booster("BNK123", 1, "shield"))
        self.assertTrue(self.store.record_booster("BNK123", 1, "shield"))
        self.assertFalse(self.store.record_booster("BNK123", 1, "shield"))
        self.assertTrue(self.store.has_booster("BNK123", 1, "shield"))
        self.assertFalse(self.store.has_booster("BNK123", 2, "shield"))

    def test_finished_game_updates_stats_once(self) -> None:
        self.assertTrue(
            self.store.record_finished_game("BNK456", [1, 2, 3], [1, 2])
        )
        self.assertFalse(self.store.record_finished_game("BNK456", [1, 2, 3], [1]))
        self.assertEqual(self.store.get_user(1).games_played, 1)
        self.assertEqual(self.store.get_user(1).wins, 1)
        self.assertEqual(self.store.get_user(2).wins, 1)
        self.assertEqual(self.store.get_user(3).games_played, 1)
        self.assertEqual(self.store.get_user(3).wins, 0)

    def test_stats_and_user_list(self) -> None:
        self.store.add_coins(300, 500, purchased=True)
        self.store.add_coins(301, 50)
        stats = self.store.stats(active_rooms=2, total_rooms=4)
        self.assertEqual(stats["users"], 2)
        self.assertEqual(stats["coins_purchased"], 500)
        self.assertEqual(stats["coins_in_balance"], 2 * START_COINS + 550)
        self.assertEqual(stats["active_rooms"], 2)
        self.assertEqual(self.store.list_user_ids(), [300, 301])


class UsersTelegramIdColumnTest(unittest.TestCase):
    """`users` jadvali `telegram_id` ustuni bilan ishlashini tekshiradi."""

    def test_existing_user_is_read_by_telegram_id(self) -> None:
        client = _FakeUsersClient(
            [
                {
                    "telegram_id": 900,
                    "username": "ali",
                    "full_name": "Ali",
                    "coins": 120,
                    "role": "user",
                }
            ]
        )
        store = EconomyStore(url="", key="", client=client)
        account = store.ensure_user(900)
        self.assertEqual(account.user_id, 900)
        self.assertEqual(account.coins, 120)
        self.assertEqual(len(client.tables["users"]), 1)
        used_columns = {
            column for _, _, filters in client.queries for column in filters
        }
        self.assertEqual(used_columns, {"telegram_id"})

    def test_new_user_is_inserted_with_telegram_id(self) -> None:
        client = _FakeUsersClient()
        store = EconomyStore(url="", key="", client=client)
        store.add_coins(901, 50)
        row = client.tables["users"][0]
        self.assertEqual(row["telegram_id"], 901)
        self.assertNotIn("user_id", row)
        self.assertEqual(row["coins"], START_COINS + 50)
        self.assertEqual(store.list_user_ids(), [901])
        self.assertEqual(store.stats()["users"], 1)

    def test_role_admin_is_detected_by_telegram_id(self) -> None:
        client = _FakeUsersClient(
            [
                {"telegram_id": 902, "role": "admin"},
                {"telegram_id": 903, "role": "user"},
            ]
        )
        store = EconomyStore(url="", key="", client=client)
        self.assertTrue(store.is_admin_user(902))
        self.assertFalse(store.is_admin_user(903))
        self.assertFalse(store.is_admin_user(904))
        used_columns = {
            column for _, _, filters in client.queries for column in filters
        }
        self.assertEqual(used_columns, {"telegram_id"})

    def test_memory_role_defaults_to_user(self) -> None:
        store = EconomyStore(url="", key="", client=None)
        store.ensure_user(905)
        self.assertEqual(store.get_role(905), "user")
        self.assertFalse(store.is_admin_user(905))


if __name__ == "__main__":
    unittest.main()
