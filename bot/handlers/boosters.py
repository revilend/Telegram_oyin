"""Qalqon taklifi va booster callback handlerlari."""

from __future__ import annotations

import logging
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import get_config
from core.billing import buy_booster, decline_shield
from core.economy import (
    EconomyError,
    InsufficientCoinsError,
    format_price,
    get_economy,
)
from engine.boosters import SHIELD, BoosterError
from engine.game_manager import GameError, get_default_manager
from models.game import GameRoom

logger = logging.getLogger(__name__)

router = Router(name="boosters")

SHIELD_YES_PREFIX = "shield_yes_"
SHIELD_NO_PREFIX = "shield_no_"


def shield_keyboard(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🛡️ Bunker Qalqonini işlatiş ({SHIELD.price} 🪙)",
                    callback_data=f"{SHIELD_YES_PREFIX}{code}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Rad etiş",
                    callback_data=f"{SHIELD_NO_PREFIX}{code}",
                )
            ],
        ]
    )


def shield_text(room: GameRoom) -> str:
    return (
        "🛡️ <b>Sizni bunkerdan haydaşmoqçi!</b>\n\n"
        f"Xona: <code>{escape(room.code)}</code>\n"
        f"Eng köp ovoz sizga berildi. <b>{SHIELD.price} tanga</b> evaziga "
        "«Bunker Qalqoni»ni faollaştirib, omon qolasizmi?\n\n"
        "Qalqon har bir xonada faqat bir marta işlaydi."
    )


async def send_shield_offer(bot, room: GameRoom) -> bool:
    """Qalqon taklifini o'yinchiga shaxsiy xabar orqali yuboradi."""
    offer = room.pending_shield
    if offer is None:
        return False
    try:
        await bot.send_message(
            offer.user_id,
            shield_text(room),
            reply_markup=shield_keyboard(room.code),
        )
        return True
    except TelegramAPIError:
        logger.exception("Qalqon taklifini yuborib bölmadi: %s", offer.user_id)
        return False


def _code(data: str, prefix: str) -> str | None:
    code = (data or "")[len(prefix) :].strip().upper()
    return code or None


def _edit_text(callback: CallbackQuery, text: str) -> None:
    if callback.message is None:
        return
    try:
        callback.message.edit_text(text)  # type: ignore[union-attr]
    except TelegramAPIError:
        pass


@router.callback_query(F.data.startswith(SHIELD_YES_PREFIX))
async def activate_shield(callback: CallbackQuery) -> None:
    code = _code(callback.data or "", SHIELD_YES_PREFIX)
    if code is None:
        await callback.answer("Notöğri tugma.", show_alert=True)
        return
    manager = get_default_manager()
    economy = get_economy()
    try:
        room = manager.get_room(code)
        offer = room.pending_shield
        if offer is None or offer.user_id != callback.from_user.id:
            await callback.answer("Bu qalqon taklifi sizga tegişli emas.", show_alert=True)
            return
        result = buy_booster(
            manager, economy, code, callback.from_user.id, SHIELD.key
        )
    except InsufficientCoinsError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except (GameError, BoosterError, EconomyError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer("Qalqon faollaştirildi!")
    text = (
        "🛡️ <b>Bunker Qalqoni faollaştirildi!</b>\n\n"
        f"Balansdan <b>{format_price(SHIELD.price)}</b> tanga yeçildi.\n"
        f"Qolgan balans: <b>{format_price(result.account_coins)}</b> tanga."
    )
    if result.eliminated is not None:
        text += (
            f"\n\nNavbatdagi nomzod <b>{escape(result.eliminated.full_name)}</b> "
            "bunkerdan haydaldi."
        )
    else:
        text += "\n\nOvozlar teng bölgani uçun bu raundda boşqa heç kim haydalmadi."
    _edit_text(callback, text)


@router.callback_query(F.data.startswith(SHIELD_NO_PREFIX))
async def reject_shield(callback: CallbackQuery) -> None:
    code = _code(callback.data or "", SHIELD_NO_PREFIX)
    if code is None:
        await callback.answer("Notöğri tugma.", show_alert=True)
        return
    manager = get_default_manager()
    try:
        room = manager.get_room(code)
        offer = room.pending_shield
        if offer is None or offer.user_id != callback.from_user.id:
            await callback.answer("Bu qalqon taklifi sizga tegişli emas.", show_alert=True)
            return
        _, player = decline_shield(manager, code, callback.from_user.id)
    except GameError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer("Qalqon rad etildi")
    _edit_text(
        callback,
        "❌ Qalqon işlatilmadi.\n\n"
        f"<b>{escape(player.full_name)}</b> bunkerdan haydaldi.",
    )
