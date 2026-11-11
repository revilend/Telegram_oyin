#!/usr/bin/env python3
"""Bot javob tezligini haqiqiy Supabase bilan o'lchaydi.

Skript Telegram'ga xabar yubormaydi: handlerlar ``FakeMessage`` bilan
chaqiriladi, shuning uchun o'lchov **baza + handler mantiqi** vaqtini
ko'rsatadi (Telegram tarmoq vaqti kirmaydi). Har bir so'rovning vaqti va
soni Supabase mijozi ustidagi yengil o'ram bilan sanaladi.

Ishlatish::

    python scripts/bench_latency.py --user-id 123456789
    python scripts/bench_latency.py --user-id 123456789 --runs 10 --json bench.json
    python scripts/bench_latency.py --allow-write --inviter-id 123456789
    python scripts/bench_latency.py --simulate   # credentialsiz sinov

``.env`` faylidagi ``SUPABASE_URL`` va ``SUPABASE_SERVICE_ROLE_KEY``
(o'rniga ``SUPABASE_KEY``) ishlatiladi.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack
import json
import logging
import os
import random
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Handlerlar konfiguratsiyani talab qiladi; o'lchov uchun xavfsiz standartlar.
os.environ.setdefault("BOT_TOKEN", "000000:BENCH")
os.environ.setdefault("ADMIN_ID", "0")

from bot.handlers import (  # noqa: E402  (env'dan keyin import qilinadi)
    common,
    leaderboard,
    missions,
    profile,
    shop,
)
from core.economy import EconomyStore  # noqa: E402

LOG = logging.getLogger("bench")


# ----------------------------------------------------------------------
# Telegram o'rnini bosuvchi obyektlar
# ----------------------------------------------------------------------
class FakeBot:
    """Xabar yuborishni o'lchovdan chiqarib tashlaydi."""

    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **_kwargs) -> None:
        self.messages.append((chat_id, text))


class FakeMessage:
    """Handler kutadigan minimal xabar; birinchi javob vaqtini yozadi."""

    def __init__(self, user_id: int, language_code: str = "uz") -> None:
        self.from_user = SimpleNamespace(
            id=user_id,
            username=f"bench{user_id}",
            full_name="Bench User",
            language_code=language_code,
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
# Supabase so'rovlarini sanash
# ----------------------------------------------------------------------
class _CountingQuery:
    def __init__(self, owner: "_CountingClient", query) -> None:
        self._owner = owner
        self._query = query

    def __getattr__(self, name: str):
        attr = getattr(self._query, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            if name == "execute":
                started = time.perf_counter()
                try:
                    return attr(*args, **kwargs)
                finally:
                    self._owner.queries += 1
                    self._owner.db_seconds += time.perf_counter() - started
            result = attr(*args, **kwargs)
            if hasattr(result, "execute"):
                return _CountingQuery(self._owner, result)
            return result

        return call


class _CountingTable:
    def __init__(self, owner: "_CountingClient", table) -> None:
        self._owner = owner
        self._table = table

    def __getattr__(self, name: str):
        attr = getattr(self._table, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            return _CountingQuery(self._owner, attr(*args, **kwargs))

        return call


class _CountingClient:
    """Haqiqiy Supabase mijozini o'rab, so'rovlar soni va vaqtini sanaydi."""

    def __init__(self, client) -> None:
        self._client = client
        self.queries = 0
        self.db_seconds = 0.0

    def table(self, name: str) -> _CountingTable:
        return _CountingTable(self, self._client.table(name))


# ----------------------------------------------------------------------
# Credentialsiz sinov uchun soxta mijoz
# ----------------------------------------------------------------------
class _SimQuery:
    def __init__(self, client, table, mode, payload=None) -> None:
        self._client = client
        self._table = table
        self._mode = mode
        self._payload = payload
        self._filters: list[tuple[str, object]] = []

    def eq(self, column: str, value: object):
        self._filters.append((column, value))
        return self

    def gte(self, column: str, value: object):
        self._filters.append((column, value))
        return self

    def lte(self, column: str, value: object):
        self._filters.append((column, value))
        return self

    def lt(self, column: str, value: object):
        self._filters.append((column, value))
        return self

    def gt(self, column: str, value: object):
        self._filters.append((column, value))
        return self

    def in_(self, _column: str, _values):
        return self

    def is_(self, _column: str, _value):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _count: int):
        return self

    def select(self, *_args):
        self._mode = "select"
        return self

    def execute(self):
        time.sleep(self._client.latency)
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
        return SimpleNamespace(data=[])


class _SimTable:
    def __init__(self, client, name: str) -> None:
        self._client = client
        self._name = name

    def insert(self, payload, **_kwargs):
        return _SimQuery(self._client, self._name, "insert", payload)

    def upsert(self, payload, **_kwargs):
        return _SimQuery(self._client, self._name, "upsert", payload)

    def update(self, payload):
        return _SimQuery(self._client, self._name, "update", payload)

    def select(self, *_args):
        return _SimQuery(self._client, self._name, "select")

    def delete(self, **_kwargs):
        return _SimQuery(self._client, self._name, "delete")


class _SimClient:
    """``--simulate`` uchun mijoz: har so'rov ``latency`` sekund kutadi."""

    def __init__(self, latency: float, user_id: int) -> None:
        self.latency = latency
        self.rows = {"users": [_user_row(user_id)], "referrals": []}

    def table(self, name: str) -> _SimTable:
        return _SimTable(self, name)


def _user_row(user_id: int) -> dict:
    return {
        "telegram_id": user_id,
        "username": f"bench{user_id}",
        "full_name": "Bench User",
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
        "role": "user",
        "is_blocked": False,
        "block_reason": "",
        "is_bot": False,
        "language_code": "uz",
    }


# ----------------------------------------------------------------------
# O'lchov
# ----------------------------------------------------------------------
class Bench:
    """Bitta ssenariyni bir necha marta o'lchab, statistikani yig'adi."""

    def __init__(self, store: EconomyStore, counter: _CountingClient, user_id: int) -> None:
        self.store = store
        self.counter = counter
        self.user_id = user_id
        self.results: list[dict] = []

    def _one(self, coro_factory) -> tuple[float, float, int]:
        message = FakeMessage(self.user_id)
        before = self.counter.queries
        started = time.perf_counter()
        asyncio.run(coro_factory(message))
        total_ms = (time.perf_counter() - started) * 1000
        stamp = message.first_answer_at or time.perf_counter()
        first_ms = (stamp - started) * 1000
        return total_ms, first_ms, self.counter.queries - before

    def run_http(
        self,
        label: str,
        request_fn,
        runs: int,
        *,
        reset=None,
    ) -> dict | None:
        """Mini App endpointini (in-process ASGI) o'lchaydi."""
        samples: list[float] = []
        queries: list[int] = []
        for index in range(runs):
            if reset is not None:
                reset()
            before = self.counter.queries
            started = time.perf_counter()
            try:
                response = request_fn()
            except Exception:
                LOG.exception("%s: run %d xato bilan tugadi", label, index + 1)
                continue
            total_ms = (time.perf_counter() - started) * 1000
            samples.append(total_ms)
            queries.append(self.counter.queries - before)
            LOG.info(
                "%-38s run %d/%d: %6.0f ms (HTTP %s, %d so'rov)",
                label,
                index + 1,
                runs,
                total_ms,
                getattr(response, "status_code", "?"),
                queries[-1],
            )
        if not samples:
            return None
        result = {
            "label": label,
            "runs": len(samples),
            "median_ms": round(statistics.median(samples), 1),
            "min_ms": round(min(samples), 1),
            "max_ms": round(max(samples), 1),
            "first_answer_median_ms": round(statistics.median(samples), 1),
            "queries_median": statistics.median(queries),
        }
        self.results.append(result)
        LOG.info(
            "%-38s mediana %6.0f ms | min %6.0f | max %6.0f | so'rov %s",
            label,
            result["median_ms"],
            result["min_ms"],
            result["max_ms"],
            result["queries_median"],
        )
        return result

    def run(
        self,
        label: str,
        coro_factory,
        runs: int,
        *,
        reset=None,
    ) -> dict:
        samples: list[float] = []
        firsts: list[float] = []
        queries: list[int] = []
        for index in range(runs):
            if reset is not None:
                reset()
            try:
                total_ms, first_ms, count = self._one(coro_factory)
            except Exception:
                LOG.exception("%s: run %d xato bilan tugadi", label, index + 1)
                continue
            samples.append(total_ms)
            firsts.append(first_ms)
            queries.append(count)
            LOG.info(
                "%-38s run %d/%d: %6.0f ms (1-javob %5.0f ms, %d so'rov)",
                label,
                index + 1,
                runs,
                total_ms,
                first_ms,
                count,
            )
        result = {
            "label": label,
            "runs": runs,
            "median_ms": round(statistics.median(samples), 1),
            "min_ms": round(min(samples), 1),
            "max_ms": round(max(samples), 1),
            "first_answer_median_ms": round(statistics.median(firsts), 1),
            "queries_median": statistics.median(queries),
        }
        self.results.append(result)
        LOG.info(
            "%-38s mediana %6.0f ms | min %6.0f | max %6.0f | so'rov %s",
            label,
            result["median_ms"],
            result["min_ms"],
            result["max_ms"],
            result["queries_median"],
        )
        return result


def _optional_handler(module_name: str, attr: str):
    """Mavjud bo'lsa handler qaytaradi, aks holda ``None``."""
    try:
        module = __import__(f"bot.handlers.{module_name}", fromlist=[attr])
    except Exception:  # modul yo'q bo'lsa ssenariy o'tkazib yuboriladi
        return None
    handler = getattr(module, attr, None)
    return handler if callable(handler) else None


def _import_optional_modules() -> None:
    """Ixtiyoriy handler modullarini oldindan yuklaydi (patch uchun)."""
    for name in ("games_catalog", "tournaments", "rewards"):
        try:
            __import__(f"bot.handlers.{name}")
        except Exception:  # ixtiyoriy modul bo'lmasa ssenariylar o'tkazib yuboriladi
            LOG.warning("bot.handlers.%s yuklanmadi", name)


def _patch_economy(store: EconomyStore) -> ExitStack:
    """Handlerlardagi ``get_economy`` ni o'lchanayotgan store'ga bog'laydi."""
    stack = ExitStack()
    patched = 0
    for name, module in list(sys.modules.items()):
        if not name.startswith("bot.handlers."):
            continue
        if hasattr(module, "get_economy"):
            stack.enter_context(
                patch.object(module, "get_economy", return_value=store)
            )
            patched += 1
    LOG.info("get_economy %d ta handler modulida almashtirildi", patched)
    return stack


def _bootstrap_client(store: EconomyStore):
    """``/api/bootstrap`` ni in-process (ASGI) chaqiruvchi mijoz.

    Haqiqiy HTTP server ishga tushirilmaydi: FastAPI ilovasi ``TestClient``
    orqali chaqiriladi, ya'ni o'lchov Mini App ko'radigan server ishini
    (marshrutlash + payload yig'ish) o'z ichiga oladi, tarmoq vaqtini emas.
    """
    from fastapi.testclient import TestClient

    import api.server as api_server

    stack = ExitStack()
    stack.enter_context(
        patch.object(api_server, "get_economy", return_value=store)
    )
    return TestClient(api_server.app), stack


def _delete_rows(store: EconomyStore, table: str, column: str, value: int) -> None:
    """O'lchov uchun yaratilgan vaqtinchalik yozuvni o'chiradi."""
    try:
        store.client.table(table).delete().eq(column, value).execute()
        LOG.info("Tozalandi: %s.%s=%s", table, column, value)
    except Exception:
        LOG.warning(
            "Tozalab bo'lmadi: %s.%s=%s — qo'lda o'chirib qo'ying",
            table,
            column,
            value,
            exc_info=True,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5, help="har ssenariy uchun takrorlash (default 5)")
    parser.add_argument("--user-id", type=int, default=0, help="o'lchov uchun mavjud foydalanuvchi ID")
    parser.add_argument("--inviter-id", type=int, default=0, help="yangi user ssenariysida taklif qiluvchi")
    parser.add_argument("--allow-write", action="store_true", help="bazaga yozadigan ssenariylarni ham o'lchash")
    parser.add_argument("--simulate", action="store_true", help="credentialsiz sinov (soxta Supabase)")
    parser.add_argument("--latency", type=float, default=0.12, help="--simulate uchun so'rov kechikishi, sekund")
    parser.add_argument("--json", type=str, default="", help="natijalarni JSON faylga yozish")
    parser.add_argument(
        "--no-bootstrap",
        action="store_true",
        help="/api/bootstrap o'lchovini o'tkazib yuborish",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    user_id = args.user_id or int(os.getenv("ADMIN_ID") or 0)
    if args.simulate and user_id <= 0:
        user_id = 777_000_001
    if user_id <= 0:
        LOG.error("Foydalanuvchi ID kerak: --user-id <telegram_id> bering")
        return 2

    if args.simulate:
        store = EconomyStore(client=_SimClient(args.latency, user_id))
        LOG.info(
            "SIMULYATSIYA rejimi: har so'rov %.0f ms, user_id=%s",
            args.latency * 1000,
            user_id,
        )
    else:
        store = EconomyStore()
        if not store.enabled:
            LOG.error(
                "Supabase sozlanmagan: .env ga SUPABASE_URL va "
                "SUPABASE_SERVICE_ROLE_KEY (yoki SUPABASE_KEY) qo'shing; "
                "credentialsiz sinov uchun --simulate ishlatiladi"
            )
            return 2
        LOG.info("Haqiqiy Supabase: %s | user_id=%s", store.url.split("//")[-1], user_id)

    counter = _CountingClient(store.client)
    store._client = counter  # noqa: SLF001 — o'lchov uchun ataylab
    _import_optional_modules()
    economy_patch = _patch_economy(store)
    bench = Bench(store, counter, user_id)

    existing = store.find_user(user_id)
    counter.queries = 0
    counter.db_seconds = 0.0
    if existing is None:
        LOG.warning(
            "ID %s bazada yo'q — avval botda /start bosing (Profil ssenariysi "
            "hisobni yaratishi mumkin)",
            user_id,
        )
    store.invalidate_user(user_id)

    runs = max(1, args.runs)

    # 1) /start: sovuq kesh (har run oldidan kesh tozalanadi) va kesh bilan.
    bench.run(
        "/start — sovuq kesh",
        lambda message: common.start_command(message, None),
        runs,
        reset=store.invalidate_user,
    )
    bench.run(
        "/start — kesh bilan",
        lambda message: common.start_command(message, None),
        runs,
    )

    # 2) Yangi foydalanuvchi + taklif havolasi (faqat --allow-write).
    if args.allow_write:
        inviter = args.inviter_id or user_id
        invited = 900_000_000_000 + random.randint(100_000, 999_999)
        command = SimpleNamespace(args=f"ref_{inviter}")
        bench.run(
            "/start — yangi user + ref (yozadi)",
            lambda message: common.start_command(message, command),
            1,
        )
        _delete_rows(store, "referrals", "invited_id", invited)
        _delete_rows(store, "users", "telegram_id", invited)

    # 3) Pastki menyu tugmalari.
    scenarios = [
        ("Profilim", profile.show_profile),
        ("Do'kon", shop.send_shop),
        ("Missiyalar", missions.show_missions),
        ("Reyting", leaderboard.show_leaderboard),
        ("O'yinlar ro'yxati", _optional_handler("games_catalog", "show_games")),
        ("Turnirlar", _optional_handler("tournaments", "show_tournaments")),
    ]
    for label, handler in scenarios:
        if handler is None:
            LOG.warning("%s: handler topilmadi, o'tkazib yuborildi", label)
            continue
        bench.run(
            f"{label} — sovuq kesh",
            lambda message, h=handler: h(message),
            runs,
            reset=store.invalidate_user,
        )
        bench.run(
            f"{label} — kesh bilan",
            lambda message, h=handler: h(message),
            runs,
        )

    # 4) Mini App: yagona /api/bootstrap endpointi (in-process ASGI).
    api_stack = None
    if not args.no_bootstrap:
        client = None
        try:
            client, api_stack = _bootstrap_client(store)
        except Exception:
            LOG.exception("Bootstrap o'lchovi ishga tushmadi")
        if client is not None:
            params = {
                "user_id": user_id,
                "username": "bench",
                "full_name": "Bench User",
            }
            bench.run_http(
                "Mini App /api/bootstrap — sovuq kesh",
                lambda: client.get("/api/bootstrap", params=params),
                1,
                reset=store.invalidate_user,
            )
            bench.run_http(
                "Mini App /api/bootstrap — kesh bilan",
                lambda: client.get("/api/bootstrap", params=params),
                runs,
            )

    if args.allow_write:
        bonus = _optional_handler("rewards", "claim_bonus")
        if bonus is not None:
            bench.run("Kunlik bonus (yozadi)", bonus, 1)

    start_row = next(
        (row for row in bench.results if row["label"].startswith("/start — sovuq")),
        None,
    )
    bootstrap_row = next(
        (
            row
            for row in bench.results
            if row["label"].startswith("Mini App /api/bootstrap — kesh")
        ),
        None,
    )
    if start_row and bootstrap_row:
        LOG.info(
            "Solishtirish (birinchi ochilish): bot /start %.0f ms | "
            "Mini App bootstrap %.0f ms | farq %+.0f ms",
            start_row["median_ms"],
            bootstrap_row["median_ms"],
            bootstrap_row["median_ms"] - start_row["median_ms"],
        )

    if api_stack is not None:
        api_stack.close()

    LOG.info("-" * 78)
    LOG.info(
        "%-38s %5s %9s %9s %9s %7s",
        "Ssenariy",
        "runs",
        "mediana",
        "min",
        "max",
        "so'rov",
    )
    for row in bench.results:
        LOG.info(
            "%-38s %5d %7.0f ms %6.0f ms %6.0f ms %7s",
            row["label"],
            row["runs"],
            row["median_ms"],
            row["min_ms"],
            row["max_ms"],
            row["queries_median"],
        )
    slowest = max(bench.results, key=lambda row: row["median_ms"])
    LOG.info(
        "Eng sekin ssenariy: %s — %.0f ms. Telegram tarmoq vaqti hisobga olinmagan.",
        slowest["label"],
        slowest["median_ms"],
    )

    economy_patch.close()

    if args.json:
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "mode": "simulate" if args.simulate else "supabase",
            "user_id": user_id,
            "runs": runs,
            "results": bench.results,
        }
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        LOG.info("Natijalar yozildi: %s", args.json)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
