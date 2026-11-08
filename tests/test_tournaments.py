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


class FakeTournamentResponse:
    def __init__(self, data):
        self.data = data


class FakeTournamentQuery:
    """tournaments/tournament_participants uchun minimal PostgREST klienti."""

    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.mode = "select"
        self.payload = None
        self.filters = []
        self.limit_value = None
        self.range_value = None
        self.order_value = None

    def select(self, *_columns):
        self.mode = "select"
        return self

    def insert(self, payload, **_kwargs):
        self.mode = "insert"
        self.payload = dict(payload)
        return self

    def update(self, payload):
        self.mode = "update"
        self.payload = dict(payload)
        return self

    def delete(self):
        self.mode = "delete"
        return self

    def eq(self, column, value):
        self.filters.append((column, "eq", value))
        return self

    def gte(self, column, value):
        self.filters.append((column, "gte", value))
        return self

    def lte(self, column, value):
        self.filters.append((column, "lte", value))
        return self

    def order(self, column, desc=False):
        self.order_value = (column, bool(desc))
        return self

    def limit(self, value):
        self.limit_value = int(value)
        return self

    def range(self, start, end):
        self.range_value = (int(start), int(end))
        return self

    def execute(self):
        rows = self.client.tables.setdefault(self.table, [])
        if self.mode == "delete":
            rows[:] = [
                row
                for row in rows
                if not all(
                    row.get(column) == value
                    for column, operation, value in self.filters
                    if operation == "eq"
                )
            ]
            return FakeTournamentResponse([])
        if self.mode == "insert":
            row = dict(self.payload)
            key = "id" if self.table == "tournaments" else ("tournament_id", "user_id")
            if isinstance(key, tuple):
                existing = next(
                    (item for item in rows if all(item.get(k) == row.get(k) for k in key)),
                    None,
                )
                if existing is not None:
                    existing.update(row)
                else:
                    rows.append(row)
            else:
                for index, item in enumerate(rows):
                    if item.get(key) == row.get(key):
                        rows[index] = row
                        break
                else:
                    rows.append(row)
            return FakeTournamentResponse([])
        if self.mode == "update":
            for row in rows:
                if all(
                    row.get(column) == value
                    for column, _, value in self.filters
                    if _ == "eq"
                ):
                    row.update(self.payload)
            return FakeTournamentResponse([])

        selected = []
        for row in rows:
            yes = True
            for column, operation, value in self.filters:
                current = row.get(column)
                if operation == "eq" and current != value:
                    yes = False
                elif operation == "gte" and str(current or "") < str(value):
                    yes = False
                elif operation == "lte" and str(current or "") > str(value):
                    yes = False
            if yes:
                selected.append(dict(row))
        if self.order_value:
            column, desc = self.order_value
            selected.sort(key=lambda item: str(item.get(column) or ""), reverse=desc)
        if self.range_value:
            start, end = self.range_value
            selected = selected[start : end + 1]
        elif self.limit_value is not None:
            selected = selected[: self.limit_value]
        return FakeTournamentResponse(selected)


class FakeTournamentClient:
    def __init__(self):
        self.tables = {"tournaments": [], "tournament_participants": []}

    def table(self, name):
        return FakeTournamentQuery(self, name)


class TournamentPersistenceTest(TournamentTestBase):
    def test_supabase_roundtrip_capacity_admin_and_start(self) -> None:
        from core.tournaments import (
            ACTIVE,
            TournamentFullError,
            TournamentStore,
            set_tournament_store,
        )

        client = FakeTournamentClient()
        shop = get_shop_store()
        store = TournamentStore(economy=self.economy, shop=shop, client=client)
        set_tournament_store(store)
        start = datetime.now(timezone.utc) + timedelta(days=2)
        tournament = store.create(
            "bomb", start.isoformat(), prize_pool=500, max_players=2
        )
        self.assertEqual(tournament.max_participants, 2)

        restarted = TournamentStore(economy=self.economy, shop=shop, client=client)
        loaded = restarted.get(tournament.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.game_type, "bomb")
        self.assertEqual(loaded.max_participants, 2)
        self.assertEqual(loaded.start_time, tournament.starts_at)

        self.economy.ensure_user(99001)
        self.economy.ensure_user(99002)
        self.economy.ensure_user(99003)
        restarted.join(99001, tournament.id, "ali", "Ali")
        restarted.join(99002, tournament.id, "vali", "Vali")
        after_join = TournamentStore(economy=self.economy, shop=shop, client=client)
        self.assertTrue(after_join.joined(tournament.id, 99001))
        self.assertEqual(after_join.participant_count(tournament.id), 2)
        with self.assertRaises(TournamentFullError) as full:
            after_join.join(99003, tournament.id, "zilola", "Zilola")
        self.assertIn("Joylar to'ldi", str(full.exception))

        updated = after_join.set_max_participants(tournament.id, 8)
        self.assertEqual(updated.max_participants, 8)
        updated = after_join.set_start_time(tournament.id, "ertaga 21:00")
        self.assertTrue(updated.start_time)
        updated = after_join.set_prize_pool(tournament.id, 750)
        self.assertEqual(updated.prize_pool, 750)
        updated = after_join.set_game(tournament.id, "mafia")
        self.assertEqual(updated.game_type, "mafia")

        started = after_join.start(tournament.id)
        self.assertEqual(started.status, ACTIVE)
        self.assertTrue(started.bracket_data)
        persisted = TournamentStore(economy=self.economy, shop=shop, client=client)
        restored = persisted.get(tournament.id)
        self.assertEqual(restored.status, ACTIVE)
        self.assertTrue(restored.bracket_data)
        payload = persisted.payload(99001)
        card = next(item for item in payload["tournaments"] if item["id"] == tournament.id)
        self.assertTrue(card["joined"])
        self.assertEqual(card["max_participants"], 8)
        self.assertIn("bracket", card)

    def test_registration_status_from_supabase_is_listed_and_leave_works(self) -> None:
        client = FakeTournamentClient()
        start = datetime.now(timezone.utc) + timedelta(days=1)
        client.tables["tournaments"].extend(
            [
                {
                    "id": "reg1",
                    "title": "Portlovchi Bomba Haftalik Turniri",
                    "game_type": "bomb",
                    "game": "bomb",
                    "prize_pool": 5000,
                    "max_participants": 8,
                    "max_players": 8,
                    "status": "registration",
                    "start_time": start.isoformat(),
                    "starts_at": start.isoformat(),
                    "bracket_data": [],
                    "entry_fee": 50,
                    "created_by": 0,
                },
                {
                    "id": "live1",
                    "title": "Boshlangan turnir",
                    "game_type": "mafia",
                    "game": "mafia",
                    "prize_pool": 1000,
                    "max_participants": 8,
                    "max_players": 8,
                    "status": "active",
                    "start_time": (start - timedelta(days=2)).isoformat(),
                    "starts_at": (start - timedelta(days=2)).isoformat(),
                    "bracket_data": [],
                    "entry_fee": 50,
                    "created_by": 0,
                },
            ]
        )
        store = TournamentStore(
            economy=self.economy, shop=get_shop_store(), client=client
        )
        set_tournament_store(store)
        self.addCleanup(set_tournament_store, None)

        visible = [item.id for item in store.visible()]
        self.assertIn("reg1", visible)
        self.assertIn("live1", visible)
        self.assertEqual([item.id for item in store.active()], ["reg1"])
        payload = store.payload(99030)
        self.assertIn("reg1", [item["id"] for item in payload["tournaments"]])

        store.join(99030, "reg1", "ali", "Ali")
        self.assertTrue(store.joined("reg1", 99030))
        self.assertEqual(store.participant_count("reg1"), 1)

        store.leave(99030, "reg1")
        self.assertFalse(store.joined("reg1", 99030))
        self.assertEqual(client.tables["tournament_participants"], [])

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
        self.assertIn(f"join_tournament_{tournament_id}", callbacks)
        self.assertIn("tour_update", callbacks)

    def test_registration_status_renders_join_registered_state_and_webapp(self) -> None:
        from bot.handlers import tournaments as handler

        tournament_id = self.create_tournament()
        self.store._update_tournament(tournament_id, {"status": "registration"})

        text = handler.poster_text(98021)
        self.assertIn("Röyxatga oliş oçiq", text)
        self.assertIn("Bunker Haftalik Turniri", text)
        self.assertIn("Örinlar:", text)
        self.assertIn("Boşlaniş vaqti:", text)

        keyboard = handler.poster_keyboard(
            98021, username="ali", full_name="Ali"
        )
        callbacks = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertIn(f"join_tournament_{tournament_id}", callbacks)
        self.assertIn("tour_update", callbacks)
        self.assertTrue(
            any(
                button.web_app is not None
                and button.web_app.url.startswith("https://")
                for row in keyboard.inline_keyboard
                for button in row
            )
        )

        self.store.join(98021, tournament_id, "ali", "Ali")
        joined_keyboard = handler.poster_keyboard(98021)
        labels = [
            button.text
            for row in joined_keyboard.inline_keyboard
            for button in row
        ]
        joined_callbacks = [
            button.callback_data
            for row in joined_keyboard.inline_keyboard
            for button in row
        ]
        self.assertIn("✅ Siz röyxatdan ötgansiz", labels)
        self.assertIn("❌ Röyxatdan çiqiş", labels)
        self.assertIn(f"leave_tournament_{tournament_id}", joined_callbacks)

    def test_lowercase_active_status_is_visible_but_not_joinable(self) -> None:
        from bot.handlers import tournaments as handler

        tournament_id = self.create_tournament()
        self.store._update_tournament(tournament_id, {"status": "active"})
        text = handler.poster_text(98022)
        self.assertIn("Turnir boşlangan", text)
        keyboard = handler.poster_keyboard(98022)
        labels = [
            button.text for row in keyboard.inline_keyboard for button in row
        ]
        callbacks = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]
        self.assertIn("▶️ Turnir boşlangan", labels)
        self.assertNotIn(f"join_tournament_{tournament_id}", callbacks)

    def test_join_and_leave_callbacks_update_the_store(self) -> None:
        import asyncio
        from types import SimpleNamespace

        from bot.handlers import tournaments as handler

        tournament_id = self.create_tournament()
        user = SimpleNamespace(id=98023, username="ali", full_name="Ali")

        class FakeBot:
            def __init__(self) -> None:
                self.sent: list[str] = []

            async def send_message(self, chat_id, text, reply_markup=None):
                self.sent.append(text)

        class FakeCallback:
            def __init__(self, data: str) -> None:
                self.data = data
                self.from_user = user
                self.bot = FakeBot()
                self.message = None
                self.answers: list[str] = []

            async def answer(self, text: str = "", show_alert: bool = False):
                self.answers.append(text)

        joined = FakeCallback(f"join_tournament_{tournament_id}")
        asyncio.run(handler.tournaments_join(joined))
        self.assertTrue(self.store.joined(tournament_id, 98023))
        self.assertIn("Tabriklaymiz", joined.answers[0])

        left = FakeCallback(f"leave_tournament_{tournament_id}")
        asyncio.run(handler.tournaments_leave(left))
        self.assertFalse(self.store.joined(tournament_id, 98023))
        self.assertIn("çiqdingiz", left.answers[0])
        self.assertEqual(
            handler._join_tournament_id(f"tour_join_{tournament_id}"),
            tournament_id,
        )

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
