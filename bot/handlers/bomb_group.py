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


def lobby_text(room: BombRoom) -> str:
    """Guruhdagi lobbi xabari."""
    return (
        "💣 <b>PORTLOVÇI BOMBA</b>\n"
        "Bombani zararsizlantir, raqiblarga hujum qil va tirik qol!\n\n"
        f"👥 Qatnaşuvçilar: {_player_names(room)}\n"
        f"🔢 Jami: {len(room.players)}/{MAX_PLAYERS} kişi\n"
        f"🔑 Xona kodi: <code>{room.code}</code>\n\n"
        f"ℹ️ {MIN_PLAYERS}–{MAX_PLAYERS} kişi. Xona egasi öyinni boşlaydi, "
        "qolganlar Mini App'dagi qöllarini oçadi."
    )


def lobby_keyboard(room: BombRoom) -> InlineKeyboardMarkup:
    """Mini App havolasi, qo'shilish va boshlash."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚪 Bombaga kiriş",
                    url=_startapp(room.code),
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Qöşiliş",
                    callback_data=f"{JOIN_PREFIX}{room.code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="▶️ Öyinni boşlaş",
                    callback_data=f"{START_PREFIX}{room.code}",
                )
            ],
        ]
    )


def playing_keyboard(room: BombRoom) -> InlineKeyboardMarkup:
    """O'yin davomida Mini App'ga olib kiruvchi tugma."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🃏 Qölni oçiş / karta öynaş",
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


def _winner_line(room: BombRoom, winner_id: int | None) -> str:
    if winner_id is None:
        return "🏁 Öyin yakunlandi — ğolib aniqlanmadi."
    winner = room.players.get(winner_id)
    name = escape(winner.label()) if winner is not None else f"ID {winner_id}"
    return f"🏆 <b>{name} ğalaba qozondi!</b> +{room.winner_reward} tanga."


def _target_name(room: BombRoom, target_id: int | None) -> str:
    if target_id is None:
        return "—"
    target = room.players.get(target_id)
    return escape(target.label()) if target is not None else f"ID {target_id}"


async def announce_room(bot: Bot, room: BombRoom, event: str) -> None:
    """O'yin boshlanganda yoki yakunlanganda guruhga e'lon yuboradi."""
    if not room.chat_id:
        return
    if event == "start":
        current = room.players.get(room.current_player_id or 0)
        current_name = escape(current.label()) if current is not None else "—"
        text = (
            "🎬 <b>PORTLOVÇI BOMBA BOŞLANDI!</b>\n\n"
            f"🔑 Xona kodi: <code>{room.code}</code>\n"
            f"👥 Öyinçilar: {len(room.players)} kişi\n"
            f"🎯 Birinçi navbat: <b>{current_name}</b>\n"
            f"🂠 Dastada {len(room.deck)} ta karta\n\n"
            "🃏 Har kim Mini App'dan öz qölini oçsin. Navbatdagilar karta "
            "öynaşi va oxirida bitta karta tortişi kerak. Bomba çiqsa — "
            "defuse bölsa qutqaradi, bölsa portlaysiz!"
        )
        keyboard = playing_keyboard(room)
    else:
        text = (
            "🏁 <b>PORTLOVÇI BOMBA YAKUNLANDI</b>\n\n"
            f"{_winner_line(room, room.winner_id)}\n\n"
            "Yangi öyin uçun guruhda <code>/bomb</code> yuboring."
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
) -> None:
    """Har bir tortish yoki karta öynaşni guruhga e'lon qiladi."""
    if not room.chat_id:
        return
    actor = room.players.get(result.player_id)
    actor_name = escape(actor.label()) if actor is not None else f"ID {result.player_id}"

    if isinstance(result, DrawResult):
        if result.card is None:
            text = "🂠 Dasta tugadi — öyin yakunlandi."
        elif result.exploded:
            text = (
                f"💥 <b>{actor_name} portladi!</b>\n"
                "Bomba çiqdi, qölida Zararsizlantiriş bölmadi."
            )
        elif result.awaiting_defuse:
            text = (
                f"💣 <b>{actor_name}</b> bomba tortdi, lekin qölida "
                "Zararsizlantiriş bor! Mini App'da bombani tepaga, örtaga "
                "yoki tagiga yaşirişni tanlasi."
            )
        elif result.defused:
            place = {0: "tepasiga", 1: "örtasiga"}.get(result.returned_index or 0)
            if place is None:
                place = "tagiga"
            text = (
                f"🛡️ <b>{actor_name}</b> Zararsizlantiriş işlatdi — "
                f"bomba dastaning {place} yaşirildi."
            )
        else:
            text = (
                f"🃏 <b>{actor_name}</b> karta tortdi: "
                f"{card_symbol(result.card)} {escape(card_name(result.card))}"
            )
    else:
        card = result.card
        text = f"🎴 <b>{actor_name}</b> «{escape(card_name(card))}» öynadi."
        if card is CardType.ATTACK:
            draws = max(2, 2 * int(room.attack_stack or 1))
            text += (
                f"\n⚔️ Navbat {_target_name(room, result.target_id)}ga ötdi — "
                f"u {draws} marta karta tortadi."
            )
        elif card is CardType.SKIP:
            text += "\n⏭️ Navbat keyingi öyinçiga ötdi."
        elif card is CardType.FUTURE:
            text += "\n🔮 Dastaning yuqori 3 kartasi faqat unga körsätildi."
        elif card is CardType.SHUFFLE:
            text += "\n🔀 Dasta aralaştirildi."
        elif card is CardType.STEAL:
            text += (
                f"\n🖐️ {_target_name(room, result.target_id)}dan bitta karta "
                "öğirlandi."
            )

    if result.game_over:
        text += f"\n\n{_winner_line(room, result.winner_id)}"
    elif result.next_player_id is not None:
        nxt = room.players.get(result.next_player_id)
        if nxt is not None:
            text += f"\n➡️ Navbat: <b>{escape(nxt.label())}</b>"

    keyboard = None if result.game_over else playing_keyboard(room)
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
        await message.answer(lobby_text(room), reply_markup=lobby_keyboard(room))
    except BombRoomError as exc:
        await message.reply(f"⚠️ {escape(str(exc))}")
    except Exception:
        logger.exception("Guruhda /bomb buyruğida xatolik")
        await message.reply("⚠️ Xatolik yuz berdi, keyinroq qayta urinib köring.")


@router.message(F.chat.type == "private", Command("bomb"))
async def create_bomb_game_private(message: Message) -> None:
    """Shaxsiy chatda /bomb — guruhga yo'naltirish."""
    await message.answer(
        "💣 Bombani guruhda öynaş kerak.\n"
        "Botni guruhga qöşib, u yerda /bomb yuboring."
    )


@router.callback_query(F.data.startswith(JOIN_PREFIX))
async def join_bomb_game(callback: CallbackQuery) -> None:
    """«➕ Qo'shilish» tugmasi."""
    code = _callback_code(callback.data, JOIN_PREFIX)
    if code is None:
        await callback.answer("Notöğri tugma.", show_alert=True)
        return
    user = callback.from_user
    try:
        room = get_default_manager().join(code, user.id, user.full_name)
    except BombRoomError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Bombaga qöşildingiz!")
    await _edit_or_send(callback, lobby_text(room), lobby_keyboard(room))


@router.callback_query(F.data.startswith(START_PREFIX))
async def start_bomb_game(callback: CallbackQuery) -> None:
    """«▶️ O'yinni boshlash» — faqat xona egasi."""
    code = _callback_code(callback.data, START_PREFIX)
    if code is None:
        await callback.answer("Notöğri tugma.", show_alert=True)
        return
    try:
        room = get_default_manager().start(code, callback.from_user.id)
    except BombRoomError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Öyin boşlandi!")
    await announce_room(callback.bot, room, "start")
    await _edit_or_send(
        callback,
        "🎬 <b>Öyin boşlandi!</b>\n\n"
        f"🔑 Xona kodi: <code>{room.code}</code>\n"
        "Qölingizni pastdagi tugma orqali Mini App'da oçing.",
        playing_keyboard(room),
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
