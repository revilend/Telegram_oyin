"""Shaxsiy chatdagi umumiy handlerlar."""

from __future__ import annotations

import logging
from html import escape

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.handlers.admin import is_admin
from bot.keyboards.main_menu import build_main_menu
from core.economy import get_economy

logger = logging.getLogger(__name__)

router = Router(name="common")

WELCOME_TEXT = (
    "Salom, <b>{name}</b>! 👋\n\n"
    "<b>Revilend Games</b> — Telegram ichida o'ynaladigan stol o'yinlari platformasi.\n\n"
    "«Bunker» o'yinida falokatdan keyin omon qolish uchun guruh bilan birga qaror "
    "qabul qilasiz: kasbingiz, sog'lig'ingiz va yukingizga qarab kim bunkerga "
    "tushishini aniqlaysiz.\n\n"
    "🎮 O'yinlarni ochish uchun pastdagi menyudan foydalaning.\n"
    "➕ Guruhda yangi o'yin ochish uchun: /bunker"
)


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    """/start — xush kelibsiz xabari va doimiy pastki menyu."""
    user = message.from_user
    if message.chat.type != "private":
        await message.answer(
            "Yangi Bunker o'yinini ochish uchun /bunker yoki /newgame buyrug'ini yuboring."
        )
        return

    name = escape(user.full_name if user else "do'stim")
    if user is not None:
        try:
            # Foydalanuvchi `users.telegram_id` bo'yicha saqlanadi.
            get_economy().ensure_user(user.id, user.username or "", user.full_name)
        except Exception:
            logger.exception("Foydalanuvchini saqlab bo'lmadi: %s", user.id)
    # Doimiy pastki menyu /start bilan darhol chiqadi.
    await message.answer(
        WELCOME_TEXT.format(name=name),
        reply_markup=build_main_menu(
            is_admin=is_admin(user.id) if user is not None else False
        ),
    )
