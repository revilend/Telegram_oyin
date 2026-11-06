"""Kunlik avtomatik baza zaxirasi: har kuni 00:00 (Asia/Tashkent).

Jadval APScheduler bilan rejalashtiriladi. Agar kutubxona o'rnatilmagan
bo'lsa, xuddi shu vaqtda ishlaydigan yengil ``asyncio`` tsikli ishlatiladi —
funksionallik kutubxonaga bog'liq bo'lib qolmaydi.

Zaxira fayli bot orqali ``ADMIN_ID``ning shaxsiy chatiga yuboriladi.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from aiogram.types import BufferedInputFile

from core.backup import (
    TASHKENT,
    BackupError,
    auto_backup_filename,
    backup_total_rows,
    dumps_backup,
    get_backup_store,
)

logger = logging.getLogger(__name__)

DAILY_TEXT = (
    "📦 <b>Revilend Games — Kunlik Baza Zaxirasi</b>\n"
    "📅 Sana: {date} 00:00 (Toshkent vaqti)\n"
    "✅ Holati: Muvaffaqiyatli saqlandi va yuborildi."
)


def daily_backup_text(now: datetime | None = None) -> str:
    """Kunlik zaxira xabarining matni (Toshkent sanasi bilan)."""
    moment = now or datetime.now(TASHKENT)
    return DAILY_TEXT.format(date=moment.astimezone(TASHKENT).strftime("%Y-%m-%d"))


def next_run_at(now: datetime | None = None) -> datetime:
    """Keyingi 00:00 (Toshkent) vaqtini qaytaradi."""
    moment = (now or datetime.now(TASHKENT)).astimezone(TASHKENT)
    target = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    if target <= moment:
        target += timedelta(days=1)
    return target


def seconds_until_next_run(now: datetime | None = None) -> float:
    """Keyingi 00:00 gacha qolgan soniyalar."""
    moment = (now or datetime.now(TASHKENT)).astimezone(TASHKENT)
    return max(0.0, (next_run_at(moment) - moment).total_seconds())


async def send_daily_backup(bot: Any, chat_id: int, *, now: datetime | None = None) -> Any:
    """Zaxira yaratib, uni bot orqali adminga hujjat sifatida yuboradi."""
    if not chat_id:
        raise BackupError("ADMIN_ID sozlanmagan — kunlik zaxira yuborilmaydi.")
    payload = await asyncio.to_thread(get_backup_store().create_backup)
    document = BufferedInputFile(dumps_backup(payload), filename=auto_backup_filename(now))
    logger.info(
        "Kunlik zaxira tayyor: %s qator, %s jadval",
        backup_total_rows(payload),
        len(payload.get("counts") or {}),
    )
    return await bot.send_document(
        chat_id,
        document,
        caption=daily_backup_text(now),
    )


async def run_daily_backup(bot: Any, chat_id: int) -> None:
    """Rejalashtirilgan vazifa: xatoni yutib, jurnalga yozadi."""
    try:
        await send_daily_backup(bot, chat_id)
    except Exception:
        logger.exception("Kunlik avtomatik zaxira yuborilmadi")


async def _backup_loop(bot: Any, chat_id: int) -> None:
    """APScheduler bo'lmaganda ishlaydigan zaxira tsikli."""
    while True:
        await asyncio.sleep(seconds_until_next_run())
        await run_daily_backup(bot, chat_id)


def start_daily_backup(bot: Any, chat_id: int) -> Any | None:
    """Har kuni 00:00 (Toshkent) da zaxira yuboradigan vazifani ishga tushiradi.

    Returns:
        APScheduler ``AsyncIOScheduler`` yoki ``asyncio.Task``; ``ADMIN_ID``
        sozlanmagan bo'lsa ``None``.
    """
    if not chat_id:
        logger.warning("ADMIN_ID sozlanmagan — kunlik zaxira rejalashtirilmadi")
        return None

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except Exception:  # kutubxona o'rnatilmagan muhitlar uchun
        logger.info("APScheduler topilmadi — asyncio tsikli bilan zaxira rejalashtirildi")
        return asyncio.create_task(_backup_loop(bot, chat_id))

    scheduler = AsyncIOScheduler(timezone=TASHKENT)
    scheduler.add_job(
        run_daily_backup,
        CronTrigger(hour=0, minute=0, timezone=TASHKENT),
        args=[bot, chat_id],
        id="daily-backup",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.start()
    logger.info("Kunlik zaxira rejalashtirildi: har kuni 00:00 (Toshkent)")
    return scheduler


def stop_daily_backup(job: Any | None) -> None:
    """Rejalashtirilgan zaxira vazifasini to'xtatadi."""
    if job is None:
        return
    try:
        if hasattr(job, "shutdown"):
            job.shutdown(wait=False)
        elif hasattr(job, "cancel"):
            job.cancel()
    except Exception:
        logger.exception("Kunlik zaxira vazifasini to'xtatib bo'lmadi")


__all__ = [
    "daily_backup_text",
    "next_run_at",
    "run_daily_backup",
    "seconds_until_next_run",
    "send_daily_backup",
    "start_daily_backup",
    "stop_daily_backup",
]
