"""Hamyon, cheklar va booster tarixi uchun testlar."""

import unittest

from core.economy import (
    APPROVED,
    PENDING,
    REJECTED,
    EconomyError,
    EconomyStore,
    InsufficientCoinsError,
)


class EconomyStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = EconomyStore(url="", key="", client=None)

    def test_wallet_starts_empty_and_add_spend(self) -> None:
        account = self.store.ensure_user(100, "ali", "Ali")
        self.assertEqual(account.coins, 0)
        self.assertEqual(account.games_played, 0)

        self.store.add_coins(100, 500)
        self.assertEqual(self.store.get_user(100).coins, 500)
        self.assertEqual(self.store.spend_coins(100, 120).coins, 380)
        with self.assertRaises(InsufficientCoinsError):
            self.store.spend_coins(100, 1000)
        self.assertEqual(self.store.get_user(100).coins, 380)

    def test_payment_approval_credits_once(self) -> None:
        payment = self.store.create_payment(200, "vali", "Vali", 500, "file-id")
        self.assertEqual(payment.status, PENDING)
        self.assertEqual(payment.price_uzs, 10_000)

        approved = self.store.approve_payment(payment.id, 1)
        self.assertEqual(approved.status, APPROVED)
        account = self.store.get_user(200)
        self.assertEqual(account.coins, 500)
        self.assertEqual(account.total_purchased, 500)

        with self.assertRaises(EconomyError):
            self.store.approve_payment(payment.id, 1)
        self.assertEqual(self.store.get_user(200).coins, 500)

    def test_payment_rejection_does_not_credit(self) -> None:
        payment = self.store.create_payment(201, "", "Zilola", 1500, "receipt")
        rejected = self.store.reject_payment(payment.id, 1)
        self.assertEqual(rejected.status, REJECTED)
        self.assertEqual(self.store.get_user(201).coins, 0)
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
        self.assertEqual(stats["coins_in_balance"], 550)
        self.assertEqual(stats["active_rooms"], 2)
        self.assertEqual(self.store.list_user_ids(), [300, 301])


if __name__ == "__main__":
    unittest.main()
