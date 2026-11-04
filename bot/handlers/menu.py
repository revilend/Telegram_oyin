"""Doimiy pastki menyu tugmalari uchun handlerlar.

«👤 Mening profilim» ``bot.handlers.profile``da, «🏆 Reyting va Top»
``bot.handlers.leaderboard``da, «👑 Admin panel» ``bot.handlers.admin``da,
«👥 Do'stlarni taklif qilish» (referallar) ``bot.handlers.common``da ishlaydi.
Bu modul qolgan tugmalarni ulaydi.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from bot.config import get_config
from bot.handlers import admin, shop
from bot.keyboards.main_menu import (
    ADMIN_BUTTON,
    GAMES_BUTTON,
    NEW_GAME_BUTTON,
    RULES_BUTTON,
    SHOP_BUTTON,
    mini_app_url_for,
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


@router.message(PRIVATE, F.text == GAMES_BUTTON)
async def menu_games(message: Message) -> None:
    """🎮 O'yinlar — Mini App'ni inline web_app tugmasi orqali ochadi.

    Pastki (reply) klaviaturadagi ``web_app`` tugmasi initData yubormasligi
    mumkin, shuning uchun havolaga foydalanuvchi id'si va ismi qo'shiladi.
    """
    config = get_config()
    user = message.from_user
    url = mini_app_url_for(
        config.mini_app_url or "",
        user_id=user.id if user is not None else None,
        username=(user.username or "") if user is not None else "",
        full_name=(user.full_name or "") if user is not None else "",
    )
    if not url.startswith("https://"):
        await message.answer(
            "⚠️ Mini App manzili sozlanmagan. Administratorga murojaat qiling."
        )
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 O'yinlar portaliga kirish",
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )
    await message.answer(
        "🎮 <b>O'yinlar portali</b>\n\n"
        "Bunker, Mafiya va Josus o'yinlarini shu yerda oching. "
        "Balansingiz va statistikangiz Mini App'da ko'rinadi.",
        reply_markup=keyboard,
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


@router.message(PRIVATE, F.text == ADMIN_BUTTON)
async def menu_admin(message: Message, state: FSMContext | None = None) -> None:
    """👑 Admin panel — statistika va inline boshqaruv tugmalari."""
    await admin.admin_panel(message, state)
