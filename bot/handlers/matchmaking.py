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
    WebAppInfo,
)

from bot.config import get_config
from bot.keyboards.main_menu import MATCHMAKING_BUTTON
from core.i18n import resolve_language, t
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

CHOOSE_TEXT = t("uz", "mm_pick")

GAME_ORDER = ("bunker", "mafia", "spyfall", "alias", "bomb")

# Eski UZ yorliqlar (orqaga moslik); tilga xos matn ``t()`` dan olinadi.
GAME_LABELS = {kind: t("uz", f"mm_game_{kind}") for kind in GAME_ORDER}


def game_keyboard(language: str = "uz") -> InlineKeyboardMarkup:
    """O'yin turini tanlash tugmalari."""
    rows = [
        [
            InlineKeyboardButton(
                text=t(language, f"mm_game_{kind}"),
                callback_data=f"{GAME_PREFIX}{kind}",
            )
        ]
        for kind in GAME_ORDER
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_keyboard(kind: str, language: str = "uz") -> InlineKeyboardMarkup:
    """Navbatda turgan foydalanuvchi uchun bekor qilish tugmasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "mm_cancel_queue"),
                    callback_data=f"{CANCEL_CALLBACK}_{kind}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "mm_other_game"), callback_data=HOME_CALLBACK
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


def match_keyboard(
    match: dict[str, Any], *, web_app: bool = True, language: str = "uz"
) -> InlineKeyboardMarkup:
    """Tayyor xonaga kirish tugmasi.

    ``web_app=True`` bo'lsa Telegram Mini App to'g'ridan-to'g'ri ochiladi va
    foydalanuvchi «Havolani ochish» oynasini körmaydi. Guruh chatlarida
    Telegram web_app inline tugmasini qabul qilmasligi mumkin: chaqiruvchi
    ``TelegramBadRequest``ni tutib, ``web_app=False`` bilan qayta yuboradi.
    """
    code = str(match.get("code") or "")
    url = mini_app_room_url(code) or str(match.get("join_url") or "")
    label = t(language, "mm_join_game")
    if web_app and url.startswith("https://"):
        row = [InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))]
    else:
        row = [InlineKeyboardButton(text=label, url=url)]
    return InlineKeyboardMarkup(inline_keyboard=[row])


def match_text(match: dict[str, Any], language: str = "uz") -> str:
    """Navbat to'lganda yuboriladigan xabar matni."""
    kind = str(match.get("game_type") or "")
    title = (
        t(language, f"mm_game_{kind}")
        if kind in GAME_ORDER
        else t(language, "mm_game_default")
    )
    code = str(match.get("code") or "")
    players = int(match.get("players") or 0)
    return t(language, "mm_match", title=title, code=code, players=players)


def queue_text(kind: str, result: dict[str, Any], language: str = "uz") -> str:
    """Navbatga qo'shilgan foydalanuvchiga ko'rsatiladigan holat."""
    title = t(language, f"mm_game_{kind}") if kind in GAME_ORDER else t(
        language, "mm_game_default"
    )
    count = int(result.get("count") or 0)
    need = int(result.get("need") or 0)
    minimum = int(MIN_PLAYERS.get(kind, 0))
    text = t(
        language,
        "mm_queue",
        title=title,
        count=count,
        minimum=minimum,
    )
    if need > 0:
        text += t(language, "mm_queue_need", need=need)
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
    bot: Any,
    players: list[dict[str, Any]],
    match: dict[str, Any],
    language: str = "uz",
) -> None:
    """Navbatdagi barcha o'yinchilarga xona havolasini shaxsiy yuboradi."""
    text = match_text(match, language)
    for entry in players:
        user_id = int(entry.get("user_id") or 0)
        if user_id <= 0:
            continue
        try:
            await bot.send_message(
                user_id,
                text,
                reply_markup=match_keyboard(match, language=language),
            )
        except TelegramBadRequest:
            # Guruh/eski mijoz web_app tugmasini qabul qilmadi — oddiy havola.
            try:
                await bot.send_message(
                    user_id,
                    text,
                    reply_markup=match_keyboard(
                        match, web_app=False, language=language
                    ),
                )
            except Exception:
                logger.info("Navbat xabarini yuborib bölmadi: %s", user_id)
        except Exception:
            logger.info("Navbat xabarini yuborib bölmadi: %s", user_id)


@router.message(Command("matchmaking", "qidiruv"))
@router.message(F.chat.type == "private", F.text == MATCHMAKING_BUTTON)
async def matchmaking_menu(message: Message) -> None:
    """O'yin qidiruvini boshlaydi: o'yin turi tanlanadi."""
    user = message.from_user
    language = resolve_language(
        user.id if user is not None else None,
        getattr(user, "language_code", None) if user is not None else None,
    )
    await message.answer(
        t(language, "mm_pick"), reply_markup=game_keyboard(language)
    )


@router.callback_query(F.data.startswith(GAME_PREFIX))
async def choose_game(callback: CallbackQuery) -> None:
    """Tanlangan o'yin bo'yicha global navbatga qo'shiladi."""
    raw = str(callback.data or "")[len(GAME_PREFIX) :]
    language = resolve_language(
        getattr(callback.from_user, "id", None),
        getattr(callback.from_user, "language_code", None),
    )
    try:
        kind = normalize_game_type(raw)
    except Exception:
        await callback.answer(t(language, "mm_unknown_game"), show_alert=True)
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
        await callback.answer(t(language, "mm_join_failed"), show_alert=True)
        return

    await callback.answer(t(language, "mm_joined"))
    match = result.get("match")
    if match:
        try:
            await _edit_or_send(
                callback,
                match_text(match, language),
                match_keyboard(match, language=language),
            )
        except TelegramBadRequest:
            # Guruh chatlari web_app inline tugmasini qabul qilmaydi.
            await callback.bot.send_message(
                callback.from_user.id,
                match_text(match, language),
                reply_markup=match_keyboard(
                    match, web_app=False, language=language
                ),
            )
        return
    await _edit_or_send(
        callback,
        queue_text(kind, result, language),
        cancel_keyboard(kind, language),
    )


@router.callback_query(F.data.startswith(CANCEL_CALLBACK))
async def cancel_search(callback: CallbackQuery) -> None:
    """Foydalanuvchini navbatdan chiqaradi."""
    raw = str(callback.data or "")[len(CANCEL_CALLBACK) :].lstrip("_")
    language = resolve_language(
        getattr(callback.from_user, "id", None),
        getattr(callback.from_user, "language_code", None),
    )
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
        await callback.answer(t(language, "mm_error"), show_alert=True)
        return

    await callback.answer(t(language, "mm_queue_cancelled"))
    text = t(
        language,
        "mm_queue_cancelled" if result.get("left") else "mm_not_in_queue",
    )
    await _edit_or_send(callback, text, game_keyboard(language))


@router.callback_query(F.data == HOME_CALLBACK)
async def back_to_games(callback: CallbackQuery) -> None:
    """O'yin turini tanlashga qaytadi (navbatdan chiqmasdan)."""
    await callback.answer()
    language = resolve_language(
        getattr(callback.from_user, "id", None),
        getattr(callback.from_user, "language_code", None),
    )
    await _edit_or_send(
        callback, t(language, "mm_pick"), game_keyboard(language)
    )


async def check_matches_now() -> list[dict[str, Any]]:
    """Bazadagi navbatni tekshirib, yetilgan mosliklarni ochadi.

    ``api.server`` fon vazifasi shu funksiyani chaqiradi: bot qayta ishga
    tushgandan keyin ham Supabase'dagi navbat yo'qolmaydi.
    """
    return check_and_create_matches()
