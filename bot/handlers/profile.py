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
    EconomyError,
    UserAccount,
    format_price,
    get_economy,
    player_rating,
)

logger = logging.getLogger(__name__)

router = Router(name="profile")


def display_name(account: UserAccount) -> str:
    """Profil va reyting uchun ko'rsatiladigan ism."""
    return account.full_name or account.username or f"ID {account.user_id}"


def profile_text(account: UserAccount) -> str:
    """Chiroyli profil kartochkasi."""
    name = escape(display_name(account))
    username = f"@{escape(account.username)}" if account.username else "—"
    return (
        "╭───────────────────────╮\n"
        "    👤 <b>Mening profilim</b>\n"
        "╰───────────────────────╯\n\n"
        f"👤 Ism: <b>{name}</b>\n"
        f"🔗 Username: {username}\n"
        f"🆔 ID: <code>{account.user_id}</code>\n"
        f"🪙 Tangalar: <b>{format_price(account.coins)}</b>\n"
        f"🎮 O'ynalgan o'yinlar: <b>{account.games_played}</b> | "
        f"🥇 G'alabalar: <b>{account.wins}</b>\n"
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
        account = load_account(user)
    except EconomyError as exc:
        await message.answer(f"⚠️ Profilni yuklab bo'lmadi: {escape(str(exc))}")
        return
    except Exception:
        logger.exception("Profilni yuklab bo'lmadi: %s", user.id)
        await message.answer(
            "⚠️ Profilni yuklab bo'lmadi. Birozdan keyin qayta urinib ko'ring."
        )
        return

    text = profile_text(account)
    if account.coins == START_COINS and account.games_played == 0:
        text += (
            f"\n\n🎁 Ro'yxatdan o'tganingiz uchun <b>{START_COINS}</b> bepul "
            "tanga berildi!"
        )
    await message.answer(text)
