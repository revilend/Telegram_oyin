"""🎯 Missiyalar: topshiriqlar ro'yxati va mukofotlarni olish."""

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

from bot.keyboards.main_menu import MISSIONS_BUTTON
from core.economy import EconomyError, format_price, get_economy
from core.missions import (
    MissionStatus,
    claim_mission,
    mission_statuses,
)

logger = logging.getLogger(__name__)

router = Router(name="missions")

PRIVATE = F.chat.type == "private"
MISSION_CLAIM_PREFIX = "mission_claim_"


def _progress_bar(status: MissionStatus) -> str:
    """``▓▓▓░░`` ko'rinishidagi taraqqiyot chizig'i."""
    filled = min(5, int(round(status.percent / 20)))
    return "▓" * filled + "░" * (5 - filled)


def missions_text(statuses: list[MissionStatus]) -> str:
    """Missiyalar ro'yxati: taraqqiyot, maqsad va mukofot."""
    lines = [
        "🎯 <b>Missiyalar</b>",
        "",
        "Topshiriqlarni bajaring va tanga ishlang!",
        "",
    ]
    for index, status in enumerate(statuses, start=1):
        mission = status.mission
        if status.claimed:
            mark = "✅ olindi"
        elif status.completed:
            mark = "🎁 tayyor"
        else:
            mark = f"{status.progress}/{mission.target}"
        lines.append(
            f"{index}. {mission.emoji} <b>{escape(mission.title)}</b> — "
            f"+{format_price(mission.reward)} 🪙\n"
            f"    {escape(mission.description)}\n"
            f"    {_progress_bar(status)} {mark}"
        )
    ready = sum(1 for status in statuses if status.claimable)
    lines.append("")
    lines.append(
        f"🎁 Olinishi mumkin: <b>{ready}</b> ta mukofot"
        if ready
        else "Hozircha tayyor mukofot yo'q — o'ynab davom eting!"
    )
    return "\n".join(lines)


def missions_keyboard(statuses: list[MissionStatus]) -> InlineKeyboardMarkup:
    """Tayyor missiyalar uchun «tanga olish» tugmalari."""
    rows = [
        [
            InlineKeyboardButton(
                text=f"🎁 +{format_price(status.mission.reward)} tangani olish",
                callback_data=f"{MISSION_CLAIM_PREFIX}{status.mission.key}",
            )
        ]
        for status in statuses
        if status.claimable
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _statuses(user_id: int) -> list[MissionStatus]:
    return mission_statuses(get_economy(), user_id)


async def show_missions(message: Message) -> None:
    """Missiyalar ro'yxatini yuboradi."""
    user = message.from_user
    if user is None:
        return
    try:
        statuses = _statuses(user.id)
    except Exception:
        logger.exception("Missiyalarni yuklab bo'lmadi: %s", user.id)
        await message.answer(
            "⚠️ Missiyalarni yuklab bo'lmadi. Birozdan keyin urinib ko'ring."
        )
        return
    await message.answer(
        missions_text(statuses), reply_markup=missions_keyboard(statuses)
    )


@router.message(PRIVATE, Command("missions"))
@router.message(PRIVATE, F.text == MISSIONS_BUTTON)
async def missions_command(message: Message) -> None:
    """🎯 Missiyalar tugmasi va /missions buyrug'i."""
    await show_missions(message)


@router.callback_query(F.data.startswith(MISSION_CLAIM_PREFIX))
async def claim_mission_reward(callback: CallbackQuery) -> None:
    """«🎁 +N tangani olish» tugmasi."""
    key = (callback.data or "")[len(MISSION_CLAIM_PREFIX) :].strip()
    user = callback.from_user
    try:
        status, account = claim_mission(get_economy(), user.id, key)
    except EconomyError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except Exception:
        logger.exception("Missiya mukofotini berib bo'lmadi: %s", user.id)
        await callback.answer(
            "⚠️ Mukofotni hozircha olib bo'lmadi. Qayta urinib ko'ring.",
            show_alert=True,
        )
        return

    await callback.answer(
        f"🎁 +{format_price(status.mission.reward)} tanga! "
        f"Balans: {format_price(account.coins)}",
        show_alert=True,
    )
    try:
        statuses = _statuses(user.id)
    except Exception:
        logger.exception("Missiyalarni yangilab bo'lmadi: %s", user.id)
        return
    text = missions_text(statuses)
    keyboard = missions_keyboard(statuses)
    message = callback.message
    if message is not None and hasattr(message, "edit_text"):
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            logger.debug("Missiya xabarini tahrirlab bo'lmadi, yangi xabar yuboriladi")
    await callback.bot.send_message(
        callback.from_user.id, text, reply_markup=keyboard
    )


__all__ = [
    "MISSION_CLAIM_PREFIX",
    "claim_mission_reward",
    "missions_command",
    "missions_keyboard",
    "missions_text",
    "router",
    "show_missions",
]
