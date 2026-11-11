"""«🏆 Reyting va Top» — eng yaxshi o'yinchilar ro'yxati.

Foydalanuvchilar kam bo'lsa ham, baza bo'sh bo'lsa ham xato bermaydi:
bo'sh holatda iliq xabar ko'rsatiladi.
"""

from __future__ import annotations

import asyncio

import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.handlers.profile import display_name, safe_int
from core.economy import UserAccount, format_price, get_economy, player_rating
from core.i18n import all_button_texts, resolve_language, t

logger = logging.getLogger(__name__)

router = Router(name="leaderboard")

TOP_LIMIT = 10
EMPTY_TEXT = "Hozirça reyting böş. Birinçi bölib öyin boşlang!"
TITLE = "🏆 <b>Reyting va Top</b>"
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
FRAME_BADGES = {
    "frame_gold": "🥇",
    "frame_neon": "💠",
    "frame_cyber": "🧬",
    "frame_fire": "🔥",
    "frame_diamond": "💎",
    "clan_emblem": "⚜️",
}


def cosmetics_badges(user_id: int) -> tuple[str, str]:
    """Taqilgan ramka emojisi va unvon matni (xato bo'lsa — bo'sh)."""
    try:
        from core.shop import CATALOG_BY_SLUG, get_shop_store

        equipped = get_shop_store().equipped(int(user_id))
        frame_emoji = FRAME_BADGES.get(str(equipped.get("frame") or ""), "")
        item = CATALOG_BY_SLUG.get(str(equipped.get("title") or ""))
        return frame_emoji, str(item.payload) if item is not None else ""
    except Exception:
        logger.exception("Bezaklarni öqib bölmadi: %s", user_id)
        return "", ""


def leaderboard_text(
    top: list[UserAccount],
    me: UserAccount | None = None,
    language: str | None = None,
) -> str:
    """Reyting jadvali matni."""
    lang = language or (getattr(me, 'language_code', None) if me is not None else None)
    lines = [t(lang, "leaderboard_title"), ""]
    if not top:
        lines.append(t(lang, "leaderboard_empty"))
        return "\n".join(lines)

    for place, account in enumerate(top, start=1):
        prefix = MEDALS.get(place, f"{place}.")
        frame_emoji, title_text = cosmetics_badges(account.user_id)
        name_html = escape(display_name(account))
        if frame_emoji:
            name_html = f"{frame_emoji} {name_html}"
        line = (
            f"{prefix} {name_html} — "
            f"<b>{format_price(player_rating(account))}</b> reyting · "
            f"{safe_int(account.wins)} ğalaba"
        )
        if title_text:
            line += f"\n   👑 <i>{escape(title_text)}</i>"
        lines.append(line)

    if me is not None:
        lines.append("")
        lines.append(
            f"📊 Sizning reytingingiz: <b>{format_price(player_rating(me))}</b> "
            f"({me.wins} ğalaba, {me.games_played} öyin)"
        )
    return "\n".join(lines)


@router.message(Command("top", "leaderboard", "reyting"))
@router.message(
    F.chat.type == "private", F.text.in_(all_button_texts("leaderboard"))
)
async def show_leaderboard(message: Message) -> None:
    """Top o'yinchilar ro'yxatini yuboradi."""
    user = message.from_user
    language = resolve_language(
        user.id if user is not None else None,
        getattr(user, "language_code", None) if user is not None else None,
    )
    try:
        # Reyting va shaxsiy hisob bir-biriga bog'liq emas: ikkala Supabase
        # so'rovi ``asyncio.gather`` bilan parallel ketadi (waterfall yo'q).
        economy = get_economy()
        calls = [asyncio.to_thread(economy.top_users, TOP_LIMIT)]
        account_getter = getattr(economy, "account_for", None) or getattr(
            economy, "get_user", None
        )
        if user is not None and callable(account_getter):
            calls.append(asyncio.to_thread(account_getter, user.id))
        results = await asyncio.gather(*calls)
        top = results[0]
        me = results[1] if len(results) > 1 else None
    except Exception as exc:  # xatoni yashirmaymiz
        logger.exception("Reyting xatosi")
        await message.answer(f"⚠️ Reyting xatosi: {escape(str(exc))}")
        return
    # Til keshdagi hisobdan olinadi — qo'shimcha Supabase so'rovi yo'q.
    language = resolve_language(
        user.id if user is not None else None,
        getattr(user, "language_code", None) if user is not None else None,
    )
    await message.answer(leaderboard_text(top, me, language))
