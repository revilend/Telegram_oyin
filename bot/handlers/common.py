"""Shaxsiy chatdagi umumiy handlerlar."""

from __future__ import annotations

from html import escape

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from bot.config import get_config

router = Router(name="common")

WELCOME_TEXT = (
    "Salom, <b>{name}</b>! 👋\n\n"
    "<b>Revilend Games</b> — Telegram ichida o'ynaladigan stol o'yinlari platformasi.\n\n"
    "«Bunker» o'yinida falokatdan keyin omon qolish uchun guruh bilan birga qaror "
    "qabul qilasiz: kasbingiz, sog'lig'ingiz va yukingizga qarab kim bunkerga "
    "tushishini aniqlaysiz.\n\n"
    "🎮 O'yinlarni ochish uchun pastdagi tugmani bosing.\n"
    "➕ Guruhda yangi o'yin ochish uchun: /bunker"
)


@router.message(CommandStart())
async def start_command(message: Message) -> None:
    """/start — shaxsiy chatda xush kelibsiz xabari, Mini App va guruh tugmalari."""
    user = message.from_user
    if message.chat.type != "private":
        await message.answer(
            "Yangi Bunker o'yinini ochish uchun /bunker yoki /newgame buyrug'ini yuboring."
        )
        return

    name = escape(user.full_name if user else "do'stim")
    config = get_config()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎮 O'yinlar portalini ochish",
                    web_app=WebAppInfo(url=config.mini_app_url),
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Guruhga qo'shish",
                    url=f"https://t.me/{config.bot_username}?startgroup=true",
                )
            ],
        ]
    )
    await message.answer(WELCOME_TEXT.format(name=name), reply_markup=keyboard)
