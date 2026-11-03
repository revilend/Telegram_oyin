"""Doimiy pastki menyu tugmalari uchun handlerlar.

«👤 Mening profilim» ``bot.handlers.profile``da, «🏆 Reyting va Top»
``bot.handlers.leaderboard``da, «👑 Admin panel» ``bot.handlers.admin``da
ishlaydi. Bu modul qolgan tugmalarni ulaydi.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import get_config
from bot.handlers import admin, shop
from bot.keyboards.main_menu import (
    ADMIN_BUTTON,
    INVITE_BUTTON,
    NEW_GAME_BUTTON,
    RULES_BUTTON,
    SHOP_BUTTON,
)

logger = logging.getLogger(__name__)

router = Router(name="menu")

PRIVATE = F.chat.type == "private"


RULES_TEXT = (
    "ℹ️ <b>Qoidalar / Yordam</b>\n\n"
    "☢️ <b>Bunker nima?</b>\n"
    "Falokatdan keyin oz sonli odam bunkerga sig'adi. Har bir o'yinchining "
    "kartalari (kasb, biologiya, sog'liq, qiziqish, yuk va fakt) bo'yicha "
    "qaysi odam omon qolishga loyiqligini birgalikda hal qilasiz.\n\n"
    "🎮 <b>Qanday o'ynaladi?</b>\n"
    "1. Botni guruhga qo'shing va <code>/bunker</code> yuboring.\n"
    "2. Do'stlar «Guruh orqali qo'shilish» tugmasini bosadi.\n"
    "3. Xona egasi «O'yinni boshlash»ni bosadi.\n"
    "4. Mini App'da kartalaringizni birma-bir ochasiz.\n"
    "5. Ovoz berish raundida ortiqcha o'yinchilar haydaladi.\n\n"
    "🪙 <b>Tangalar va boosterlar</b>\n"
    "Tangalar «Tangalar do'koni»da sotib olinadi va qalqon, ikki ovoz yoki "
    "kartani qayta tanlash kabi boosterlarga sarflanadi.\n\n"
    "❓ Savol bo'lsa administratorga yozing."
)


@router.message(PRIVATE, F.text == SHOP_BUTTON)
async def menu_shop(message: Message, state: FSMContext) -> None:
    """🪙 Tangalar do'koni — /shop menyusini ochadi."""
    await shop.send_shop(message, state)


@router.message(PRIVATE, F.text == NEW_GAME_BUTTON)
async def menu_new_game(message: Message) -> None:
    """🛡️ Yangi Bunker — guruhda xona ochish qo'llanmasi."""
    config = get_config()
    text = (
        "🛡️ <b>Yangi Bunker o'yini</b>\n\n"
        "Bunker faqat guruhda o'ynaladi. Uch qadam:\n"
        "1. Botni guruhingizga qo'shing (pastdagi tugma).\n"
        "2. Guruhda <code>/bunker</code> buyrug'ini yuboring.\n"
        "3. Do'stlaringiz «Guruh orqali qo'shilish» tugmasini bosadi, "
        "xona egasi esa «O'yinni boshlash»ni bosadi.\n\n"
        "Keyin hamma Mini App'da kartalarini ko'radi va ovoz berish "
        "boshlanadi. Omad! 🍀"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Guruhga qo'shish",
                    url=f"https://t.me/{config.bot_username}?startgroup=true",
                )
            ]
        ]
    )
    await message.answer(text, reply_markup=keyboard)


@router.message(PRIVATE, F.text == RULES_BUTTON)
async def menu_rules(message: Message) -> None:
    """ℹ️ Qoidalar / Yordam."""
    await message.answer(RULES_TEXT)


@router.message(PRIVATE, F.text == INVITE_BUTTON)
async def menu_invite(message: Message) -> None:
    """👥 Do'stlarni taklif qilish."""
    config = get_config()
    link = f"https://t.me/{config.bot_username}"
    share_text = "Revilend Games — Bunker o'yinini birga o'ynaymiz! 🎮"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Do'stga ulashish",
                    url=(
                        "https://t.me/share/url"
                        f"?url={quote(link, safe='')}&text={quote(share_text, safe='')}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Guruhga qo'shish",
                    url=f"https://t.me/{config.bot_username}?startgroup=true",
                )
            ],
        ]
    )
    await message.answer(
        "👥 <b>Do'stlarni taklif qilish</b>\n\n"
        f"Bot havolasi: <code>{link}</code>\n\n"
        "Havolani do'stlaringizga yuboring — ular botni ochib, birgalikda "
        "guruhda Bunker o'ynashlari mumkin.\n\n"
        "💡 Guruhga qo'shib, <code>/bunker</code> yuboring va o'yinni "
        "boshlang.",
        reply_markup=keyboard,
    )


@router.message(PRIVATE, F.text == ADMIN_BUTTON)
async def menu_admin(message: Message, state: FSMContext | None = None) -> None:
    """👑 Admin panel — statistika va inline boshqaruv tugmalari."""
    await admin.admin_panel(message, state)
