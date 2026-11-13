"""🎮 O'yinlar vitrinasi: beshta faol o'yin qoidalari.

``/games`` yoki «🎲 O'yinlar ro'yxati» tugmasi platformadagi beshta faol
o'yinni ko'rsatadi; tanlanganda qisqa qoidalar, guruhda boshlash buyrug'i va
«➕ Guruhga qo'shish» tugmasi chiqadi.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import get_config
from core.i18n import resolve_language, t

logger = logging.getLogger(__name__)

router = Router(name="games_catalog")

BUNKER_CALLBACK = "catalog_bunker"
MAFIA_CALLBACK = "catalog_mafia"
SPY_CALLBACK = "catalog_spy"
ALIAS_CALLBACK = "catalog_alias"
BOMB_CALLBACK = "catalog_bomb"
BACK_CALLBACK = "catalog_back"


def catalog_keyboard(language: str = "uz") -> InlineKeyboardMarkup:
    """Har bir o'yin alohida qatorda + guruhga qo'shish tugmasi."""
    config = get_config()
    entries = (
        ("catalog_btn_bunker", BUNKER_CALLBACK),
        ("catalog_btn_mafia", MAFIA_CALLBACK),
        ("catalog_btn_spy", SPY_CALLBACK),
        ("catalog_btn_alias", ALIAS_CALLBACK),
        ("catalog_btn_bomb", BOMB_CALLBACK),
        ("catalog_btn_tournaments", "tournaments_open"),
    )
    rows = [
        [InlineKeyboardButton(text=t(language, key), callback_data=data)]
        for key, data in entries
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=t(language, "catalog_btn_add_group"),
                url=f"https://t.me/{config.bot_username}?startgroup=true",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def detail_keyboard(language: str = "uz") -> InlineKeyboardMarkup:
    """Guruhga qo'shish va katalogga qaytish."""
    config = get_config()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "catalog_btn_add_group_small"),
                    url=f"https://t.me/{config.bot_username}?startgroup=true",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "catalog_back"), callback_data=BACK_CALLBACK
                )
            ],
        ]
    )


async def show_games(message: Message) -> None:
    """O'yinlar vitrinasini yuboradi."""
    user = message.from_user
    language = resolve_language(
        user.id if user is not None else None,
        getattr(user, "language_code", None) if user is not None else None,
    )
    await message.answer(t(language, "catalog_title"), reply_markup=catalog_keyboard(language))


async def _edit_or_send(
    callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup
) -> None:
    message = callback.message
    if message is not None and hasattr(message, "edit_text"):
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            pass
    await callback.bot.send_message(
        callback.message.chat.id if callback.message else callback.from_user.id,
        text,
        reply_markup=keyboard,
    )


@router.message(Command("games"))
async def games_command(message: Message) -> None:
    """/games — barcha o'yinlar ro'yxati."""
    await show_games(message)


@router.callback_query(F.data == BUNKER_CALLBACK)
async def show_bunker(callback: CallbackQuery) -> None:
    """Bunker qoidalari va guruhda boshlash yo'riqnomasi."""
    language = resolve_language(callback.from_user.id, getattr(callback.from_user, 'language_code', None))
    await callback.answer()
    await _edit_or_send(callback, t(language, "catalog_bunker"), detail_keyboard(language))


@router.callback_query(F.data == MAFIA_CALLBACK)
async def show_mafia(callback: CallbackQuery) -> None:
    """Mafiya qoidalari va guruhda boshlash yo'riqnomasi."""
    language = resolve_language(callback.from_user.id, getattr(callback.from_user, 'language_code', None))
    await callback.answer()
    await _edit_or_send(callback, t(language, "catalog_mafia"), detail_keyboard(language))


@router.callback_query(F.data == SPY_CALLBACK)
async def show_spy(callback: CallbackQuery) -> None:
    """Josus qoidalari va guruhda boshlash yo'riqnomasi."""
    language = resolve_language(callback.from_user.id, getattr(callback.from_user, 'language_code', None))
    await callback.answer()
    await _edit_or_send(callback, t(language, "catalog_spy"), detail_keyboard(language))


@router.callback_query(F.data == ALIAS_CALLBACK)
async def show_alias(callback: CallbackQuery) -> None:
    """Alias qoidalari va guruhda boshlash yo'riqnomasi."""
    language = resolve_language(callback.from_user.id, getattr(callback.from_user, 'language_code', None))
    await callback.answer()
    await _edit_or_send(callback, t(language, "catalog_alias"), detail_keyboard(language))


@router.callback_query(F.data == BOMB_CALLBACK)
async def show_bomb(callback: CallbackQuery) -> None:
    """Portlovçi Bomba qoidalari va guruhda boshlash yo'riqnomasi."""
    language = resolve_language(callback.from_user.id, getattr(callback.from_user, 'language_code', None))
    await callback.answer()
    await _edit_or_send(callback, t(language, "catalog_bomb"), detail_keyboard(language))


@router.callback_query(F.data == BACK_CALLBACK)
async def back_to_catalog(callback: CallbackQuery) -> None:
    """Katalogga qaytish."""
    language = resolve_language(callback.from_user.id, getattr(callback.from_user, 'language_code', None))
    await callback.answer()
    await _edit_or_send(callback, t(language, "catalog_title"), catalog_keyboard(language))
