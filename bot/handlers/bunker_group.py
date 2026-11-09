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
from core.i18n import resolve_language, t
from engine.game_manager import GameError, GameRoom, get_default_manager
from models.game import RoomStatus

logger = logging.getLogger(__name__)

router = Router(name="bunker_group")

JOIN_PREFIX = "join_"
START_PREFIX = "start_"

# Bunker xona kodlari doim ``BNK`` + 3 raqam (``BNK123``).  Turnir
# callbacklari (``join_tournament_TOURNAMENT_1``) ham ``join_`` bilan
# boshlangani uchun oddiy ``startswith("join_")`` filtr turnir
# ro'yxatdan o'tishni "xonaga qo'shilish" deb o'qib, bo'lmagan xonada
# "kodli xona topilmadi" xatosini chiqarardi.  Shuning uchun bunker
# handlerlari faqat haqiqiy Bunker kodlarini qabul qiladi.
JOIN_FILTER = r"^join_BNK\d{3}$"
START_FILTER = r"^start_BNK\d{3}$"


# ----------------------------------------------------------------------
# Matn va tugmalar
# ----------------------------------------------------------------------
def _room_text(room: GameRoom, *, started: bool = False, language: str = "uz") -> str:
    """Xona haqidagi guruh xabarini tayyorlaydi."""
    catastrophe = room.catastrophe or {}
    supplies = "\n".join(
        f"• {escape(str(item))}" for item in catastrophe.get("bunker_supplies", [])
    )
    requirements = "\n".join(
        f"• {escape(str(item))}" for item in catastrophe.get("survival_requirements", [])
    )

    lines = [
        t(language, "bunker_started_head")
        if started
        else t(language, "bunker_new_head"),
        "",
        f"☢️ <b>{escape(str(catastrophe.get('name', 'Falokat')))}</b>",
        "",
        escape(str(catastrophe.get("description", ""))),
        "",
        t(language, "bunker_supplies"),
        supplies or "• —",
        "",
        t(language, "bunker_requirements"),
        requirements or "• —",
        "",
        t(language, "bunker_room_code", code=room.code),
        t(language, "bunker_players", count=len(room.players), maximum=room.max_players),
        t(language, "bunker_capacity", capacity=room.bunker_capacity),
    ]
    if started or room.current_round:
        lines.append(t(language, "bunker_round", number=room.current_round))
    return "\n".join(lines)


def _room_keyboard(room: GameRoom, *, started: bool = False, language: str = "uz") -> InlineKeyboardMarkup:
    """Mini App va guruh harakatlari uchun inline tugmalar.

    Guruhlarda Telegram ``web_app`` tugmasini qabul qilmaydi
    (BUTTON_TYPE_INVALID), shuning uchun botning ``startapp`` havolasi
    ishlatiladi.
    """
    config = get_config()
    rows = [
        [
            InlineKeyboardButton(
                text=t(language, "btn_enter_bunker"),
                url=f"https://t.me/{config.bot_username}?startapp={room.code}",
            )
        ]
    ]
    if not started:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(language, "btn_join_group"),
                    callback_data=f"{JOIN_PREFIX}{room.code}",
                )
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(language, "btn_start"),
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
    text = _room_text(
        room,
        started=_is_started(room),
        language=resolve_language(
            int(getattr(room, "host_id", 0) or 0)
        ),
    )
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
            raise ValueError("Buyruq yuborgan foydalanuvçi aniqlanmadi")

        logger.info(
            "Guruhda yangi Bunker xonasi: çat=%s user=%s",
            message.chat.id,
            user.id,
        )
        room = get_default_manager().create_room(
            host_id=user.id,
            host_name=user.full_name,
            host_username=user.username or "",
        )
        header = t(resolve_language(user.id, getattr(user, "language_code", None)), "room_created", game="Bunker", waiting=len(room.players))
        await message.answer(header + "\n\n" + _room_text(room), reply_markup=_room_keyboard(room))
    except Exception as exc:  # bitta xato butun buyruqni jim yutmasligi kerak
        logger.exception("Guruhda /bunker buyruğini bajarişda xatolik: %s", exc)
        await message.reply(f"⚠️ Xatolik yuz berdi: {escape(str(exc))}")


@router.message(F.chat.type == "private", Command("bunker", "newgame"))
async def create_game_private(message: Message) -> None:
    """Shaxsiy chatda /bunker — guruhga yo'naltirish."""
    await message.answer(
        "Bunker öyinini faqat guruhda oçiş mumkin.\n"
        "Guruhga ötib /bunker buyruğini yuboring."
    )


@router.callback_query(F.data.regexp(JOIN_FILTER))
async def join_game(callback: CallbackQuery) -> None:
    """«Guruh orqali qo'shilish» tugmasi."""
    code = _callback_code(callback.data, JOIN_PREFIX)
    if code is None:
        await callback.answer("Notöğri tugma.", show_alert=True)
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

    language = resolve_language(user.id, getattr(user, "language_code", None))
    await callback.answer(t(language, "room_joined", name=escape(player.full_name)))
    await callback.bot.send_message(
        _chat_id(callback),
        f"➕ <b>{escape(player.full_name)}</b> qöşildi "
        f"(jami: {len(room.players)} kişi).",
    )
    await _refresh_room_message(callback, room)


@router.callback_query(F.data.regexp(START_FILTER))
async def start_game_callback(callback: CallbackQuery) -> None:
    """«O'yinni boshlash» tugmasi — faqat host uchun."""
    code = _callback_code(callback.data, START_PREFIX)
    if code is None:
        await callback.answer("Notöğri tugma.", show_alert=True)
        return

    user = callback.from_user
    manager = get_default_manager()
    try:
        room = manager.get_room(code)
        if user.id != room.host_id:
            await callback.answer(
                "Öyinni faqat xona egasi boşlaşi mumkin.",
                show_alert=True,
            )
            return
        room = manager.start_game(code)
    except GameError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    language = resolve_language(user.id, getattr(user, "language_code", None))
    await callback.answer(t(language, "room_started", game="Bunker"))
    announcement = (
        "🎬 <b>Öyin boşlandi!</b>\n\n"
        f"🔑 Xona kodi: <code>{room.code}</code>\n"
        f"👥 Öyinçilar: {len(room.players)} kişi\n"
        f"🏠 Bunker siğimi: {room.bunker_capacity} kişi\n\n"
        "Har bir öyinçi pastdagi tugma orqali Mini App'ga kirib, "
        "öz kartalarini körsin. Omad! 🍀"
    )
    await callback.bot.send_message(
        _chat_id(callback),
        announcement,
        reply_markup=_room_keyboard(room, started=True),
    )
    await _refresh_room_message(callback, room)
