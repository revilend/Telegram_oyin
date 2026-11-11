"""🎯 Missiyalar: topshiriqlar ro'yxati va mukofotlarni olish."""

from __future__ import annotations

import asyncio

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

from core.economy import EconomyError, format_price, get_economy
from core.i18n import all_button_texts, resolve_language, t
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


def missions_text(statuses: list[MissionStatus], language: str = "uz") -> str:
    """Missiyalar ro'yxati: taraqqiyot, maqsad va mukofot."""
    lines = [
        t(language, "missions_title"),
        "",
        t(language, "missions_intro"),
        "",
    ]
    for index, status in enumerate(statuses, start=1):
        mission = status.mission
        if status.claimed:
            mark = t(language, "missions_claimed")
        elif status.completed:
            mark = t(language, "missions_ready")
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
        t(language, "missions_ready_count", count=ready)
        if ready
        else t(language, "missions_none_ready")
    )
    return "\n".join(lines)


def missions_keyboard(
    statuses: list[MissionStatus], language: str = "uz"
) -> InlineKeyboardMarkup:
    """Tayyor missiyalar uchun «tanga olish» tugmalari."""
    rows = [
        [
            InlineKeyboardButton(
                text=t(
                    language,
                    "missions_claim_button",
                    reward=format_price(status.mission.reward),
                ),
                callback_data=f"{MISSION_CLAIM_PREFIX}{status.mission.key}",
            )
        ]
        for status in statuses
        if status.claimable
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _statuses(user_id: int) -> list[MissionStatus]:
    return mission_statuses(get_economy(), user_id)


async def _statuses_async(user) -> list[MissionStatus]:
    """Hisob va missiya yozuvlarini parallel o'qiydi (waterfall yo'q)."""
    economy = get_economy()
    account_for = getattr(economy, "account_for", None)
    claimed_of = getattr(economy, "claimed_missions", None)
    if not (callable(account_for) and callable(claimed_of)):
        return await asyncio.to_thread(_statuses, user.id)
    account, claimed = await asyncio.gather(
        asyncio.to_thread(
            account_for, user.id, user.username or "", user.full_name or ""
        ),
        asyncio.to_thread(claimed_of, user.id),
    )
    return mission_statuses(
        economy, user.id, account=account, claimed=claimed
    )


async def show_missions(message: Message) -> None:
    """Missiyalar ro'yxatini yuboradi."""
    user = message.from_user
    if user is None:
        return
    language = resolve_language(user.id, getattr(user, "language_code", None))
    try:
        statuses = await _statuses_async(user)
    except Exception:
        logger.exception("Missiyalarni yuklab bölmadi: %s", user.id)
        await message.answer(t(language, "missions_load_error"))
        return
    await message.answer(
        missions_text(statuses, language),
        reply_markup=missions_keyboard(statuses, language),
    )


@router.message(PRIVATE, Command("missions"))
@router.message(PRIVATE, F.text.in_(all_button_texts("missions")))
async def missions_command(message: Message) -> None:
    """🎯 Missiyalar tugmasi va /missions buyrug'i."""
    await show_missions(message)


@router.callback_query(F.data.startswith(MISSION_CLAIM_PREFIX))
async def claim_mission_reward(callback: CallbackQuery) -> None:
    """«🎁 +N tangani olish» tugmasi."""
    key = (callback.data or "")[len(MISSION_CLAIM_PREFIX) :].strip()
    user = callback.from_user
    language = resolve_language(
        getattr(user, "id", None), getattr(user, "language_code", None)
    )
    try:
        status, account = claim_mission(get_economy(), user.id, key)
    except EconomyError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except Exception:
        logger.exception("Missiya mukofotini berib bölmadi: %s", user.id)
        await callback.answer(
            t(language, "missions_claim_error"), show_alert=True
        )
        return

    await callback.answer(
        t(
            language,
            "missions_claim_alert",
            reward=format_price(status.mission.reward),
            balance=format_price(account.coins),
        ),
        show_alert=True,
    )
    try:
        statuses = _statuses(user.id)
    except Exception:
        logger.exception("Missiyalarni yangilab bölmadi: %s", user.id)
        return
    text = missions_text(statuses, language)
    keyboard = missions_keyboard(statuses, language)
    message = callback.message
    if message is not None and hasattr(message, "edit_text"):
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            logger.debug("Missiya xabarini tahrirlab bölmadi, yangi xabar yuboriladi")
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
