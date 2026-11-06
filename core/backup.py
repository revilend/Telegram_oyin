"""Bazaning to'liq zaxira nusxasi (backup) va tiklash (restore).

Zaxira Supabase/PostgreSQL jadvallarini PostgREST orqali o'qib, versiyalangan
JSON faylga yig'adi::

    {
      "version": 1,
      "app": "Revilend Games",
      "created_at": "2026-11-06T19:00:00+00:00",
      "created_at_tashkent": "2026-11-07T00:00:00+05:00",
      "tables": {"users": [...], "rooms": [...], ...},
      "counts": {"users": 42, "rooms": 3, ...},
      "skipped": ["bomb_cards"]
    }

Tiklash faqat ``upsert`` bilan ishlaydi: mavjud qatorlar yangilanadi, yangi
qatorlar qo'shiladi. Hech qanday jadval o'chirilmaydi — bu noto'g'ri fayl
yuklansa ham ma'lumotni yo'qotmaslik uchun.

Baza sozlanmagan bo'lsa (``SUPABASE_URL``/``SUPABASE_KEY`` yo'q) funksiyalar
``BackupError`` ko'taradi: admin panel aniq xabar ko'rsatadi.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from html import escape
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from core.db import safe_upsert

logger = logging.getLogger(__name__)

TASHKENT = ZoneInfo("Asia/Tashkent")

BACKUP_VERSION = 1
APP_NAME = "Revilend Games"

# PostgREST bir so'rovda ko'pi bilan shuncha qator qaytaradi.
PAGE_SIZE = 1000
# Tiklashda bir so'rovda yuboriladigan qatorlar soni.
RESTORE_CHUNK = 100

# Jadval nomi -> upsert uchun konflikt ustunlari (primary key).
# Tartib muhim: ``users`` va ``rooms`` avval tiklanadi, chunki bog'liq
# jadvallar ularga foreign key bilan tayanadi.
BACKUP_TABLES: dict[str, str] = {
    "users": "telegram_id",
    "referrals": "id",
    "user_inventory": "user_id,item_slug",
    "transactions": "id",
    "payment_requests": "id",
    "system_settings": "key",
    "promo_codes": "code",
    "promo_redemptions": "code,user_id",
    "player_missions": "user_id,mission",
    "rooms": "code",
    "room_players": "room_code,user_id",
    "player_boosters": "room_code,user_id,booster",
    "game_results": "room_code",
    "game_history": "id",
    "spyfall_rooms": "code",
    "alias_words": "id",
    "matchmaking_queue": "user_id",
    "tournaments": "id",
    "tournament_participants": "tournament_id,user_id",
    # Sxemada hali bo'lmasligi mumkin bo'lgan jadvallar: mavjud bo'lsa
    # zaxiraga tushadi, bo'lmasa ``skipped`` ro'yxatiga qo'shiladi.
    "shop_items": "slug",
    "bomb_cards": "id",
}


class BackupError(RuntimeError):
    """Zaxira olish yoki tiklashning kutilgan xatosi."""


def missing_table(exc: Exception) -> bool:
    """Xato «jadval topilmadi» ekanini aniqlaydi.

    PostgREST ``PGRST205`` (schema cache'da jadval yo'q) va Postgres
    ``42P01`` (relation does not exist) holatlarini tushunadi.
    """
    message = str(exc or "").lower()
    code = str(getattr(exc, "code", "") or "").upper()
    if code in {"PGRST205", "42P01"}:
        return True
    return "could not find the table" in message or (
        "relation" in message and "does not exist" in message
    )


def _chunks(rows: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _tashkent(now: datetime | None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(TASHKENT)


def backup_filename(now: datetime | None = None) -> str:
    """Qo'lda olinadigan zaxira fayli nomi: ``backup_revilend_YYYY_MM_DD_HHMM.json``."""
    return f"backup_revilend_{_tashkent(now):%Y_%m_%d_%H%M}.json"


def auto_backup_filename(now: datetime | None = None) -> str:
    """Kunlik avtomatik zaxira fayli nomi: ``backup_avto_YYYY_MM_DD.json``."""
    return f"backup_avto_{_tashkent(now):%Y_%m_%d}.json"


def dumps_backup(payload: dict[str, Any]) -> bytes:
    """Zaxira tuzilmasini Telegram'ga yuboriladigan JSON baytlariga aylantiradi."""
    return json.dumps(
        payload, ensure_ascii=False, indent=2, default=str, sort_keys=False
    ).encode("utf-8")


def backup_total_rows(payload: dict[str, Any]) -> int:
    """Zaxifadagi barcha qatorlar soni."""
    return sum(int(value) for value in (payload.get("counts") or {}).values())


def backup_caption(payload: dict[str, Any], *, filename: str = "") -> str:
    """Qo'lda olingan zaxira hujjati uchun izoh matni."""
    lines = ["📥 <b>Bazadan nusxa olindi</b>", ""]
    if filename:
        lines.append(f"🗂 Fayl: <code>{escape(filename)}</code>")
    lines.append(
        f"📊 Jadvallar: <b>{len(payload.get('counts') or {})}</b> · "
        f"qatorlar: <b>{backup_total_rows(payload)}</b>"
    )
    stamp = str(payload.get("created_at_tashkent") or "")[:16].replace("T", " ")
    if stamp:
        lines.append(f"🕒 {stamp} (Toshkent vaqti)")
    skipped = [str(name) for name in (payload.get("skipped") or [])]
    if skipped:
        lines.append(
            "⚠️ Mavjud bo'lmagan jadvallar: " + escape(", ".join(skipped))
        )
    return "\n".join(lines)


def restore_caption(result: dict[str, Any]) -> str:
    """Tiklash natijasi haqidagi hisobot matni."""
    restored = result.get("restored") or {}
    tables = len(restored)
    total = sum(int(value) for value in restored.values())
    lines = [
        "✅ <b>Baza tiklandi</b>",
        "",
        f"📊 Jadvallar: <b>{tables}</b> · qatorlar: <b>{total}</b>",
        "♻️ Mavjud qatorlar yangilandi, yangilari qo'shildi (o'chirish yo'q).",
    ]
    skipped = [str(name) for name in (result.get("skipped") or [])]
    if skipped:
        lines.append(
            "⚠️ O'tkazib yuborilgan jadvallar: " + escape(", ".join(skipped))
        )
    return "\n".join(lines)


class BackupStore:
    """Supabase jadvallaridan zaxira oladigan va ularni tiklaydigan ombor."""

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.url = (url if url is not None else os.getenv("SUPABASE_URL") or "").strip()
        self.key = (key if key is not None else os.getenv("SUPABASE_KEY") or "").strip()
        self._client = client
        self._client_lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._client is not None or bool(self.url and self.key)

    @property
    def client(self) -> Any:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    from supabase import create_client

                    self._client = create_client(self.url, self.key)
        return self._client

    # ------------------------------------------------------------------
    # O'qish / zaxira
    # ------------------------------------------------------------------
    def fetch_table(self, table: str) -> list[dict[str, Any]]:
        """Jadvalning barcha qatorlarini sahifalab o'qiydi."""
        rows: list[dict[str, Any]] = []
        start = 0
        while True:
            page = (
                self.client.table(table)
                .select("*")
                .range(start, start + PAGE_SIZE - 1)
                .execute()
                .data
                or []
            )
            rows.extend(row for row in page if isinstance(row, dict))
            if len(page) < PAGE_SIZE:
                return rows
            start += PAGE_SIZE

    def create_backup(
        self,
        *,
        now: datetime | None = None,
        tables: list[str] | None = None,
    ) -> dict[str, Any]:
        """Barcha asosiy jadvallardan to'liq zaxira yig'adi."""
        if not self.enabled:
            raise BackupError(
                "Supabase sozlanmagan: SUPABASE_URL va SUPABASE_KEY kerak."
            )
        moment = now or datetime.now(timezone.utc)
        selected = tables if tables is not None else list(BACKUP_TABLES)
        payload: dict[str, Any] = {
            "version": BACKUP_VERSION,
            "app": APP_NAME,
            "created_at": moment.astimezone(timezone.utc).isoformat(),
            "created_at_tashkent": moment.astimezone(TASHKENT).isoformat(),
            "tables": {},
            "counts": {},
            "skipped": [],
        }
        for table in selected:
            try:
                rows = self.fetch_table(table)
            except Exception as exc:
                if missing_table(exc):
                    payload["skipped"].append(table)
                    logger.info("Zaxira: '%s' jadvali bazada yo'q", table)
                    continue
                raise
            payload["tables"][table] = rows
            payload["counts"][table] = len(rows)
        return payload

    # ------------------------------------------------------------------
    # Tiklash
    # ------------------------------------------------------------------
    def restore(
        self,
        payload: dict[str, Any],
        *,
        tables: list[str] | None = None,
    ) -> dict[str, Any]:
        """JSON zaxirasini jadvallarga ``upsert`` qiladi."""
        if not self.enabled:
            raise BackupError(
                "Supabase sozlanmagan: SUPABASE_URL va SUPABASE_KEY kerak."
            )
        if not isinstance(payload, dict):
            raise BackupError("Fayl formati noto'g'ri: JSON obyekt kutilgan.")
        raw_tables = payload.get("tables")
        if not isinstance(raw_tables, dict) or not raw_tables:
            raise BackupError(
                "Fayl formati noto'g'ri: 'tables' bo'limi topilmadi."
            )
        if payload.get("app") not in (None, APP_NAME):
            raise BackupError("Bu fayl Revilend Games zaxirasi emas.")

        selected = set(tables) if tables is not None else None
        restored: dict[str, int] = {}
        skipped: list[str] = []
        for table, rows in raw_tables.items():
            name = str(table)
            if selected is not None and name not in selected:
                continue
            if name not in BACKUP_TABLES:
                skipped.append(name)
                logger.warning("Tiklash: noma'lum jadval o'tkazib yuborildi: %s", name)
                continue
            if not isinstance(rows, list):
                raise BackupError(f"'{name}' jadvali uchun qatorlar ro'yxati kutilgan.")
            clean = [row for row in rows if isinstance(row, dict)]
            if not clean:
                restored[name] = 0
                continue
            try:
                for chunk in _chunks(clean, RESTORE_CHUNK):
                    safe_upsert(
                        self.client,
                        name,
                        chunk,
                        on_conflict=BACKUP_TABLES[name],
                    )
            except Exception as exc:
                if missing_table(exc):
                    skipped.append(name)
                    logger.info("Tiklash: '%s' jadvali bazada yo'q", name)
                    continue
                raise
            restored[name] = len(clean)
        return {"restored": restored, "skipped": skipped}


_store: BackupStore | None = None
_store_lock = threading.Lock()


def get_backup_store() -> BackupStore:
    """Umumiy BackupStore nusxasini qaytaradi."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = BackupStore()
    return _store


__all__ = [
    "BACKUP_TABLES",
    "BACKUP_VERSION",
    "BackupError",
    "BackupStore",
    "TASHKENT",
    "auto_backup_filename",
    "backup_caption",
    "backup_filename",
    "backup_total_rows",
    "dumps_backup",
    "get_backup_store",
    "missing_table",
    "restore_caption",
]
