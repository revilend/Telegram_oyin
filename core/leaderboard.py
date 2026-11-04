"""Haftalik liga va mavsumiy reyting so'rovlari.

Hafta chegarasi PostgreSQL'da (UTC, dushanba 00:00) aniqlanadi. Hisob
server xotirasida emas, Supabase'da saqlanadi; SQL RPC hisoblagichni atomar
yangilaydi.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Any

from core.db import get_store
from core.economy import UserAccount, _row_to_account

logger = logging.getLogger(__name__)

WEEKLY_WIN_SCORE = 50


class LeaderboardError(RuntimeError):
    """Reyting ma'lumotini o'qish yoki yangilash xatosi."""


def week_start_tashkent(moment: datetime | None = None) -> date:
    """Toshkent vaqti bo'yicha joriy haftaning dushanba sanasi."""
    zone = ZoneInfo("Asia/Tashkent")
    value = moment or datetime.now(zone)
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone)
    value = value.astimezone(zone)
    return value.date().fromordinal(value.date().toordinal() - value.weekday())


def record_weekly_win(user_id: int, *, score: int = WEEKLY_WIN_SCORE) -> bool:
    """G'alaba hisoblagichini atomar RPC orqali oshiradi."""
    store = get_store()
    if not store.enabled:
        logger.warning("Haftalik reyting yozilmadi: Supabase sozlanmagan")
        return False
    try:
        store.client.rpc(
            "record_weekly_win",
            {"p_telegram_id": int(user_id), "p_score": max(0, int(score))},
        ).execute()
        return True
    except Exception as exc:
        logger.exception("Haftalik g'alabani yozib bo'lmadi: user=%s", user_id)
        raise LeaderboardError("Haftalik reytingni yangilab bo'lmadi") from exc


def weekly_top(limit: int = 10) -> list[UserAccount]:
    """Joriy hafta bo'yicha eng yuqori ball olgan o'yinchilar."""
    store = get_store()
    if not store.enabled:
        return []
    try:
        rows = (
            store.client.table("users")
            .select("*")
            .eq("weekly_period_start", week_start_tashkent().isoformat())
            .order("weekly_score", desc=True)
            .order("weekly_wins", desc=True)
            .limit(max(1, min(int(limit), 1000)))
            .execute()
            .data
            or []
        )
        return [_row_to_account(row) for row in rows]
    except Exception as exc:
        logger.exception("Haftalik reytingni o'qib bo'lmadi")
        raise LeaderboardError("Haftalik reytingni yuklab bo'lmadi") from exc


def weekly_stats(user_id: int) -> dict[str, int]:
    """Bitta o'yinchining haftalik hisoblagichlarini qaytaradi."""
    store = get_store()
    if not store.enabled:
        return {"weekly_wins": 0, "weekly_score": 0}
    try:
        rows = (
            store.client.table("users")
            .select("weekly_wins,weekly_score")
            .eq("telegram_id", int(user_id))
            .eq("weekly_period_start", week_start_tashkent().isoformat())
            .limit(1)
            .execute()
            .data
            or []
        )
        row: dict[str, Any] = rows[0] if rows else {}
        return {
            "weekly_wins": int(row.get("weekly_wins") or 0),
            "weekly_score": int(row.get("weekly_score") or 0),
        }
    except Exception as exc:
        logger.exception("Haftalik statistika olinmadi: user=%s", user_id)
        raise LeaderboardError("Haftalik statistikani olib bo'lmadi") from exc
