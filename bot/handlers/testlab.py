"""`/test_game` — virtual botlar bilan öyinni avtomatik sinash buyrug‘i."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.handlers.admin import is_admin
from engine.test_lab import GAMES, format_report, run_game

logger = logging.getLogger(__name__)

router = Router(name="test_lab")


@router.message(Command("test_game"))
async def test_game(message: Message) -> None:
    """Admin uçun: xonani virtual botlar bilan töldirib, öyinni oxirigacha öynaydi."""
    user = message.from_user
    if user is None or not is_admin(user.id):
        await message.answer("⛔ Bu buyruq faqat administrator uçun.")
        return

    parts = (message.text or "").split(maxsplit=1)
    requested = parts[1].strip() if len(parts) > 1 else "all"
    requested = requested.split()[0].lower() if requested else "all"
    if requested not in GAMES and requested not in ("all", "hammasi"):
        await message.answer(
            "🎮 Qaysi öyinni sinaymiz?\n"
            f"Mavjud: {', '.join(GAMES)}\n"
            "Masalan: <code>/test_game bunker</code> yoki <code>/test_game all</code>",
            parse_mode="HTML",
        )
        return

    await message.answer("🧪 Virtual botlar öyinni öynayapti, biroz kuting…")
    try:
        result = await asyncio.to_thread(run_game, requested)
    except Exception as error:  # buyruq hech qachon botni yiqitmasin
        logger.exception("Virtual bot testi işlamadi")
        await message.answer(f"❌ Test işlamadi: {error}")
        return
    try:
        await message.answer(format_report(result), parse_mode="HTML")
    except Exception:
        logger.exception("Hisobotni yuborib bölmadi")
        await message.answer("✅ Test tugadi, lekin hisobotni formatlaşda xato böldi.")
