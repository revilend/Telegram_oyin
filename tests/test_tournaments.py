"""Haftalik turnirlar va admin endpointlari testlari."""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.server import app
from bot.config import get_config
from core.economy import START_COINS, get_economy
from core.shop import InventoryEntry, ShopStore, get_shop_store, set_shop_store
from core.tournaments import (
    TournamentStore,
    get_tournament_store,
    set_tournament_store,
)


class TournamentTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "ALLOW_GUEST_AUTH": "true",
                "SUPABASE_URL": "",
                "SUPABASE_KEY": "",
                "BOT_TOKEN": "123456:TEST",
                "ADMIN_ID": "424242",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        get_config.cache_clear()
        self.addCleanup(get_config.cache_clear)

        self.economy = get_economy()
        set_shop_store(ShopStore(economy=self.economy))
        self.addCleanup(set_shop_store, None)
        self.store = TournamentStore(economy=self.economy, shop=get_shop_store())
        set_tournament_store(self.store)
        self.addCleanup(set_tournament_store, None)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def create_tournament(self, minutes: int = 48 * 60) -> str:
        start = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        tournament = self.store.create(
            "bunker", start.isoformat(), entry_fee=50, prize_pool=800
        )
        return tournament.id

    def coins(self, user_id: int) -> int:
        return self.economy.get_user(user_id).coins


class TournamentApiTest(TournamentTestBase):
    def test_active_seeds_weekly_championship(self) -> None:
        response = self.client.get("/api/tournaments/active?user_id=98001")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["tournaments"])
        weekly = payload["tournaments"][0]
        self.assertEqual(weekly["entry_fee"], 50)
        self.assertEqual(weekly["game"], "mixed")
        self.assertEqual(weekly["prize_pool"], 2_000)
        self.assertTrue(weekly["starts_at_local"])
        self.assertEqual(payload["coins"], START_COINS)

    def test_join_spends_coins_and_blocks_duplicates(self) -> None:
        tournament_id = self.create_tournament()
        before = self.coins(98002)

        joined = self.client.post(
            "/api/tournaments/join",
            json={"user_id": 98002, "tournament_id": tournament_id},
        )
        self.assertEqual(joined.status_code, 200)
        payload = joined.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["coins"], before - 50)
        self.assertEqual(payload["participants_count"], 1)
        self.assertFalse(payload["ticket_used"])

        duplicate = self.client.post(
            "/api/tournaments/join",
            json={"user_id": 98002, "tournament_id": tournament_id},
        )
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("allaqachon", duplicate.json()["detail"])

    def test_join_consumes_tournament_ticket(self) -> None:
        tournament_id = self.create_tournament()
        shop = get_shop_store()
        shop._save_entry(
            98003, InventoryEntry(item_slug="tournament_ticket", quantity=1)
        )
        self.economy.spend_coins(98003, self.coins(98003))

        response = self.client.post(
            "/api/tournaments/join",
            json={"user_id": 98003, "tournament_id": tournament_id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ticket_used"])
        self.assertEqual(response.json()["expense"], 0)
        self.assertEqual(shop.entry(98003, "tournament_ticket").quantity, 0)

    def test_join_without_money_returns_402(self) -> None:
        tournament_id = self.create_tournament()
        self.economy.spend_coins(98004, self.coins(98004))
        response = self.client.post(
            "/api/tournaments/join",
            json={"user_id": 98004, "tournament_id": tournament_id},
        )
        self.assertEqual(response.status_code, 402)
        self.assertIn("çiptasi kerak", response.json()["detail"])

    def test_bracket_pairs_participants(self) -> None:
        tournament_id = self.create_tournament()
        for uid in (98005, 98006, 98007):
            self.store.join(uid, tournament_id, f"user{uid}", f"User {uid}")
        rounds = self.store.bracket(tournament_id)
        self.assertGreaterEqual(len(rounds), 2)
        first = rounds[0]["matches"][0]
        self.assertIsNotNone(first["a"])
        self.assertIsNotNone(first["b"])

    def test_reminder_due_and_marked(self) -> None:
        tournament_id = self.create_tournament(minutes=20)
        self.store.join(98008, tournament_id, "ali", "Ali")
        due = self.store.due_reminders()
        self.assertEqual([item.id for item in due], [tournament_id])
        self.store.mark_reminded(tournament_id)
        self.assertEqual(self.store.due_reminders(), [])


class AdminApiTest(TournamentTestBase):
    def test_pending_payments_list_and_approve(self) -> None:
        payment = self.economy.create_payment(98010, "ali", "Ali", 500, "file-1")
        before = self.coins(98010)

        pending = self.client.get("/api/admin/payments/pending?user_id=424242")
        self.assertEqual(pending.status_code, 200)
        ids = [item["id"] for item in pending.json()["payments"]]
        self.assertIn(payment.id, ids)

        approved = self.client.post(
            f"/api/admin/payments/{payment.id}/approve?user_id=424242"
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["payment"]["status"], "APPROVED")
        self.assertEqual(self.coins(98010), before + 500)

    def test_reject_payment(self) -> None:
        payment = self.economy.create_payment(98011, "vali", "Vali", 500, "file-2")
        response = self.client.post(
            f"/api/admin/payments/{payment.id}/reject?user_id=424242"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["payment"]["status"], "REJECTED")

    def test_admin_endpoints_require_permission(self) -> None:
        response = self.client.get("/api/admin/payments/pending?user_id=98012")
        self.assertEqual(response.status_code, 403)

    def test_balance_adjustment(self) -> None:
        added = self.client.post(
            "/api/admin/balance",
            json={"user_id": 98013, "coins": 150, "admin_id": 424242},
        )
        self.assertEqual(added.status_code, 200)
        self.assertEqual(added.json()["user"]["coins"], START_COINS + 150)

        removed = self.client.post(
            "/api/admin/balance",
            json={"user_id": 98013, "coins": -50, "admin_id": 424242},
        )
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.json()["user"]["coins"], START_COINS + 100)

    def test_admin_creates_tournament(self) -> None:
        start = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        response = self.client.post(
            "/api/admin/tournaments",
            json={
                "game": "mafia",
                "starts_at": start,
                "entry_fee": 50,
                "prize_pool": 900,
                "admin_id": 424242,
            },
        )
        self.assertEqual(response.status_code, 200)
        tournament_id = response.json()["tournament"]["id"]
        active = self.client.get("/api/tournaments/active").json()["tournaments"]
        self.assertIn(tournament_id, [item["id"] for item in active])


class TournamentBotTest(TournamentTestBase):
    def test_poster_mentions_prize_and_join_button(self) -> None:
        from bot.handlers import tournaments as handler

        tournament_id = self.create_tournament()
        text = handler.poster_text(98020)
        self.assertIn("Sovrin fondi", text)
        self.assertIn("Boşlaniş", text)
        callbacks = [
            row[0].callback_data
            for row in handler.poster_keyboard(98020).inline_keyboard
        ]
        self.assertIn(f"tour_join_{tournament_id}", callbacks)
        self.assertIn("tour_update", callbacks)

    def test_reminder_text_mentions_start(self) -> None:
        from bot.handlers import tournaments as handler

        tournament_id = self.create_tournament(minutes=25)
        tournament = get_tournament_store().get(tournament_id)
        self.assertIsNotNone(tournament)
        text = handler.reminder_text(tournament)
        self.assertIn("30 daqiqa", text)
        self.assertIn(tournament.title, text)


if __name__ == "__main__":
    unittest.main()
