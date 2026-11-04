"""🎮 O'yinlar vitrinasi: Bunker, Mafiya va Josus qoidalari.

``/games`` yoki «🎮 O'yinlar (Mini App)» tugmasi uchta faol o'yinni
ko'rsatadi; tanlanganda qisqa qoidalar va guruhda boshlash yo'riqnomasi
chiqadi.
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
from bot.keyboards.main_menu import GAMES_BUTTON

logger = logging.getLogger(__name__)

router = Router(name="games_catalog")

BUNKER_CALLBACK = "catalog_bunker"
MAFIA_CALLBACK = "catalog_mafia"
SPY_CALLBACK = "catalog_spy"
BACK_CALLBACK = "catalog_back"

CATALOG_TEXT = (
    "🎮 <b>O'yinlar</b>\n\n"
    "Qaysi o'yinni tanlaysiz?\n\n"
    "🛡️ <b>Bunker</b> — falokatdan keyin omon qolish uchun kartalar "
    "bo'yicha bahslashasiz.\n"
    "🕵️ <b>Mafiya</b> — tunda yashirin rollar, kunduzi ovoz berish.\n"
    "🔍 <b>Josus</b> — hamma joyni biladi, bitta josus bilmaydi. "
    "Savol-javob orqali uni toping."
)

BUNKER_TEXT = (
    "🛡️ <b>Bunker</b>\n\n"
    "Falokatdan keyin faqat bir necha kishi bunkerga sig'adi. Har bir "
    "o'yinchining kasbi, sog'lig'i, qiziqishi va yuki bo'yicha kim omon "
    "qolishga loyiqligini birgalikda hal qilasiz.\n\n"
    "🎮 <b>Guruhda boshlash:</b>\n"
    "1. Botni guruhingizga qo'shing.\n"
    "2. Guruhda <code>/bunker</code> yuboring.\n"
    "3. Do'stlar «Guruh orqali qo'shilish»ni bosadi.\n"
    "4. Xona egasi «O'yinni boshlash»ni bosadi."
)

SPY_TEXT = (
    "🔍 <b>Josus (Spyfall)</b>\n\n"
    "Hamma bitta joyda — masalan, to'yxonada yoki kosmik stantsiyada. "
    "Faqat bitta (yoki ikkita) josus qayerda ekanligini bilmaydi. "
    "Savol-javob orqali josusni toping, josus esa joyni taxmin qilishga "
    "harakat qiladi.\n\n"
    "🎮 <b>Guruhda boshlash:</b>\n"
    "1. Botni guruhingizga qo'shing.\n"
    "2. Guruhda <code>/spy</code> yoki <code>/josus</code> yuboring.\n"
    "3. Kamida 3 kishi «Qo'shilish»ni bosadi.\n"
    "4. Xona egasi o'yinni boshlaydi — kartalar Mini App'da ochiladi.\n\n"
    "🏆 G'olibga: tinch aholi +25, josus +35 tanga."
)

MAFIA_TEXT = (
    "🕵️ <b>Mafiya</b>\n\n"
    "Shahar mafiyalar changalida. Tunda yashirin rollar harakat qiladi, "
    "kunduzi shahar aholisi ovoz berib mafiyani topishga harakat qiladi.\n\n"
    "🎮 <b>Guruhda boshlash:</b>\n"
    "1. Botni guruhingizga qo'shing.\n"
    "2. Guruhda <code>/mafia</code> yuboring.\n"
    "3. Kamida 4 kishi «Qo'shilish»ni bosadi.\n"
    "4. Xona egasi o'yinni boshlaydi — rollar shaxsiy xabarda keladi."
)


def catalog_keyboard() -> InlineKeyboardMarkup:
    """Uchta faol o'yin tugmasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛡️ Bunker", callback_data=BUNKER_CALLBACK
                ),
                InlineKeyboardButton(
                    text="🕵️ Mafiya", callback_data=MAFIA_CALLBACK
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Josus", callback_data=SPY_CALLBACK
                )
            ],
        ]
    )


def detail_keyboard() -> InlineKeyboardMarkup:
    """Guruhga qo'shish va katalogga qaytish."""
    config = get_config()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Guruhga qo'shish",
                    url=f"https://t.me/{config.bot_username}?startgroup=true",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Orqaga", callback_data=BACK_CALLBACK
                )
            ],
        ]
    )


async def show_games(message: Message) -> None:
    """O'yinlar vitrinasini yuboradi."""
    await message.answer(CATALOG_TEXT, reply_markup=catalog_keyboard())


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
    """/games — ikkala o'yin vitrinasi."""
    await show_games(message)


@router.message(F.chat.type == "private", F.text == GAMES_BUTTON)
async def games_button(message: Message) -> None:
    """«🎮 O'yinlar (Mini App)» matn tugmasi (web_app bo'lmaganda)."""
    await show_games(message)


@router.callback_query(F.data == BUNKER_CALLBACK)
async def show_bunker(callback: CallbackQuery) -> None:
    """Bunker qoidalari va guruhda boshlash yo'riqnomasi."""
    await callback.answer()
    await _edit_or_send(callback, BUNKER_TEXT, detail_keyboard())


@router.callback_query(F.data == MAFIA_CALLBACK)
async def show_mafia(callback: CallbackQuery) -> None:
    """Mafiya qoidalari va guruhda boshlash yo'riqnomasi."""
    await callback.answer()
    await _edit_or_send(callback, MAFIA_TEXT, detail_keyboard())


@router.callback_query(F.data == SPY_CALLBACK)
async def show_spy(callback: CallbackQuery) -> None:
    """Josus qoidalari va guruhda boshlash yo'riqnomasi."""
    await callback.answer()
    await _edit_or_send(callback, SPY_TEXT, detail_keyboard())


@router.callback_query(F.data == BACK_CALLBACK)
async def back_to_catalog(callback: CallbackQuery) -> None:
    """Katalogga qaytish."""
    await callback.answer()
    await _edit_or_send(callback, CATALOG_TEXT, catalog_keyboard())
