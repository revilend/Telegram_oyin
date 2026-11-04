"""«🏆 Reyting va Top» — eng yaxshi o'yinchilar ro'yxati.

Foydalanuvchilar kam bo'lsa ham, baza bo'sh bo'lsa ham xato bermaydi:
bo'sh holatda iliq xabar ko'rsatiladi.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.handlers.profile import display_name, safe_int
from bot.keyboards.main_menu import LEADERBOARD_BUTTON
from core.economy import UserAccount, format_price, get_economy, player_rating
from core.leaderboard import weekly_stats, weekly_top

logger = logging.getLogger(__name__)

router = Router(name="leaderboard")

TOP_LIMIT = 10
EMPTY_TEXT = "Hozircha reyting bo'sh. Birinchi bo'lib o'yin boshlang!"
TITLE = "🏆 <b>Reyting va Top</b>"
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def leaderboard_text(
    top: list[UserAccount], me: UserAccount | None = None, *, weekly: bool = False
) -> str:
    """Reyting jadvali matni."""
    lines = [TITLE, "⚡ <b>Bu haftalik Liga</b>" if weekly else "🌟 <b>Barcha davrlar</b>", ""]
    if not top:
        lines.append(EMPTY_TEXT)
        return "\n".join(lines)

    for place, account in enumerate(top, start=1):
        prefix = MEDALS.get(place, f"{place}.")
        lines.append(
            f"{prefix} {escape(display_name(account))} — "
            f"<b>{format_price(account.weekly_score if weekly else player_rating(account))}</b> ball · "
            f"{safe_int(account.weekly_wins if weekly else account.wins)} g'alaba"
        )

    if me is not None:
        lines.append("")
        lines.append(
            f"📊 Sizning reytingingiz: <b>{format_price(me.weekly_score if weekly else player_rating(me))}</b> "
            f"({me.weekly_wins if weekly else me.wins} g'alaba, {me.games_played} o'yin)"
        )
    return "\n".join(lines)


@router.message(Command("top", "leaderboard", "reyting"))
@router.message(F.chat.type == "private", F.text == LEADERBOARD_BUTTON)
async def show_leaderboard(message: Message) -> None:
    """Top o'yinchilar ro'yxatini yuboradi."""
    user = message.from_user
    try:
        economy = get_economy()
        top = economy.top_users(TOP_LIMIT)
        me = economy.get_user(user.id) if user is not None else None
    except Exception as exc:  # xatoni yashirmaymiz
        logger.exception("Reyting xatosi")
        await message.answer(f"⚠️ Reyting xatosi: {escape(str(exc))}")
        return
    await message.answer(
        leaderboard_text(top, me),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="🌟 Barcha davrlar", callback_data="leaderboard:all"),
                InlineKeyboardButton(text="⚡ Bu haftalik Liga", callback_data="leaderboard:weekly"),
            ]]
        ),
    )


@router.callback_query(F.data.startswith("leaderboard:"))
async def switch_leaderboard(callback: CallbackQuery) -> None:
    """Botdagi reyting vkladkalarini almashtiradi."""
    weekly = callback.data == "leaderboard:weekly"
    try:
        economy = get_economy()
        top = weekly_top(TOP_LIMIT) if weekly else economy.top_users(TOP_LIMIT)
        me = economy.get_user(callback.from_user.id)
        if weekly:
            stats = weekly_stats(callback.from_user.id)
            me = replace(
                me,
                weekly_wins=stats["weekly_wins"],
                weekly_score=stats["weekly_score"],
            )
        text_value = leaderboard_text(top, me, weekly=weekly)
        await callback.message.edit_text(
            text_value,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="🌟 Barcha davrlar", callback_data="leaderboard:all"),
                    InlineKeyboardButton(text="⚡ Bu haftalik Liga", callback_data="leaderboard:weekly"),
                ]]
            ),
        )
        await callback.answer()
    except Exception:
        logger.exception("Reyting vkladkasini almashtirishda xatolik")
        await callback.answer("Reytingni yuklab bo'lmadi", show_alert=True)
