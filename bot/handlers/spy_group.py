"""Guruhda «Josus» (Spyfall) xonasini ochish va e'lon qilish.

``/spy`` yoki ``/josus`` buyrug'i Bunker va Mafiyadagi kabi lobby ochadi.
Mini App'dagi o'yin oqimi bilan umumiy :class:`SpyfallManager` ishlatiladi,
shuning uchun botda ochilgan xona Mini App'da darhol ko'rinadi.
"""

from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
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
from games.spyfall.engine import (
    DOUBLE_SPY_MIN_PLAYERS,
    MAX_PLAYERS,
    MIN_PLAYERS,
    SpyfallRoom,
    Winner,
)
from games.spyfall.manager import SpyfallRoomError, get_default_manager

logger = logging.getLogger(__name__)

router = Router(name="spy_group")

JOIN_PREFIX = "spy_join_"
START_PREFIX = "spy_start_"

WINNER_LABELS: dict[Winner, str] = {
    Winner.PLAYERS: "TINÇ AHOLI",
    Winner.SPIES: "JOSUS",
}


def _startapp(code: str) -> str:
    return f"https://t.me/{get_config().bot_username}?startapp=spy_{code}"


def _players_list(room: SpyfallRoom) -> str:
    labels = []
    for player in room.players.values():
        name = escape(player.display_name())
        labels.append(f"{'👑 ' if player.is_host else ''}{name}")
    return ", ".join(labels) or "—"


def spy_count_for(player_count: int) -> int:
    """O'yinchilar soniga qarab josuslar soni."""
    return 2 if int(player_count) >= DOUBLE_SPY_MIN_PLAYERS else 1


def _room_language(room: SpyfallRoom) -> str:
    host_id = int(getattr(room, "host_id", 0) or 0)
    return resolve_language(host_id) if host_id else "uz"


def lobby_text(room: SpyfallRoom, language: str = "uz") -> str:
    """Guruhdagi lobby xabari."""
    count = len(room.players)
    spies = spy_count_for(count)
    return t(
        language, "spy_lobby",
        players=_players_list(room), count=count, maximum=MAX_PLAYERS,
        spies=spies, code=room.code, minimum=MIN_PLAYERS,
        double_min=DOUBLE_SPY_MIN_PLAYERS,
    )


def lobby_keyboard(room: SpyfallRoom, language: str = "uz") -> InlineKeyboardMarkup:
    """Mini App havolasi, qo'shilish va boshlash tugmalari."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_enter_spy"),
                    url=_startapp(room.code),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_join"),
                    callback_data=f"{JOIN_PREFIX}{room.code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(language, "btn_start"),
                    callback_data=f"{START_PREFIX}{room.code}",
                )
            ],
        ]
    )


def playing_keyboard(room: SpyfallRoom, language: str = "uz") -> InlineKeyboardMarkup:
    """O'yin davomidagi tugma: karta va ovoz berish Mini App'da."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_open_card"),
                    url=_startapp(room.code),
                )
            ]
        ]
    )


def _callback_code(data: str | None, prefix: str) -> str | None:
    if not data or not data.startswith(prefix):
        return None
    code = data[len(prefix) :].strip().upper()
    return code or None


def _chat_id(callback: CallbackQuery) -> int:
    if callback.message is not None:
        return callback.message.chat.id
    return callback.from_user.id


async def _edit_or_send(
    callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup
) -> None:
    message = callback.message
    if isinstance(message, Message):
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            pass
    await callback.bot.send_message(_chat_id(callback), text, reply_markup=keyboard)


# ----------------------------------------------------------------------
# E'lonlar (Mini App'dan ham chaqiriladi)
# ----------------------------------------------------------------------
async def announce_room(bot: Bot, room: SpyfallRoom, event: str) -> None:
    """O'yin boshlanganda va yakunlanganda guruhga jonli e'lon yuboradi."""
    if not room.chat_id:
        return
    language = _room_language(room)
    state = room.public_state()
    if event == "start":
        text = t(
            language,
            "spy_announce_start",
            code=room.code,
            players=len(room.players),
            spies=len(room.spy_ids),
            minutes=room.round_seconds // 60,
        )
        keyboard = playing_keyboard(room, language)
    else:
        winner = room.winner.value if room.winner else ""
        title = t(
            language,
            "spy_win_spies"
            if winner == Winner.SPIES.value
            else "spy_win_players",
        )
        location = state.get("location") or {}
        spies = [
            escape(room.players[uid].display_name())
            for uid in sorted(room.spy_ids)
            if uid in room.players
        ]
        text = t(
            language,
            "spy_result_head",
            title=title,
            reason=escape(room.finish_reason),
        )
        if location:
            text += t(
                language,
                "spy_result_place",
                emoji=escape(str(location.get("emoji") or "")),
                place=escape(str(location.get("name") or "")),
            )
        text += t(
            language,
            "spy_result_tail",
            spies=", ".join(spies) or "—",
            reward=60 if winner == Winner.SPIES.value else 30,
        )
        keyboard = None

    try:
        await bot.send_message(room.chat_id, text, reply_markup=keyboard)
    except Exception:  # e'lon yuborilmasa o'yin holati buzilmasin
        logger.exception("Josus e'lonini guruhga yuborib bölmadi: %s", room.chat_id)


# ----------------------------------------------------------------------
# Handlerlar
# ----------------------------------------------------------------------
@router.message(
    F.chat.type.in_({"group", "supergroup"}), Command("spy", "josus", "spyfall")
)
async def create_spy_game(message: Message) -> None:
    """/spy yoki /josus — guruhda yangi xona ochadi."""
    user = message.from_user
    if user is None:
        return
    try:
        room = get_default_manager().create_room(
            user.id,
            user.full_name,
            chat_id=message.chat.id,
        )
        await message.answer(lobby_text(room, _room_language(room)), reply_markup=lobby_keyboard(room, _room_language(room)))
    except SpyfallRoomError as exc:
        await message.reply(f"⚠️ {escape(str(exc))}")
    except Exception:
        logger.exception("Guruhda /spy buyruğida xatolik")
        await message.reply(
            t(
                resolve_language(user.id, getattr(user, "language_code", None)),
                "error_generic",
            )
        )


@router.message(F.chat.type == "private", Command("spy", "josus", "spyfall"))
async def create_spy_game_private(message: Message) -> None:
    """Shaxsiy chatda /spy — guruhga yo'naltirish."""
    user = message.from_user
    language = resolve_language(
        user.id if user is not None else None,
        getattr(user, "language_code", None) if user is not None else None,
    )
    await message.answer(t(language, "spy_private_hint"))


@router.callback_query(F.data.startswith(JOIN_PREFIX))
async def join_spy_game(callback: CallbackQuery) -> None:
    """«➕ Qo'shilish» tugmasi."""
    code = _callback_code(callback.data, JOIN_PREFIX)
    language = resolve_language(
        getattr(callback.from_user, "id", None),
        getattr(callback.from_user, "language_code", None),
    )
    if code is None:
        await callback.answer(t(language, "booster_wrong_button"), show_alert=True)
        return

    user = callback.from_user
    try:
        room = get_default_manager().join(code, user.id, user.full_name)
    except SpyfallRoomError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    language = resolve_language(user.id, getattr(user, "language_code", None))
    await callback.answer(t(language, "room_joined", name=escape(user.full_name)))
    await _edit_or_send(callback, lobby_text(room, _room_language(room)), lobby_keyboard(room, _room_language(room)))


@router.callback_query(F.data.startswith(START_PREFIX))
async def start_spy_game(callback: CallbackQuery) -> None:
    """«▶️ O'yinni boshlash» — faqat xona egasi uchun."""
    code = _callback_code(callback.data, START_PREFIX)
    language = resolve_language(
        getattr(callback.from_user, "id", None),
        getattr(callback.from_user, "language_code", None),
    )
    if code is None:
        await callback.answer(t(language, "booster_wrong_button"), show_alert=True)
        return

    try:
        room = get_default_manager().start(code, callback.from_user.id)
    except SpyfallRoomError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    language = resolve_language(
        callback.from_user.id, getattr(callback.from_user, "language_code", None)
    )
    await callback.answer(t(language, "room_started", game="Josus"))
    await announce_room(callback.bot, room, "start")
    await _edit_or_send(
        callback,
        t(
            language,
            "spy_start_brief",
            code=room.code,
            spies=len(room.spy_ids),
        ),
        playing_keyboard(room, language),
    )


__all__ = [
    "JOIN_PREFIX",
    "START_PREFIX",
    "announce_room",
    "create_spy_game",
    "lobby_keyboard",
    "lobby_text",
    "playing_keyboard",
    "router",
    "spy_count_for",
]
