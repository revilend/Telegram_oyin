"""Chek yuborish Supabase xatolariga (PGRST204) chidamli ekanini tekshirish."""

from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("ADMIN_ID", "424242")

from bot.handlers import shop
from core.economy import APPROVED, PENDING, REJECTED, START_COINS, EconomyStore


def pgrst204(column: str, table: str = "users") -> Exception:
    exc = Exception(
        f"Could not find the '{column}' column of '{table}' in the schema cache "
        "(code: PGRST204)"
    )
    exc.code = "PGRST204"  # type: ignore[attr-defined]
    return exc


class FakeQuery:
    def __init__(self, client: "FakeClient", table: str, mode: str, payload=None):
        self.client = client
        self.table = table
        self.mode = mode
        self.payload = payload
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
            return SimpleNamespace(data=self.client.select_rows.get(self.table, []))
        rejected = self.client.reject_columns.get(self.table, set())
        rows = self.payload if isinstance(self.payload, list) else [self.payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            for column in rejected:
                if column in row:
                    raise pgrst204(column, self.table)
        if self.table in self.client.fail_tables:
            raise self.client.fail_tables[self.table]
        self.client.writes.append(
            {
                "table": self.table,
                "mode": self.mode,
                "payload": self.payload,
                "filters": list(self.filters),
            }
        )
        return SimpleNamespace(data=[])


class FakeTable:
    def __init__(self, client: "FakeClient", name: str) -> None:
        self.client = client
        self.name = name

    def insert(self, payload, **_kwargs) -> FakeQuery:
        return FakeQuery(self.client, self.name, "insert", payload)

    def upsert(self, payload, **_kwargs) -> FakeQuery:
        return FakeQuery(self.client, self.name, "upsert", payload)

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

    def payloads(self, table: str) -> list[dict]:
        return [
            write["payload"]
            for write in self.writes
            if write["table"] == table
        ]


def user_row(user_id: int, coins: int = START_COINS) -> dict:
    return {
        "telegram_id": user_id,
        "username": "ali",
        "full_name": "Ali Valiyev",
        "coins": coins,
        "total_purchased": 0,
        "games_played": 0,
        "wins": 0,
        "bunker_wins": 0,
        "mafia_wins": 0,
        "referral_count": 0,
        "role": "user",
        "created_at": "2026-01-01T00:00:00+00:00",
    }


class EconomySafeWriteTest(unittest.TestCase):
    def test_user_insert_and_update_never_send_updated_at(self) -> None:
        client = FakeClient()
        store = EconomyStore(client=client)
        store.ensure_user(700, "ali", "Ali")

        insert_row = client.payloads("users")[0]
        self.assertEqual(insert_row["coins"], START_COINS)
        self.assertNotIn("updated_at", insert_row)

        client.select_rows["users"] = [user_row(700)]
        store.ensure_user(700, "vali", "Vali")
        update_row = client.writes[-1]
        self.assertEqual(update_row["mode"], "update")
        self.assertNotIn("updated_at", update_row["payload"])

    def test_user_insert_strips_missing_optional_column(self) -> None:
        client = FakeClient({"users": {"role"}})
        store = EconomyStore(client=client)
        account = store.ensure_user(701, "ali", "Ali")

        self.assertEqual(account.coins, START_COINS)
        sent = client.payloads("users")[0]
        self.assertNotIn("role", sent)
        self.assertEqual(sent["telegram_id"], 701)

    def test_payment_columns_missing_still_saves(self) -> None:
        client = FakeClient({"payment_requests": {"created_at", "updated_at"}})
        store = EconomyStore(client=client)

        payment = store.create_payment(702, "ali", "Ali", 500, "receipt-1")

        sent = client.payloads("payment_requests")[0]
        self.assertNotIn("created_at", sent)
        self.assertNotIn("updated_at", sent)
        self.assertEqual(store.get_payment(payment.id).status, PENDING)

    def test_payment_is_kept_in_memory_when_db_write_fails(self) -> None:
        client = FakeClient(
            select_rows={"users": [user_row(703)]},
            fail_tables={"payment_requests": RuntimeError("baza ishlamayapti")},
        )
        store = EconomyStore(client=client)

        payment = store.create_payment(703, "ali", "Ali", 500, "receipt-2")

        found = store.get_payment(payment.id)
        self.assertIsNotNone(found)
        self.assertEqual(found.receipt_file_id, "receipt-2")
        pending = [item.id for item in store.list_pending_payments()]
        self.assertIn(payment.id, pending)

    def test_promo_code_strips_missing_alias_columns(self) -> None:
        client = FakeClient(
            {"promo_codes": {"reward_coins", "uses", "current_uses"}}
        )
        store = EconomyStore(client=client)

        promo = store.create_promo_code("YANGIYIL", 500, 20)

        self.assertEqual(promo.code, "YANGIYIL")
        self.assertEqual(promo.coins, 500)
        self.assertEqual(promo.max_uses, 20)
        sent = client.payloads("promo_codes")[0]
        self.assertNotIn("reward_coins", sent)
        self.assertNotIn("uses", sent)
        self.assertNotIn("current_uses", sent)
        self.assertEqual(sent["coins"], 500)
        self.assertEqual(sent["max_uses"], 20)

    def test_promo_code_is_created_even_when_db_write_fails(self) -> None:
        client = FakeClient(
            fail_tables={"promo_codes": RuntimeError("baza ishlamayapti")}
        )
        store = EconomyStore(client=client)

        promo = store.create_promo_code("YANGIYIL", 500, 20)

        self.assertEqual(store.get_promo_code("yangiyil").coins, 500)
        redemption = store.redeem_promo_code(704, "YANGIYIL")
        self.assertEqual(redemption.coins, 500)
        self.assertEqual(redemption.account.coins, START_COINS + 500)
        self.assertEqual(store.get_promo_code(promo.code).used_count, 1)

    def test_mission_claim_survives_mission_table_failure(self) -> None:
        client = FakeClient(
            fail_tables={"player_missions": RuntimeError("baza ishlamayapti")}
        )
        store = EconomyStore(client=client)

        account = store.claim_mission_reward(705, "first_game", 50)

        self.assertEqual(account.coins, START_COINS + 50)
        self.assertIn("first_game", store.claimed_missions(705))

    def test_approval_works_even_if_payment_db_write_fails(self) -> None:
        client = FakeClient(
            select_rows={"users": [user_row(704)]},
            fail_tables={"payment_requests": RuntimeError("baza ishlamayapti")},
        )
        store = EconomyStore(client=client)
        payment = store.create_payment(704, "ali", "Ali", 500, "receipt-3")

        approved = store.approve_payment(payment.id, 424242)

        self.assertEqual(approved.status, APPROVED)
        coin_updates = [
            write["payload"].get("coins")
            for write in client.writes
            if write["table"] == "users" and write["mode"] == "update"
        ]
        self.assertIn(START_COINS + 500, coin_updates)

    def test_rejection_works_even_if_payment_db_write_fails(self) -> None:
        client = FakeClient(
            select_rows={"users": [user_row(705)]},
            fail_tables={"payment_requests": RuntimeError("baza ishlamayapti")},
        )
        store = EconomyStore(client=client)
        payment = store.create_payment(705, "ali", "Ali", 500, "receipt-4")

        rejected = store.reject_payment(payment.id, 424242)

        self.assertEqual(rejected.status, REJECTED)


class FakeBot:
    def __init__(self) -> None:
        self.photos: list[dict] = []
        self.documents: list[dict] = []
        self.messages: list[dict] = []

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
        self.photos.append(
            {
                "chat_id": chat_id,
                "photo": photo,
                "caption": caption,
                "reply_markup": reply_markup,
            }
        )

    async def send_document(self, chat_id, document, caption=None, reply_markup=None):
        self.documents.append(
            {
                "chat_id": chat_id,
                "document": document,
                "caption": caption,
                "reply_markup": reply_markup,
            }
        )

    async def send_message(self, chat_id, text, reply_markup=None):
        self.messages.append(
            {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        )


class FakeMessage:
    def __init__(self) -> None:
        self.from_user = SimpleNamespace(id=706, username="ali", full_name="Ali Valiyev")
        self.chat = SimpleNamespace(id=706, type="private")
        self.photo = [SimpleNamespace(file_id="receipt-photo")]
        self.document = None
        self.bot = FakeBot()
        self.answers: list[str] = []

    async def answer(self, text: str, **_kwargs) -> None:
        self.answers.append(text)


class FakeState:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.cleared = False

    async def get_data(self) -> dict:
        return dict(self.data)

    async def clear(self) -> None:
        self.cleared = True


class ReceiptHandlerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SimpleNamespace(
            admin_id=424242,
            bot_username="revilend_gamesbot",
            mini_app_url="https://revilend.games",
        )
        self.config_patch = patch.object(shop, "get_config", return_value=self.config)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)

    def test_receipt_reaches_admin_when_columns_are_missing(self) -> None:
        client = FakeClient(
            {
                "users": {"updated_at"},
                "payment_requests": {"updated_at", "created_at"},
            },
            select_rows={"users": [user_row(706)]},
        )
        store = EconomyStore(client=client)
        message = FakeMessage()
        state = FakeState({"package_coins": 500})

        with patch.object(shop, "get_economy", return_value=store):
            asyncio.run(shop.receipt_file(message, state))

        self.assertTrue(state.cleared)
        self.assertIn("qabul qilindi", message.answers[0])
        self.assertNotIn("PGRST204", " ".join(message.answers))

        self.assertEqual(len(message.bot.photos), 1)
        photo = message.bot.photos[0]
        self.assertEqual(photo["chat_id"], 424242)
        self.assertEqual(photo["photo"], "receipt-photo")
        self.assertIn("Yangi tölov çeki", photo["caption"])
        buttons = photo["reply_markup"].inline_keyboard[0]
        self.assertEqual(buttons[0].text, "✅ Tasdiqlaş")
        self.assertEqual(buttons[1].text, "❌ Rad etiş")
        self.assertTrue(buttons[0].callback_data.startswith("pay_ok_"))

    def test_receipt_is_saved_when_payment_table_write_fails(self) -> None:
        client = FakeClient(
            select_rows={"users": [user_row(707)]},
            fail_tables={"payment_requests": RuntimeError("baza ishlamayapti")},
        )
        store = EconomyStore(client=client)
        message = FakeMessage()
        state = FakeState({"package_coins": 1500})

        with patch.object(shop, "get_economy", return_value=store):
            asyncio.run(shop.receipt_file(message, state))

        self.assertIn("qabul qilindi", message.answers[0])
        self.assertEqual(len(message.bot.photos), 1)
        stored = store.list_pending_payments()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].package_coins, 1500)

    def test_technical_error_is_not_shown_to_user(self) -> None:
        store = SimpleNamespace(
            create_payment=lambda **_kwargs: (_ for _ in ()).throw(
                pgrst204("updated_at", "payment_requests")
            )
        )
        message = FakeMessage()
        state = FakeState({"package_coins": 500})

        with patch.object(shop, "get_economy", return_value=store):
            asyncio.run(shop.receipt_file(message, state))

        answer = message.answers[0]
        self.assertNotIn("PGRST204", answer)
        self.assertNotIn("updated_at", answer)
        self.assertIn("vaqtinça xatolik", answer)


if __name__ == "__main__":
    unittest.main()
