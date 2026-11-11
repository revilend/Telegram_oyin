"""Guruhda «Portlovçi Bomba» xonasini ochish va harakatlarni e'lon qilish.

``/bomb`` guruhda lobbi ochadi. O'yin Mini App'da öynaladi; har bir tortish
va karta öynaş API orqali kelib, shu modul orqali guruhga e'lon qilinadi.
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
from games.bomb.cards import CardType, card_name, card_symbol
from games.bomb.engine import ActionResult, BombRoom, DrawResult
from games.bomb.generator import MAX_PLAYERS, MIN_PLAYERS
from games.bomb.manager import BombRoomError, get_default_manager

logger = logging.getLogger(__name__)

router = Router(name="bomb_group")

JOIN_PREFIX = "bomb_join_"
START_PREFIX = "bomb_start_"


def _bot_username() -> str:
    return (get_config().bot_username or "revilend_gamesbot").lstrip("@")


def _startapp(code: str) -> str:
    return f"https://t.me/{_bot_username()}?startapp=bomb_{code}"


def _player_names(room: BombRoom) -> str:
    labels = []
    for player in room.players.values():
        marker = "👑 " if player.user_id == room.host_id else ""
        labels.append(f"{marker}{escape(player.label())}")
    return ", ".join(labels) or "—"


def _room_language(room: BombRoom) -> str:
    host_id = int(getattr(room, "host_id", 0) or 0)
    return resolve_language(host_id) if host_id else "uz"


def lobby_text(room: BombRoom, language: str = "uz") -> str:
    """Guruhdagi lobbi xabari."""
    return t(
        language, "bomb_lobby",
        players=_player_names(room), count=len(room.players), maximum=MAX_PLAYERS,
        code=room.code, minimum=MIN_PLAYERS,
    )


def lobby_keyboard(room: BombRoom, language: str = "uz") -> InlineKeyboardMarkup:
    """Mini App havolasi, qo'shilish va boshlash."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_enter_bomb"),
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


def playing_keyboard(room: BombRoom, language: str = "uz") -> InlineKeyboardMarkup:
    """O'yin davomida Mini App'ga olib kiruvchi tugma."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "btn_open_hand"),
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
    callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None
) -> None:
    message = callback.message
    if isinstance(message, Message):
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            pass
    await callback.bot.send_message(
        _chat_id(callback), text, reply_markup=keyboard
    )


def _winner_line(
    room: BombRoom, winner_id: int | None, language: str = "uz"
) -> str:
    if winner_id is None:
        return t(language, "bomb_winner_none")
    winner = room.players.get(winner_id)
    name = escape(winner.label()) if winner is not None else f"ID {winner_id}"
    return t(language, "bomb_winner", name=name, reward=room.winner_reward)


def _target_name(room: BombRoom, target_id: int | None) -> str:
    if target_id is None:
        return "—"
    target = room.players.get(target_id)
    return escape(target.label()) if target is not None else f"ID {target_id}"


async def announce_room(
    bot: Bot, room: BombRoom, event: str, language: str | None = None
) -> None:
    """O'yin boshlanganda yoki yakunlanganda guruhga e'lon yuboradi."""
    if not room.chat_id:
        return
    lang = language or _room_language(room)
    if event == "start":
        current = room.players.get(room.current_player_id or 0)
        current_name = escape(current.label()) if current is not None else "—"
        text = t(
            lang,
            "bomb_announce_start",
            code=room.code,
            players=len(room.players),
            current=current_name,
            deck=len(room.deck),
        )
        keyboard = playing_keyboard(room, lang)
    else:
        text = t(
            lang,
            "bomb_finished",
            winner=_winner_line(room, room.winner_id, lang),
        )
        keyboard = None
    try:
        await bot.send_message(room.chat_id, text, reply_markup=keyboard)
    except Exception:
        logger.exception("Bomb e'lonini guruhga yuborib bölmadi: %s", room.chat_id)


async def announce_action(
    bot: Bot,
    room: BombRoom,
    result: DrawResult | ActionResult,
    language: str | None = None,
) -> None:
    """Har bir tortish yoki karta öynaşni guruhga e'lon qiladi."""
    if not room.chat_id:
        return
    lang = language or _room_language(room)
    actor = room.players.get(result.player_id)
    actor_name = escape(actor.label()) if actor is not None else f"ID {result.player_id}"

    if isinstance(result, DrawResult):
        if result.card is None:
            text = t(lang, "bomb_deck_empty")
        elif result.exploded:
            text = t(lang, "bomb_exploded", name=actor_name)
        elif result.awaiting_defuse:
            text = t(lang, "bomb_awaiting_defuse", name=actor_name)
        elif result.defused:
            place_key = {
                0: "bomb_place_top",
                1: "bomb_place_mid",
            }.get(result.returned_index or 0, "bomb_place_bottom")
            text = t(
                lang,
                "bomb_defused",
                name=actor_name,
                place=t(lang, place_key),
            )
        else:
            text = t(
                lang,
                "bomb_draw",
                name=actor_name,
                symbol=card_symbol(result.card),
                card=escape(card_name(result.card)),
            )
    else:
        card = result.card
        text = t(
            lang, "bomb_played", name=actor_name, card=escape(card_name(card))
        )
        if card is CardType.ATTACK:
            draws = max(2, 2 * int(room.attack_stack or 1))
            text += t(
                lang,
                "bomb_attack",
                target=_target_name(room, result.target_id),
                draws=draws,
            )
        elif card is CardType.SKIP:
            text += t(lang, "bomb_skip")
        elif card is CardType.FUTURE:
            text += t(lang, "bomb_future")
        elif card is CardType.SHUFFLE:
            text += t(lang, "bomb_mix")
        elif card is CardType.STEAL:
            text += t(
                lang, "bomb_steal", target=_target_name(room, result.target_id)
            )

    if result.game_over:
        text += "\n\n" + _winner_line(room, result.winner_id, lang)
    elif result.next_player_id is not None:
        nxt = room.players.get(result.next_player_id)
        if nxt is not None:
            text += t(lang, "bomb_turn", name=escape(nxt.label()))

    keyboard = None if result.game_over else playing_keyboard(room, lang)
    try:
        await bot.send_message(room.chat_id, text, reply_markup=keyboard)
    except Exception:
        logger.exception("Bomb harakatini guruhga yuborib bölmadi: %s", room.chat_id)


@router.message(
    F.chat.type.in_({"group", "supergroup"}), Command("bomb")
)
async def create_bomb_game(message: Message) -> None:
    """/bomb — guruhda yangi lobbi ochadi."""
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
    except BombRoomError as exc:
        await message.reply(f"⚠️ {escape(str(exc))}")
    except Exception:
        logger.exception("Guruhda /bomb buyruğida xatolik")
        await message.reply(
            t(
                resolve_language(user.id, getattr(user, "language_code", None)),
                "error_generic",
            )
        )


@router.message(F.chat.type == "private", Command("bomb"))
async def create_bomb_game_private(message: Message) -> None:
    """Shaxsiy chatda /bomb — guruhga yo'naltirish."""
    user = message.from_user
    language = resolve_language(
        user.id if user is not None else None,
        getattr(user, "language_code", None) if user is not None else None,
    )
    await message.answer(t(language, "bomb_private_hint"))


@router.callback_query(F.data.startswith(JOIN_PREFIX))
async def join_bomb_game(callback: CallbackQuery) -> None:
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
    except BombRoomError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    language = resolve_language(user.id, getattr(user, "language_code", None))
    await callback.answer(t(language, "room_joined", name=escape(user.full_name)))
    await _edit_or_send(callback, lobby_text(room, _room_language(room)), lobby_keyboard(room, _room_language(room)))


@router.callback_query(F.data.startswith(START_PREFIX))
async def start_bomb_game(callback: CallbackQuery) -> None:
    """«▶️ O'yinni boshlash» — faqat xona egasi."""
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
    except BombRoomError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    language = resolve_language(
        callback.from_user.id, getattr(callback.from_user, "language_code", None)
    )
    await callback.answer(t(language, "room_started", game="Bomba"))
    await announce_room(callback.bot, room, "start")
    await _edit_or_send(
        callback,
        t(language, "bomb_start_brief", code=room.code),
        playing_keyboard(room, language),
    )


__all__ = [
    "JOIN_PREFIX",
    "START_PREFIX",
    "announce_action",
    "announce_room",
    "create_bomb_game",
    "lobby_keyboard",
    "lobby_text",
    "playing_keyboard",
    "router",
]
