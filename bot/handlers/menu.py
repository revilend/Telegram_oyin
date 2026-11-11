"""Doimiy pastki menyu tugmalari uchun handlerlar.

«👤 Mening profilim» ``bot.handlers.profile``da, «🏆 Reyting va Top»
``bot.handlers.leaderboard``da, «👑 Admin panel» ``bot.handlers.admin``da,
«👥 Do'stlarni taklif qilish» (referallar) va «ℹ️ Qoidalar / Yordam»
``bot.handlers.common``da ishlaydi.  Bu modul qolgan tugmalarni ulaydi.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from bot.config import get_config
from bot.handlers import admin, games_catalog, missions, shop, tournaments
from bot.keyboards.main_menu import mini_app_url_for
from core.i18n import all_button_texts, resolve_language, t

logger = logging.getLogger(__name__)

router = Router(name="menu")

PRIVATE = F.chat.type == "private"


@router.message(PRIVATE, F.text.in_(all_button_texts("games")))
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
    from bot.handlers import common as common_handlers

    language = resolve_language(
        user.id if user is not None else None,
        getattr(user, "language_code", None) if user is not None else None,
    )
    if not url.startswith("https://"):
        await message.answer(t(language, "miniapp_unconfigured"))
        await common_handlers.send_login_code(message)
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "miniapp_open_button"),
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )
    await message.answer(
        t(language, "portal_title"),
        reply_markup=keyboard,
    )
    # Mini App initData'siz ochilganda ham profilga kirish uchun kod.
    await common_handlers.send_login_code(message)


@router.message(PRIVATE, F.text.in_(all_button_texts("shop")))
async def menu_shop(message: Message, state: FSMContext) -> None:
    """🪙 Tangalar do'koni — /shop menyusini ochadi."""
    await shop.send_shop(message, state)


@router.message(PRIVATE, F.text.in_(all_button_texts("tournaments")))
async def menu_tournaments(message: Message) -> None:
    """🏆 Turnirlar — haftalik çempionat afishasi."""
    await tournaments.show_tournaments(message)


@router.message(PRIVATE, F.text.in_(all_button_texts("games_list")))
async def menu_game_list(message: Message) -> None:
    """🎲 O'yinlar ro'yxati — platformadagi barcha o'yinlar."""
    await games_catalog.show_games(message)


@router.message(PRIVATE, F.text.in_(all_button_texts("missions")))
@router.message(PRIVATE, Command("missions"))
async def menu_missions(message: Message) -> None:
    """🎯 Missiyalar — topshiriqlar va mukofotlar."""
    await missions.show_missions(message)


@router.message(PRIVATE, F.text.in_(all_button_texts("admin")))
async def menu_admin(message: Message, state: FSMContext | None = None) -> None:
    """👑 Admin panel — statistika va inline boshqaruv tugmalari."""
    await admin.admin_panel(message, state)
