"""Guruhda «Bunker» xonasini ochish, qo'shilish va boshlash handlerlari."""

from __future__ import annotations

import logging
from html import escape

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
from engine.game_manager import GameError, GameRoom, get_default_manager
from models.game import RoomStatus

logger = logging.getLogger(__name__)

router = Router(name="bunker_group")

JOIN_PREFIX = "join_"
START_PREFIX = "start_"


# ----------------------------------------------------------------------
# Matn va tugmalar
# ----------------------------------------------------------------------
def _room_text(room: GameRoom, *, started: bool = False) -> str:
    """Xona haqidagi guruh xabarini tayyorlaydi."""
    catastrophe = room.catastrophe or {}
    supplies = "\n".join(
        f"• {escape(str(item))}" for item in catastrophe.get("bunker_supplies", [])
    )
    requirements = "\n".join(
        f"• {escape(str(item))}" for item in catastrophe.get("survival_requirements", [])
    )

    lines = [
        "🎬 <b>O'yin boshlandi!</b>" if started else "🆘 <b>Yangi Bunker o'yini</b>",
        "",
        f"☢️ <b>{escape(str(catastrophe.get('name', 'Falokat')))}</b>",
        "",
        escape(str(catastrophe.get("description", ""))),
        "",
        "📦 <b>Bunkerdagi zaxiralar:</b>",
        supplies or "• —",
        "",
        "✅ <b>Omon qolish talablari:</b>",
        requirements or "• —",
        "",
        f"🔑 <b>Xona kodi:</b> <code>{room.code}</code>",
        f"👥 <b>O'yinchilar:</b> {len(room.players)}/{room.max_players}",
        f"🏠 <b>Bunker sig'imi:</b> {room.bunker_capacity} kishi",
    ]
    if started or room.current_round:
        lines.append(f"🔄 <b>Raund:</b> {room.current_round}")
    return "\n".join(lines)


def _room_keyboard(room: GameRoom, *, started: bool = False) -> InlineKeyboardMarkup:
    """Mini App va guruh harakatlari uchun inline tugmalar.

    Guruhlarda Telegram ``web_app`` tugmasini qabul qilmaydi
    (BUTTON_TYPE_INVALID), shuning uchun botning ``startapp`` havolasi
    ishlatiladi.
    """
    config = get_config()
    rows = [
        [
            InlineKeyboardButton(
                text="🚪 Bunkerga kirish",
                url=f"https://t.me/{config.bot_username}?startapp={room.code}",
            )
        ]
    ]
    if not started:
        rows.append(
            [
                InlineKeyboardButton(
                    text="➕ Guruh orqali qo'shilish",
                    callback_data=f"{JOIN_PREFIX}{room.code}",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="▶️ O'yinni boshlash",
                    callback_data=f"{START_PREFIX}{room.code}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _is_started(room: GameRoom) -> bool:
    return room.status is not RoomStatus.LOBBY


def _chat_id(callback: CallbackQuery) -> int:
    if callback.message is not None:
        return callback.message.chat.id
    return callback.from_user.id


def _callback_code(data: str | None, prefix: str) -> str | None:
    if not data or not data.startswith(prefix):
        return None
    code = data[len(prefix) :].strip().upper()
    return code or None


async def _refresh_room_message(callback: CallbackQuery, room: GameRoom) -> None:
    """Xona kartasini yangilaydi; imkoni bo'lmasa yangi xabar yuboradi."""
    text = _room_text(room, started=_is_started(room))
    keyboard = _room_keyboard(room, started=_is_started(room))
    message = callback.message

    if isinstance(message, Message):
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            pass

    await callback.bot.send_message(_chat_id(callback), text, reply_markup=keyboard)


# ----------------------------------------------------------------------
# Handlerlar
# ----------------------------------------------------------------------
@router.message(F.chat.type.in_({"group", "supergroup"}), Command("bunker", "newgame"))
async def create_game(message: Message) -> None:
    """/bunker yoki /newgame — guruhda (shu jumladan superguruhda) xona ochadi."""
    try:
        user = message.from_user
        if user is None:
            raise ValueError("Buyruq yuborgan foydalanuvchi aniqlanmadi")

        logger.info(
            "Guruhda yangi Bunker xonasi: chat=%s user=%s",
            message.chat.id,
            user.id,
        )
        room = get_default_manager().create_room(
            host_id=user.id,
            host_name=user.full_name,
            host_username=user.username or "",
        )
        await message.answer(_room_text(room), reply_markup=_room_keyboard(room))
    except Exception as exc:  # bitta xato butun buyruqni jim yutmasligi kerak
        logger.exception("Guruhda /bunker buyrug'ini bajarishda xatolik: %s", exc)
        await message.reply(f"⚠️ Xatolik yuz berdi: {escape(str(exc))}")


@router.message(F.chat.type == "private", Command("bunker", "newgame"))
async def create_game_private(message: Message) -> None:
    """Shaxsiy chatda /bunker — guruhga yo'naltirish."""
    await message.answer(
        "Bunker o'yinini faqat guruhda ochish mumkin.\n"
        "Guruhga o'tib /bunker buyrug'ini yuboring."
    )


@router.callback_query(F.data.startswith(JOIN_PREFIX))
async def join_game(callback: CallbackQuery) -> None:
    """«Guruh orqali qo'shilish» tugmasi."""
    code = _callback_code(callback.data, JOIN_PREFIX)
    if code is None:
        await callback.answer("Noto'g'ri tugma.", show_alert=True)
        return

    user = callback.from_user
    manager = get_default_manager()
    try:
        player = manager.join_room(
            code=code,
            user_id=user.id,
            full_name=user.full_name,
            username=user.username or "",
        )
        room = manager.get_room(code)
    except GameError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer("Xonaga qo'shildingiz!")
    await callback.bot.send_message(
        _chat_id(callback),
        f"➕ <b>{escape(player.full_name)}</b> qo'shildi "
        f"(jami: {len(room.players)} kishi).",
    )
    await _refresh_room_message(callback, room)


@router.callback_query(F.data.startswith(START_PREFIX))
async def start_game_callback(callback: CallbackQuery) -> None:
    """«O'yinni boshlash» tugmasi — faqat host uchun."""
    code = _callback_code(callback.data, START_PREFIX)
    if code is None:
        await callback.answer("Noto'g'ri tugma.", show_alert=True)
        return

    user = callback.from_user
    manager = get_default_manager()
    try:
        room = manager.get_room(code)
        if user.id != room.host_id:
            await callback.answer(
                "O'yinni faqat xona egasi boshlashi mumkin.",
                show_alert=True,
            )
            return
        room = manager.start_game(code)
    except GameError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer("O'yin boshlandi!")
    announcement = (
        "🎬 <b>O'yin boshlandi!</b>\n\n"
        f"🔑 Xona kodi: <code>{room.code}</code>\n"
        f"👥 O'yinchilar: {len(room.players)} kishi\n"
        f"🏠 Bunker sig'imi: {room.bunker_capacity} kishi\n\n"
        "Har bir o'yinchi pastdagi tugma orqali Mini App'ga kirib, "
        "o'z kartalarini ko'rsin. Omad! 🍀"
    )
    await callback.bot.send_message(
        _chat_id(callback),
        announcement,
        reply_markup=_room_keyboard(room, started=True),
    )
    await _refresh_room_message(callback, room)
