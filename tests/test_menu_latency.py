"""Menyu tugmalari va /start uchun 0.5 sekundlik byudjet testi.

Supabase so'rovlari 100 ms kechikish bilan simulyatsiya qilinadi, shuning uchun
5 tadan ortiq ketma-ket so'rov byudjetdan chiqib ketadi. Test ikki narsani
qo'riqlaydi:

* foydalanuvchi javobni (birinchi xabarni) 0.5 sekund ichida oladi;
* so'rovlar soni kutilgan chegaradan oshmaydi — kesh ishlamay qolsa yiqiladi.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST")

import core.economy as economy_module  # noqa: E402
from bot.config import get_config  # noqa: E402
from bot.handlers import common, leaderboard, missions, profile, shop  # noqa: E402
from core.economy import START_COINS, EconomyStore  # noqa: E402

USER_ID = 850_001
NEW_USER_ID = 850_777
LATENCY = 0.10  # har bir Supabase so'rovi, sekund
BUDGET_MS = 500  # foydalanuvchi kutadigan chegara


# ----------------------------------------------------------------------
# Supabase o'rnini bosuvchi mijoz (so'rovlarni sanaydi)
# ----------------------------------------------------------------------
class _Query:
    def __init__(self, client, table: str, mode: str, payload=None) -> None:
        self._client = client
        self._table = table
        self._mode = mode
        self._payload = payload
        self._filters: list[tuple[str, object]] = []

    def eq(self, column: str, value: object):
        self._filters.append((column, value))
        return self

    def limit(self, _count: int):
        return self

    def select(self, *_args):
        self._mode = "select"
        return self

    # Boshqa zanjir usullari o'lchovga ta'sir qilmaydi.
    def order(self, *_args, **_kwargs):
        return self

    def range(self, *_args):
        return self

    def execute(self):
        time.sleep(LATENCY)
        self._client.queries += 1
        if self._mode == "select":
            rows = [
                dict(row)
                for row in self._client.rows.get(self._table, [])
                if all(row.get(column) == value for column, value in self._filters)
            ]
            return SimpleNamespace(data=rows)
        if self._table == "users" and self._mode == "update":
            for row in self._client.rows.get("users", []):
                if all(row.get(c) == v for c, v in self._filters):
                    row.update(self._payload or {})
        elif self._table == "users" and self._mode == "insert":
            self._client.rows.setdefault("users", []).append(dict(self._payload or {}))
        elif self._mode == "delete":
            self._client.rows[self._table] = [
                row
                for row in self._client.rows.get(self._table, [])
                if not all(row.get(c) == v for c, v in self._filters)
            ]
        return SimpleNamespace(data=[])


class _Table:
    def __init__(self, client, name: str) -> None:
        self._client = client
        self._name = name

    def insert(self, payload, **_kwargs):
        return _Query(self._client, self._name, "insert", payload)

    def upsert(self, payload, **_kwargs):
        return _Query(self._client, self._name, "upsert", payload)

    def update(self, payload):
        return _Query(self._client, self._name, "update", payload)

    def select(self, *_args):
        return _Query(self._client, self._name, "select")

    def delete(self, **_kwargs):
        return _Query(self._client, self._name, "delete")


class FakeClient:
    def __init__(self, rows: dict[str, list[dict]]) -> None:
        self.rows = rows
        self.queries = 0

    def table(self, name: str) -> _Table:
        return _Table(self, name)


def user_row(user_id: int = USER_ID) -> dict:
    return {
        "telegram_id": user_id,
        "username": f"bench{user_id}",
        "full_name": "Bench User",
        "coins": 250,
        "total_purchased": 0,
        "games_played": 0,
        "wins": 0,
        "bunker_wins": 0,
        "mafia_wins": 0,
        "spy_wins": 0,
        "alias_wins": 0,
        "bomb_wins": 0,
        "referral_count": 0,
        "role": "user",
        "is_blocked": False,
        "block_reason": "",
        "is_bot": False,
        "language_code": "uz",
    }


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **_kwargs) -> None:
        self.messages.append((chat_id, text))


class FakeMessage:
    """Handler kutadigan minimal xabar; birinchi javob vaqtini yozadi."""

    def __init__(self, user_id: int) -> None:
        self.from_user = SimpleNamespace(
            id=user_id,
            username=f"bench{user_id}",
            full_name="Bench User",
            language_code="uz",
        )
        self.chat = SimpleNamespace(id=user_id, type="private")
        self.bot = FakeBot()
        self.answers: list[str] = []
        self.started_at = time.perf_counter()
        self.first_answer_at: float | None = None

    async def answer(self, text: str, **_kwargs) -> None:
        if self.first_answer_at is None:
            self.first_answer_at = time.perf_counter()
        self.answers.append(text)

    async def reply(self, text: str, **kwargs) -> None:
        await self.answer(text, **kwargs)


# ----------------------------------------------------------------------
# Ssenariylar: (nom, handler, sovuq kesh byudjeti, kesh bilan byudjet)
# ----------------------------------------------------------------------
MENU_SCENARIOS = (
    ("/start", lambda message: common.start_command(message, None), 1, 0),
    ("Profilim", profile.show_profile, 1, 0),
    ("Do'kon", shop.send_shop, 1, 0),
    ("Missiyalar", missions.show_missions, 3, 3),
    ("Reyting", leaderboard.show_leaderboard, 3, 2),
)


class MenuLatencyBudgetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient({"users": [user_row()]})
        self.store = EconomyStore(client=self.client)
        # ADMIN_ID boshqa testlardan meros qolmasin: admin bildirishnomasi
        # yoqilgan holat har doim bir xil o'lchansin.
        env = patch.dict(os.environ, {"ADMIN_ID": "424242"})
        env.start()
        self.addCleanup(env.stop)
        get_config.cache_clear()
        self.addCleanup(get_config.cache_clear)

        # Handlerlar ``get_economy`` ni modul darajasida import qiladi;
        # ``core.i18n.resolve_language`` esa chaqiruv paytida import qiladi.
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(
            patch.object(economy_module, "get_economy", return_value=self.store)
        )
        for name, module in list(sys.modules.items()):
            if not name.startswith("bot.handlers."):
                continue
            if hasattr(module, "get_economy"):
                self.stack.enter_context(
                    patch.object(module, "get_economy", return_value=self.store)
                )

    def _measure(self, handler, *, user_id: int = USER_ID, reset: bool = False, args=None):
        if reset:
            self.store.invalidate_user(user_id)
        message = FakeMessage(user_id)
        before = self.client.queries
        started = time.perf_counter()

        async def run() -> None:
            if args is None:
                await handler(message)
            else:
                await handler(message, args)
            # Fon vazifalari (taklif/admin) ham o'lchovga kirsin.
            await common.flush_background_tasks()

        asyncio.run(run())
        elapsed = (time.perf_counter() - started) * 1000
        first = ((message.first_answer_at or time.perf_counter()) - started) * 1000
        return elapsed, first, self.client.queries - before, message

    # ------------------------------------------------------------------
    # 0.5 sekundlik byudjet
    # ------------------------------------------------------------------
    def test_first_answer_fits_budget_with_empty_cache(self) -> None:
        for label, handler, _cold, _warm in MENU_SCENARIOS:
            with self.subTest(scenario=label):
                elapsed, first, _queries, _message = self._measure(
                    handler, reset=True
                )
                self.assertLess(
                    first,
                    BUDGET_MS,
                    f"{label}: birinchi javob {first:.0f} ms "
                    f"(byudjet {BUDGET_MS} ms), jami {elapsed:.0f} ms",
                )

    def test_first_answer_fits_budget_with_warm_cache(self) -> None:
        for label, handler, _cold, _warm in MENU_SCENARIOS:
            with self.subTest(scenario=label):
                self._measure(handler, reset=True)  # keshni to'ldiradi
                elapsed, first, _queries, _message = self._measure(handler)
                self.assertLess(
                    first,
                    BUDGET_MS,
                    f"{label}: kesh bilan birinchi javob {first:.0f} ms "
                    f"(byudjet {BUDGET_MS} ms), jami {elapsed:.0f} ms",
                )

    # ------------------------------------------------------------------
    # So'rovlar soni byudjeti (regressiya qo'riqchisi)
    # ------------------------------------------------------------------
    def test_query_budget_does_not_grow_with_empty_cache(self) -> None:
        for label, handler, cold_budget, _warm in MENU_SCENARIOS:
            with self.subTest(scenario=label):
                _elapsed, _first, queries, _message = self._measure(
                    handler, reset=True
                )
                self.assertLessEqual(
                    queries,
                    cold_budget,
                    f"{label}: sovuq keshda {queries} so'rov "
                    f"(byudjet {cold_budget}) — yangi Supabase chaqiruvi qo'shilgan",
                )

    def test_query_budget_does_not_grow_with_cache(self) -> None:
        for label, handler, _cold, warm_budget in MENU_SCENARIOS:
            with self.subTest(scenario=label):
                self._measure(handler, reset=True)
                _elapsed, _first, queries, _message = self._measure(handler)
                self.assertLessEqual(
                    queries,
                    warm_budget,
                    f"{label}: kesh bilan {queries} so'rov "
                    f"(byudjet {warm_budget}) — kesh ishlamayapti",
                )

    # ------------------------------------------------------------------
    # Yangi foydalanuvchi + taklif havolasi
    # ------------------------------------------------------------------
    def test_new_user_with_referral_gets_welcome_within_budget(self) -> None:
        command = SimpleNamespace(args=f"ref_{USER_ID}")

        def handler(message):
            return common.start_command(message, command)

        _elapsed, first, queries, message = self._measure(
            handler, user_id=NEW_USER_ID
        )
        self.assertTrue(message.answers, "xush kelibsiz xabari yuborilmagan")
        self.assertLess(
            first,
            BUDGET_MS,
            f"yangi foydalanuvchi xush kelibsiz xabari {first:.0f} ms "
            f"(byudjet {BUDGET_MS} ms)",
        )
        # 1 hisob yaratish + 3 taklif yozuvi + 2 admin bildirishnomasi
        # (foydalanuvchi soni va taklif qiluvchi) + 2 zaxira.
        self.assertLessEqual(
            queries,
            8,
            f"yangi foydalanuvchi + taklif: {queries} so'rov (byudjet 8)",
        )
        self.assertEqual(self.store.find_user(NEW_USER_ID).coins, START_COINS)

    # ------------------------------------------------------------------
    # O'lchov asbobi haqiqatan ishlayotganiga ishonch
    # ------------------------------------------------------------------
    def test_query_counter_counts_real_requests(self) -> None:
        self.client.queries = 0
        self.store.add_coins(USER_ID, 5)
        self.assertGreaterEqual(
            self.client.queries, 2, "so'rovlar sanagichi ishlamayapti"
        )


if __name__ == "__main__":
    unittest.main()
