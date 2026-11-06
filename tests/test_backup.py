"""Baza zaxirasi (backup/restore) va kunlik avtomatik zaxira testlari."""

from __future__ import annotations

import asyncio
import io
import json
import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("ADMIN_ID", "424242")
os.environ.setdefault("MINI_APP_URL", "https://revilend.games")
os.environ.setdefault("BOT_USERNAME", "revilend_gamesbot")

from bot.config import get_config
from bot.handlers import admin
from core import daily_backup
from core.backup import (
    BackupError,
    BackupStore,
    auto_backup_filename,
    backup_caption,
    backup_filename,
    dumps_backup,
    restore_caption,
)

TASHKENT = ZoneInfo("Asia/Tashkent")


class FakeTableError(Exception):
    """PostgREST uslubidagi «jadval yo'q» xatosi."""

    def __init__(self, message: str, code: str = "PGRST205") -> None:
        super().__init__(message)
        self.code = code


class FakeQuery:
    def __init__(self, client: "FakeClient", table: str) -> None:
        self.client = client
        self.table = table
        self._range: tuple[int, int] | None = None
        self._upsert: tuple[object, str | None] | None = None

    def select(self, *_columns: str) -> "FakeQuery":
        return self

    def range(self, start: int, end: int) -> "FakeQuery":
        self._range = (start, end)
        return self

    def upsert(self, rows: object, on_conflict: str | None = None) -> "FakeQuery":
        self._upsert = (rows, on_conflict)
        return self

    def execute(self) -> SimpleNamespace:
        if self.table in self.client.missing:
            raise FakeTableError(
                f"Could not find the table 'public.{self.table}' in the schema cache"
            )
        if self._upsert is not None:
            rows, on_conflict = self._upsert
            self.client.upserts.append((self.table, rows, on_conflict))
            return SimpleNamespace(data=rows)
        rows = list(self.client.rows.get(self.table, []))
        if self._range is not None:
            start, end = self._range
            rows = rows[start : end + 1]
        return SimpleNamespace(data=rows)


class FakeClient:
    def __init__(
        self,
        rows: dict[str, list[dict]] | None = None,
        missing: tuple[str, ...] = (),
    ) -> None:
        self.rows = rows or {}
        self.missing = set(missing)
        self.upserts: list[tuple[str, object, str | None]] = []
        self.reads: list[str] = []

    def table(self, name: str) -> FakeQuery:
        self.reads.append(name)
        return FakeQuery(self, name)


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, object]] = []
        self.documents: list[tuple[int, object, str]] = []

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        self.messages.append((chat_id, text, kwargs.get("reply_markup")))

    async def send_document(self, chat_id: int, document, caption: str = "", **_kwargs) -> None:
        self.documents.append((chat_id, document, caption))

    async def download(self, document) -> io.BytesIO:
        return io.BytesIO(document.payload)


class FakeCallback:
    def __init__(self, user_id: int = 424242, data: str = "") -> None:
        self.from_user = SimpleNamespace(id=user_id, username="admin", full_name="Admin")
        self.data = data
        self.bot = FakeBot()
        self.answers: list[str] = []

    async def answer(self, text: str = "", **_kwargs) -> None:
        self.answers.append(text)


class FakeState:
    def __init__(self) -> None:
        self.state = None

    async def set_state(self, state) -> None:
        self.state = state

    async def clear(self) -> None:
        self.state = None


class FakeDocument:
    def __init__(self, payload: bytes, name: str = "backup.json", size: int = 0) -> None:
        self.payload = payload
        self.file_name = name
        self.file_size = size or len(payload)


class FakeMessage:
    def __init__(
        self, user_id: int = 424242, text: str = "", document=None
    ) -> None:
        self.from_user = SimpleNamespace(id=user_id, username="admin", full_name="Admin")
        self.chat = SimpleNamespace(id=user_id, type="private")
        self.text = text
        self.document = document
        self.bot = FakeBot()
        self.answers: list[str] = []
        self.markups: list[object] = []

    async def answer(self, text: str, **kwargs) -> None:
        self.answers.append(text)
        self.markups.append(kwargs.get("reply_markup"))


def sample_payload() -> dict:
    return {
        "version": 1,
        "app": "Revilend Games",
        "created_at": "2026-11-06T19:00:00+00:00",
        "created_at_tashkent": "2026-11-07T00:00:00+05:00",
        "tables": {
            "users": [
                {"telegram_id": 1, "username": "ali", "coins": 10},
                {"telegram_id": 2, "username": "vali", "coins": 20},
            ],
            "rooms": [{"code": "BNK1", "host_id": 1}],
        },
        "counts": {"users": 2, "rooms": 1},
        "skipped": [],
    }


class BackendUnavailableTest(unittest.TestCase):
    def test_backup_requires_supabase(self) -> None:
        store = BackupStore(url="", key="")
        with self.assertRaises(BackupError):
            store.create_backup()
        with self.assertRaises(BackupError):
            store.restore(sample_payload())


class BackupShapeTest(unittest.TestCase):
    def test_filenames_use_tashkent_time(self) -> None:
        moment = datetime(2026, 11, 6, 19, 5, tzinfo=timezone.utc)
        self.assertEqual(backup_filename(moment), "backup_revilend_2026_11_07_0005.json")
        self.assertEqual(auto_backup_filename(moment), "backup_avto_2026_11_07.json")

    def test_create_backup_collects_rows_and_skips_missing_tables(self) -> None:
        client = FakeClient(
            rows={"users": sample_payload()["tables"]["users"], "rooms": []},
            missing=("bomb_cards",),
        )
        store = BackupStore(client=client)
        payload = store.create_backup(tables=["users", "rooms", "bomb_cards"])

        self.assertEqual(payload["app"], "Revilend Games")
        self.assertEqual(payload["counts"], {"users": 2, "rooms": 0})
        self.assertEqual(payload["skipped"], ["bomb_cards"])
        self.assertEqual(payload["tables"]["users"][0]["username"], "ali")
        self.assertTrue(payload["created_at_tashkent"].endswith("+05:00"))

    def test_fetch_table_paginates(self) -> None:
        rows = [{"telegram_id": index} for index in range(2500)]
        store = BackupStore(client=FakeClient(rows={"users": rows}))
        fetched = store.fetch_table("users")
        self.assertEqual(len(fetched), 2500)
        self.assertEqual(fetched[-1]["telegram_id"], 2499)

    def test_dumps_backup_is_readable_json(self) -> None:
        data = json.loads(dumps_backup(sample_payload()).decode("utf-8"))
        self.assertEqual(data["counts"]["users"], 2)

    def test_captions_report_counts(self) -> None:
        caption = backup_caption(sample_payload(), filename="backup.json")
        self.assertIn("Bazadan nusxa olindi", caption)
        self.assertIn("backup.json", caption)
        self.assertIn("<b>2</b>", caption)
        self.assertIn("2026-11-07 00:00", caption)

        restored = restore_caption({"restored": {"users": 2}, "skipped": ["bomb_cards"]})
        self.assertIn("Baza tiklandi", restored)
        self.assertIn("<b>2</b>", restored)
        self.assertIn("bomb_cards", restored)


class RestoreTest(unittest.TestCase):
    def test_restore_upserts_with_primary_keys(self) -> None:
        client = FakeClient()
        store = BackupStore(client=client)
        result = store.restore(sample_payload())

        self.assertEqual(result["restored"], {"users": 2, "rooms": 1})
        conflicts = {table: conflict for table, _rows, conflict in client.upserts}
        self.assertEqual(conflicts["users"], "telegram_id")
        self.assertEqual(conflicts["rooms"], "code")

    def test_restore_chunks_large_tables(self) -> None:
        client = FakeClient()
        store = BackupStore(client=client)
        payload = {
            "app": "Revilend Games",
            "tables": {"users": [{"telegram_id": index} for index in range(250)]},
        }
        result = store.restore(payload)

        self.assertEqual(result["restored"]["users"], 250)
        user_upserts = [rows for table, rows, _ in client.upserts if table == "users"]
        self.assertEqual([len(rows) for rows in user_upserts], [100, 100, 50])

    def test_restore_skips_unknown_and_missing_tables(self) -> None:
        client = FakeClient(missing=("bomb_cards",))
        store = BackupStore(client=client)
        payload = {
            "app": "Revilend Games",
            "tables": {"not_a_table": [{"id": 1}], "bomb_cards": [{"id": 1}]},
        }
        result = store.restore(payload)
        self.assertEqual(result["restored"], {})
        self.assertEqual(sorted(result["skipped"]), ["bomb_cards", "not_a_table"])

    def test_restore_rejects_invalid_payloads(self) -> None:
        store = BackupStore(client=FakeClient())
        with self.assertRaises(BackupError):
            store.restore(SimpleNamespace(tables={}))  # type: ignore[arg-type]
        with self.assertRaises(BackupError):
            store.restore({"tables": []})
        with self.assertRaises(BackupError):
            store.restore({"tables": {"users": "nope"}})
        with self.assertRaises(BackupError):
            store.restore({"app": "Boshqa o'yin", "tables": {"users": []}})


class DailyBackupTest(unittest.TestCase):
    def test_next_run_is_midnight_tashkent(self) -> None:
        moment = datetime(2026, 11, 6, 23, 0, tzinfo=TASHKENT)
        self.assertEqual(daily_backup.next_run_at(moment).date().isoformat(), "2026-11-07")
        self.assertEqual(daily_backup.next_run_at(moment).hour, 0)
        self.assertAlmostEqual(daily_backup.seconds_until_next_run(moment), 3600, delta=1)

    def test_midnight_rolls_to_next_day(self) -> None:
        moment = datetime(2026, 11, 7, 0, 0, tzinfo=TASHKENT)
        self.assertEqual(daily_backup.next_run_at(moment).date().isoformat(), "2026-11-08")

    def test_daily_message_text(self) -> None:
        moment = datetime(2026, 11, 6, 19, 0, tzinfo=timezone.utc)  # 00:00 Tashkent
        text = daily_backup.daily_backup_text(moment)
        self.assertIn("Kunlik Baza Zaxirasi", text)
        self.assertIn("Sana: 2026-11-07 00:00 (Toshkent vaqti)", text)
        self.assertIn("Muvaffaqiyatli saqlandi va yuborildi", text)

    def test_send_daily_backup_sends_json_document(self) -> None:
        store = SimpleNamespace(create_backup=lambda **_: sample_payload())
        bot = FakeBot()
        moment = datetime(2026, 11, 6, 19, 0, tzinfo=timezone.utc)
        with patch.object(daily_backup, "get_backup_store", return_value=store):
            asyncio.run(daily_backup.send_daily_backup(bot, 424242, now=moment))

        chat_id, document, caption = bot.documents[0]
        self.assertEqual(chat_id, 424242)
        self.assertEqual(document.filename, "backup_avto_2026_11_07.json")
        self.assertIn("Sana: 2026-11-07 00:00", caption)
        self.assertEqual(json.loads(document.data.decode("utf-8"))["app"], "Revilend Games")

    def test_send_daily_backup_needs_admin_chat(self) -> None:
        with self.assertRaises(BackupError):
            asyncio.run(daily_backup.send_daily_backup(FakeBot(), 0))

    def test_start_without_admin_returns_none(self) -> None:
        self.assertIsNone(daily_backup.start_daily_backup(FakeBot(), 0))

    def test_scheduler_registers_midnight_cron_job(self) -> None:
        async def scenario() -> None:
            scheduler = daily_backup.start_daily_backup(FakeBot(), 424242)
            try:
                self.assertIsNotNone(scheduler)
                job = scheduler.get_job("daily-backup")
                self.assertIsNotNone(job)
                self.assertIn("hour='0'", str(job.trigger))
                self.assertIn("minute='0'", str(job.trigger))
                self.assertEqual(job.next_run_time.hour, 0)
                self.assertEqual(job.next_run_time.minute, 0)
                self.assertEqual(str(job.next_run_time.tzinfo), "Asia/Tashkent")
            finally:
                daily_backup.stop_daily_backup(scheduler)

        asyncio.run(scenario())


class AdminBackupUiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "BOT_TOKEN": "123456:TEST",
                "ADMIN_ID": "424242",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_KEY": "test-key",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        get_config.cache_clear()
        self.addCleanup(get_config.cache_clear)

    def test_backup_button_sends_json_file(self) -> None:
        store = SimpleNamespace(create_backup=lambda **_: sample_payload())
        callback = FakeCallback()
        with patch.object(admin, "get_backup_store", return_value=store):
            asyncio.run(admin.send_backup(callback))

        chat_id, document, caption = callback.bot.documents[0]
        self.assertEqual(chat_id, 424242)
        self.assertTrue(document.filename.startswith("backup_revilend_"))
        self.assertTrue(document.filename.endswith(".json"))
        self.assertIn("Bazadan nusxa olindi", caption)
        self.assertEqual(json.loads(document.data.decode("utf-8"))["counts"]["users"], 2)

    def test_backup_reports_missing_supabase(self) -> None:
        store = SimpleNamespace(
            create_backup=lambda **_: (_ for _ in ()).throw(BackupError("Supabase sozlanmagan"))
        )
        callback = FakeCallback()
        with patch.object(admin, "get_backup_store", return_value=store):
            asyncio.run(admin.send_backup(callback))
        self.assertIn("Supabase sozlanmagan", callback.bot.messages[-1][1])

    def test_restore_is_root_admin_only(self) -> None:
        state = FakeState()
        callback = FakeCallback(user_id=777)  # role admin bo'lsa ham ADMIN_ID emas
        with patch.object(admin, "is_admin", return_value=True):
            asyncio.run(admin.ask_restore(callback, state))
        self.assertIsNone(state.state)
        self.assertIn("faqat boş admin", callback.answers[-1])

    def test_restore_flow_accepts_json_document(self) -> None:
        state = FakeState()
        asyncio.run(admin.ask_restore(FakeCallback(), state))
        self.assertIs(state.state, admin.AdminStates.waiting_restore)

        document = FakeDocument(json.dumps(sample_payload()).encode("utf-8"))
        message = FakeMessage(document=document)
        store = SimpleNamespace(
            restore=lambda payload: {"restored": {"users": 2}, "skipped": []}
        )
        with patch.object(admin, "get_backup_store", return_value=store):
            asyncio.run(admin.restore_from_file(message, state))

        self.assertIsNone(state.state)
        self.assertIn("Baza tiklandi", message.answers[-1])

    def test_restore_rejects_non_json_file(self) -> None:
        state = FakeState()
        asyncio.run(admin.ask_restore(FakeCallback(), state))
        message = FakeMessage(document=FakeDocument(b"data", name="backup.txt"))
        asyncio.run(admin.restore_from_file(message, state))
        self.assertIn("Faqat <code>.json</code>", message.answers[-1])
        self.assertIs(state.state, admin.AdminStates.waiting_restore)

    def test_restore_rejects_corrupt_json(self) -> None:
        state = FakeState()
        asyncio.run(admin.ask_restore(FakeCallback(), state))
        message = FakeMessage(document=FakeDocument(b"{not json"))
        asyncio.run(admin.restore_from_file(message, state))
        self.assertIn("yaroqli JSON", message.answers[-1])
        self.assertIs(state.state, admin.AdminStates.waiting_restore)

    def test_restore_denied_for_other_admins(self) -> None:
        state = FakeState()
        message = FakeMessage(user_id=777, document=FakeDocument(b"{}"))
        asyncio.run(admin.restore_from_file(message, state))
        self.assertIn("faqat administrator", message.answers[-1])
        self.assertIsNone(state.state)


if __name__ == "__main__":
    unittest.main()
