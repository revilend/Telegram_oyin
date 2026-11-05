"""«🏆 Reyting va Top» — eng yaxshi o'yinchilar ro'yxati.

Foydalanuvchilar kam bo'lsa ham, baza bo'sh bo'lsa ham xato bermaydi:
bo'sh holatda iliq xabar ko'rsatiladi.
"""

from __future__ import annotations

import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.handlers.profile import display_name, safe_int
from bot.keyboards.main_menu import LEADERBOARD_BUTTON
from core.economy import UserAccount, format_price, get_economy, player_rating

logger = logging.getLogger(__name__)

router = Router(name="leaderboard")

TOP_LIMIT = 10
EMPTY_TEXT = "Hozirça reyting böş. Birinçi bölib öyin boşlang!"
TITLE = "🏆 <b>Reyting va Top</b>"
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def leaderboard_text(
    top: list[UserAccount], me: UserAccount | None = None
) -> str:
    """Reyting jadvali matni."""
    lines = [TITLE, ""]
    if not top:
        lines.append(EMPTY_TEXT)
        return "\n".join(lines)

    for place, account in enumerate(top, start=1):
        prefix = MEDALS.get(place, f"{place}.")
        lines.append(
            f"{prefix} {escape(display_name(account))} — "
            f"<b>{format_price(player_rating(account))}</b> reyting · "
            f"{safe_int(account.wins)} ğalaba"
        )

    if me is not None:
        lines.append("")
        lines.append(
            f"📊 Sizning reytingingiz: <b>{format_price(player_rating(me))}</b> "
            f"({me.wins} ğalaba, {me.games_played} öyin)"
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
    await message.answer(leaderboard_text(top, me))
