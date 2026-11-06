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

logger = logging.getLogger(__name__)

router = Router(name="games_catalog")

BUNKER_CALLBACK = "catalog_bunker"
MAFIA_CALLBACK = "catalog_mafia"
SPY_CALLBACK = "catalog_spy"
ALIAS_CALLBACK = "catalog_alias"
BOMB_CALLBACK = "catalog_bomb"
BACK_CALLBACK = "catalog_back"

CATALOG_TEXT = (
    "🎲 <b>Öyinlar röyxati</b>\n\n"
    "Platformadagi barça öyinlar. Har biri guruhda öynaladi:\n\n"
    "🛡️ <b>Bunker</b> — <code>/bunker</code> bilan boşlanadi. Falokatdan "
    "keyin omon qoliş uçun kartalar böyiça bahslaşasiz.\n"
    "🕵️ <b>Mafiya</b> — <code>/mafia</code> bilan boşlanadi. Tunda yaşirin "
    "rollar, kunduzi ovoz beriş.\n"
    "🔍 <b>Josus</b> — <code>/spy</code> bilan boşlanadi. Hamma joyni "
    "biladi, bitta josus bilmaydi. Savol-javob orqali uni toping.\n"
    "🐊 <b>Alias</b> — <code>/alias</code> bilan boşlanadi. Sözni "
    "aytmasdan, taqiqlangan sözlarsiz tuşuntirasiz.\n"
    "💣 <b>Portlovçi Bomba</b> — <code>/bomb</code> bilan boşlanadi. "
    "Bombani zararsizlantirib, oxirgi tirik qoling.\n\n"
    "👇 Öyinni tanlang — guruhda boşlaş böyiça qöllanma çiqadi."
)

BUNKER_TEXT = (
    "🛡️ <b>Bunker</b>\n\n"
    "Falokatdan keyin faqat bir neça kişi bunkerga siğadi. Har bir "
    "öyinçining kasbi, soğliği, qiziqişi va yuki böyiça kim omon "
    "qolişga loyiqligini birgalikda hal qilasiz.\n\n"
    "🎮 <b>Guruhda boşlaş:</b>\n"
    "1. Botni guruhingizga qöşing.\n"
    "2. Guruhda <code>/bunker</code> yuboring.\n"
    "3. Döstlar «Guruh orqali qöşiliş»ni bosadi.\n"
    "4. Xona egasi «Öyinni boşlaş»ni bosadi."
)

SPY_TEXT = (
    "🔍 <b>Josus (Spyfall)</b>\n\n"
    "Hamma bitta joyda — masalan, töyxonada yoki kosmik stantsiyada. "
    "Faqat bitta (yoki ikkita) josus qayerda ekanligini bilmaydi. "
    "Savol-javob orqali josusni toping, josus esa joyni taxmin qilişga "
    "harakat qiladi.\n\n"
    "🎮 <b>Guruhda boşlaş:</b>\n"
    "1. Botni guruhingizga qöşing.\n"
    "2. Guruhda <code>/spy</code> yoki <code>/josus</code> yuboring.\n"
    "3. Kamida 3 kişi «Qöşiliş»ni bosadi.\n"
    "4. Xona egasi öyinni boşlaydi — kartalar Mini App'da oçiladi.\n\n"
    "🏆 Ğolibga: tinç aholi +25, josus +35 tanga."
)

ALIAS_TEXT = (
    "🐊 <b>Alias / Krokodil</b>\n\n"
    "Har raundda bitta öyinçi tuşuntiruvçi böladi. U sözni aytmasdan, "
    "uçta taqiqlangan sözni işlatmasdan tuşuntiradi. Qolganlar 60 soniya "
    "içida sözni topişga harakat qiladi.\n\n"
    "🎮 <b>Guruhda boşlaş:</b>\n"
    "1. Botni guruhingizga qöşing.\n"
    "2. Guruhda <code>/alias</code> yoki <code>/krokodil</code> yuboring.\n"
    "3. Kamida 2 kişi «➕ Qöşiliş»ni bosadi.\n"
    "4. Xona egasi «▶️ Boşlaş»ni bosadi — söz tuşuntiruvçiga "
    "şaxsiy xabar bilan keladi.\n\n"
    "🏆 Topgan öyinçiga +10, tuşuntiruvçiga +5 tanga."
)

BOMB_TEXT = (
    "💣 <b>Portlovçi Bomba</b>\n\n"
    "Karta öyini: bombani zararsizlantir, raqiblarga hujum qil va tirik qol! "
    "Har bir öyinçi bitta defuse va törtta harakat kartasi bilan boşlaydi.\n\n"
    "🎮 <b>Guruhda boşlaş:</b>\n"
    "1. Botni guruhingizga qöşing.\n"
    "2. Guruhda <code>/bomb</code> yuboring.\n"
    "3. Kamida 2 kişi «Qöşiliş»ni bosadi.\n"
    "4. Xona egasi öyinni boşlaydi — qöllar Mini App'da oçiladi.\n\n"
    "🏆 Oxirgi tirik qolgan öyinçiga +30 tanga."
)


MAFIA_TEXT = (
    "🕵️ <b>Mafiya</b>\n\n"
    "Şahar mafiyalar çangalida. Tunda yaşirin rollar harakat qiladi, "
    "kunduzi şahar aholisi ovoz berib mafiyani topişga harakat qiladi.\n\n"
    "🎮 <b>Guruhda boşlaş:</b>\n"
    "1. Botni guruhingizga qöşing.\n"
    "2. Guruhda <code>/mafia</code> yuboring.\n"
    "3. Kamida 4 kişi «Qöşiliş»ni bosadi.\n"
    "4. Xona egasi öyinni boşlaydi — rollar şaxsiy xabarda keladi."
)


def catalog_keyboard() -> InlineKeyboardMarkup:
    """Har bir o'yin alohida qatorda + guruhga qo'shish tugmasi."""
    config = get_config()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛡️ Bunker — /bunker", callback_data=BUNKER_CALLBACK
                )
            ],
            [
                InlineKeyboardButton(
                    text="🕵️ Mafiya — /mafia", callback_data=MAFIA_CALLBACK
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Josus (Spyfall) — /spy", callback_data=SPY_CALLBACK
                )
            ],
            [
                InlineKeyboardButton(
                    text="🐊 Alias / Krokodil — /alias",
                    callback_data=ALIAS_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="💣 Portlovçi Bomba — /bomb",
                    callback_data=BOMB_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏆 Haftalik turnirlar",
                    callback_data="tournaments_open",
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Botni guruhga qöşiş",
                    url=f"https://t.me/{config.bot_username}?startgroup=true",
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
                    text="➕ Guruhga qöşiş",
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
    """/games — barcha o'yinlar ro'yxati."""
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


@router.callback_query(F.data == ALIAS_CALLBACK)
async def show_alias(callback: CallbackQuery) -> None:
    """Alias qoidalari va guruhda boshlash yo'riqnomasi."""
    await callback.answer()
    await _edit_or_send(callback, ALIAS_TEXT, detail_keyboard())


@router.callback_query(F.data == BOMB_CALLBACK)
async def show_bomb(callback: CallbackQuery) -> None:
    """Portlovçi Bomba qoidalari va guruhda boshlash yo'riqnomasi."""
    await callback.answer()
    await _edit_or_send(callback, BOMB_TEXT, detail_keyboard())


@router.callback_query(F.data == BACK_CALLBACK)
async def back_to_catalog(callback: CallbackQuery) -> None:
    """Katalogga qaytish."""
    await callback.answer()
    await _edit_or_send(callback, CATALOG_TEXT, catalog_keyboard())
