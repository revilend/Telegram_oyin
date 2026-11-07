"""«👤 Mening profilim» kartochkasi.

Foydalanuvchi ``users`` jadvalida bo'lmasa, xatolik bermay avtomatik
yaratiladi (``core.economy.START_COINS`` — 100 bepul tanga).
"""

from __future__ import annotations

import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards.main_menu import PROFILE_BUTTON
from core.economy import (
    START_COINS,
    UserAccount,
    format_price,
    get_economy,
    player_rating,
)

logger = logging.getLogger(__name__)

router = Router(name="profile")


def safe_int(value: object, default: int = 0) -> int:
    """Bazadan kelgan qiymatni xavfsiz butun songa aylantiradi."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def display_name(account: UserAccount) -> str:
    """Profil va reyting uchun ko'rsatiladigan ism."""
    name = (account.full_name or "").strip()
    username = (account.username or "").strip()
    if name:
        return name
    if username:
        return username
    return f"ID {account.user_id}"


def equipped_title(user_id: int) -> str:
    """Do'kondan taqilgan unvon matnini qaytaradi (bo'lmasa — bo'sh)."""
    try:
        from core.shop import CATALOG_BY_SLUG, get_shop_store

        slug = str(get_shop_store().equipped(int(user_id)).get("title") or "")
        item = CATALOG_BY_SLUG.get(slug)
        return str(item.payload) if item is not None else ""
    except Exception:
        logger.exception("Unvonni öqib bölmadi: %s", user_id)
        return ""


def profile_text(account: UserAccount, title: str = "") -> str:
    """Chiroyli profil kartochkasi (barcha maydonlar xavfsiz)."""
    name = escape(display_name(account))
    username = f"@{escape(account.username)}" if account.username else "—"
    coins = safe_int(account.coins, START_COINS)
    games = safe_int(account.games_played)
    wins = safe_int(account.wins)
    bunker_wins = safe_int(account.bunker_wins)
    mafia_wins = safe_int(account.mafia_wins)
    spy_wins = safe_int(account.spy_wins)
    alias_wins = safe_int(account.alias_wins)
    bomb_wins = safe_int(account.bomb_wins)
    total_wins = bunker_wins + mafia_wins + spy_wins + alias_wins + bomb_wins
    title_line = f"\n👑 Unvon: <b>{escape(title)}</b>" if title else ""
    return (
        "╭───────────────────────╮\n"
        "    👤 <b>Mening profilim</b>\n"
        "╰───────────────────────╯\n\n"
        f"👤 Ism: <b>{name}</b>{title_line}\n"
        f"🔗 Username: {username}\n"
        f"🆔 ID: <code>{account.user_id}</code>\n"
        f"🪙 Tangalar: <b>{format_price(coins)}</b>\n"
        f"🎮 Öynalgan öyinlar: <b>{games}</b> | "
        f"🥇 Ğalabalar: <b>{wins}</b>\n"
        f"🛡️ Bunker: <b>{bunker_wins}</b> | 🕵️ Mafiya: <b>{mafia_wins}</b>\n"
        f"🕶️ Josus: <b>{spy_wins}</b> | 🐊 Alias: <b>{alias_wins}</b>\n"
        f"💣 Bomba: <b>{bomb_wins}</b>\n"
        f"🏅 Umumiy ğalabalar: <b>{total_wins}</b>\n"
        f"🏆 Reyting: <b>{format_price(player_rating(account))}</b>"
    )


def load_account(user) -> UserAccount:
    """Hisobni qaytaradi; yo'q bo'lsa 100 tanga bilan yaratadi."""
    return get_economy().ensure_user(
        user.id, user.username or "", user.full_name or ""
    )


@router.message(Command("profile", "me"))
@router.message(F.chat.type == "private", F.text == PROFILE_BUTTON)
async def show_profile(message: Message) -> None:
    """Profil kartochkasini yuboradi."""
    user = message.from_user
    if user is None:
        return
    try:
        # `users` jadvali `telegram_id` bo'yicha qidiriladi; topilmasa
        # 100 tanga bilan yangi yozuv yaratiladi.
        account = load_account(user)
    except Exception as exc:  # xatoni yashirmaymiz
        logger.exception("Profil xatosi: %s", user.id)
        await message.answer(f"⚠️ Profil xatosi: {escape(str(exc))}")
        return

    text = profile_text(account, equipped_title(user.id))
    if account.coins == START_COINS and account.games_played == 0:
        text += (
            f"\n\n🎁 Röyxatdan ötganingiz uçun <b>{START_COINS}</b> bepul "
            "tanga berildi!"
        )
    await message.answer(text)
