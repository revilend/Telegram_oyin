"""Global o'yin qidiruvi (matchmaking) uchun bot interfeysi.

Foydalanuvchi menyudagi «🌐 O'yin qidirish» tugmasini yoki ``/matchmaking``
buyrug'ini bosganda o'yin turi tanlanadi, so'ng Supabase'dagi umumiy navbatga
qo'shiladi. Navbat yetarli o'yinchi bilan to'lganda xona ochiladi va barcha
ishtirokchilarga Mini App havolasi shaxsiy xabar bilan yuboriladi.

Bu modul xabarning matni va tugmalarini ham taqdim etadi: ``api.server``
navbat to'lganda ``send_match_notices`` orqali aynan shu xabarni yuboradi.
"""

from __future__ import annotations

import logging
from typing import Any

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
from bot.keyboards.main_menu import MATCHMAKING_BUTTON
from engine.matchmaking import (
    GAME_TITLES,
    MIN_PLAYERS,
    check_and_create_matches,
    join_global_queue,
    leave_global_queue,
    normalize_game_type,
)

logger = logging.getLogger(__name__)

router = Router(name="matchmaking")

GAME_PREFIX = "mm_game_"
CANCEL_CALLBACK = "mm_leave"
HOME_CALLBACK = "mm_home"

CHOOSE_TEXT = (
    "🌐 <b>Global öyin qidiruvi</b>\n\n"
    "Qaysi öyin uçun şerik qidirasiz? Navbat tölişi bilan barça "
    "iştirokçilarga xona havolasi yuboriladi."
)

GAME_LABELS = {
    "bunker": "🛡️ Bunker",
    "mafia": "🕵️ Mafiya",
    "alias": "🐊 Alias",
}


def game_keyboard() -> InlineKeyboardMarkup:
    """O'yin turini tanlash tugmalari."""
    rows = [
        [
            InlineKeyboardButton(
                text=GAME_LABELS[kind], callback_data=f"{GAME_PREFIX}{kind}"
            )
        ]
        for kind in ("bunker", "mafia", "alias")
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_keyboard(kind: str) -> InlineKeyboardMarkup:
    """Navbatda turgan foydalanuvchi uchun bekor qilish tugmasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Qidiruvni bekor qiliş",
                    callback_data=f"{CANCEL_CALLBACK}_{kind}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Boşqa öyin", callback_data=HOME_CALLBACK
                )
            ],
        ]
    )


def mini_app_room_url(code: str) -> str:
    """Mini App havolasini xona kodi bilan qaytaradi (``?room=``)."""
    try:
        return get_config().mini_app_link(code)
    except Exception:  # token yo'q muhitda ham havola kerak bo'ladi
        logger.debug("MINI_APP_URL konfiguratsiyasini olib bölmadi", exc_info=True)
        return ""


def match_keyboard(match: dict[str, Any]) -> InlineKeyboardMarkup:
    """Tayyor xonaga kirish tugmasi."""
    code = str(match.get("code") or "")
    url = mini_app_room_url(code) or str(match.get("join_url") or "")
    row = [InlineKeyboardButton(text="🎮 Xonaga kiriş", url=url)]
    return InlineKeyboardMarkup(inline_keyboard=[row])


def match_text(match: dict[str, Any]) -> str:
    """Navbat to'lganda yuboriladigan xabar matni."""
    title = GAME_TITLES.get(str(match.get("game_type") or ""), "Öyin")
    code = str(match.get("code") or "")
    players = int(match.get("players") or 0)
    return (
        f"✅ <b>{title}: jamoa yiğildi!</b>\n\n"
        f"Xona kodi: <code>{code}</code>\n"
        f"Öyinçilar: {players} kişi\n\n"
        "Havola orqali darhol qöşiling."
    )


def queue_text(kind: str, result: dict[str, Any]) -> str:
    """Navbatga qo'shilgan foydalanuvchiga ko'rsatiladigan holat."""
    title = GAME_TITLES.get(kind, "Öyin")
    count = int(result.get("count") or 0)
    need = int(result.get("need") or 0)
    minimum = int(MIN_PLAYERS.get(kind, 0))
    text = (
        f"⏳ Navbatga qöşildingiz! Odamlar yiğilişi bilan xabar beramiz "
        f"(Hozir navbatda: {count} kişi)...\n\n"
        f"🎮 Öyin: <b>{title}</b>\n"
        f"Kerakli öyinçi: {minimum} kişi"
    )
    if need > 0:
        text += f"\nYana {need} kişi kerak."
    return text


async def _edit_or_send(
    callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup
) -> None:
    """Callback xabarini tahrirlaydi, imkoni bo'lmasa yangi xabar yuboradi."""
    message = callback.message
    if message is not None and hasattr(message, "edit_text"):
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            pass
    chat_id = message.chat.id if message is not None else callback.from_user.id
    await callback.bot.send_message(chat_id, text, reply_markup=keyboard)


async def send_match_notices(
    bot: Any, players: list[dict[str, Any]], match: dict[str, Any]
) -> None:
    """Navbatdagi barcha o'yinchilarga xona havolasini shaxsiy yuboradi."""
    text = match_text(match)
    keyboard = match_keyboard(match)
    for entry in players:
        user_id = int(entry.get("user_id") or 0)
        if user_id <= 0:
            continue
        try:
            await bot.send_message(user_id, text, reply_markup=keyboard)
        except Exception:
            logger.info("Navbat xabarini yuborib bölmadi: %s", user_id)


@router.message(Command("matchmaking", "qidiruv"))
@router.message(F.chat.type == "private", F.text == MATCHMAKING_BUTTON)
async def matchmaking_menu(message: Message) -> None:
    """O'yin qidiruvini boshlaydi: o'yin turi tanlanadi."""
    await message.answer(CHOOSE_TEXT, reply_markup=game_keyboard())


@router.callback_query(F.data.startswith(GAME_PREFIX))
async def choose_game(callback: CallbackQuery) -> None:
    """Tanlangan o'yin bo'yicha global navbatga qo'shiladi."""
    raw = str(callback.data or "")[len(GAME_PREFIX) :]
    try:
        kind = normalize_game_type(raw)
    except Exception:
        await callback.answer("Noma'lum öyin turi", show_alert=True)
        return

    user = callback.from_user
    try:
        result = join_global_queue(
            user.id,
            kind,
            name=user.full_name,
            username=user.username or "",
        )
    except Exception:
        logger.exception("Navbatga qöşib bölmadi: %s", user.id)
        await callback.answer("Navbatga qöşilib bölmadi", show_alert=True)
        return

    await callback.answer("Navbatga qöşildingiz!")
    match = result.get("match")
    if match:
        await _edit_or_send(callback, match_text(match), match_keyboard(match))
        return
    await _edit_or_send(callback, queue_text(kind, result), cancel_keyboard(kind))


@router.callback_query(F.data.startswith(CANCEL_CALLBACK))
async def cancel_search(callback: CallbackQuery) -> None:
    """Foydalanuvchini navbatdan chiqaradi."""
    raw = str(callback.data or "")[len(CANCEL_CALLBACK) :].lstrip("_")
    kind: str | None = None
    if raw:
        try:
            kind = normalize_game_type(raw)
        except Exception:
            kind = None
    try:
        result = leave_global_queue(callback.from_user.id, kind)
    except Exception:
        logger.exception("Navbatdan çiqarib bölmadi: %s", callback.from_user.id)
        await callback.answer("Xatolik yuz berdi", show_alert=True)
        return

    await callback.answer("Qidiruv bekor qilindi")
    text = (
        "❌ Qidiruv bekor qilindi."
        if result.get("left")
        else "❌ Siz navbatda emassiz."
    )
    await _edit_or_send(callback, text, game_keyboard())


@router.callback_query(F.data == HOME_CALLBACK)
async def back_to_games(callback: CallbackQuery) -> None:
    """O'yin turini tanlashga qaytadi (navbatdan chiqmasdan)."""
    await callback.answer()
    await _edit_or_send(callback, CHOOSE_TEXT, game_keyboard())


async def check_matches_now() -> list[dict[str, Any]]:
    """Bazadagi navbatni tekshirib, yetilgan mosliklarni ochadi.

    ``api.server`` fon vazifasi shu funksiyani chaqiradi: bot qayta ishga
    tushgandan keyin ham Supabase'dagi navbat yo'qolmaydi.
    """
    return check_and_create_matches()
