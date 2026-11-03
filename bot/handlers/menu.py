"""Doimiy pastki menyu tugmalari uchun handlerlar.

Har bir tugma mavjud funksiyalarga ulanadi: do'kon, guruhga o'yin ochish
qo'llanmasi, profil, reyting, qoidalar, taklif va admin panel.
"""

from __future__ import annotations

import logging
from html import escape
from urllib.parse import quote

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import get_config
from bot.handlers import admin, shop
from bot.keyboards.main_menu import (
    ADMIN_BUTTON,
    INVITE_BUTTON,
    LEADERBOARD_BUTTON,
    NEW_GAME_BUTTON,
    PROFILE_BUTTON,
    RULES_BUTTON,
    SHOP_BUTTON,
)
from core.economy import UserAccount, format_price, get_economy

logger = logging.getLogger(__name__)

router = Router(name="menu")

PRIVATE = F.chat.type == "private"


def rank_title(wins: int) -> str:
    """G'alabalar soniga qarab unvonni qaytaradi."""
    wins = int(wins)
    if wins >= 10:
        return "👑 Afsonaviy omon qoluvchi"
    if wins >= 5:
        return "🏅 Bunker ustasi"
    if wins >= 2:
        return "🎖 Tajribali o'yinchi"
    if wins >= 1:
        return "🌱 Ilk g'alaba"
    return "🪖 Yangi o'yinchi"


def _display_name(account: UserAccount) -> str:
    return account.full_name or account.username or str(account.user_id)


def profile_text(account: UserAccount) -> str:
    """«👤 Mening profilim» xabari."""
    username = f"@{escape(account.username)}" if account.username else "—"
    return (
        "👤 <b>Mening profilim</b>\n\n"
        f"Ism: <b>{escape(_display_name(account))}</b>\n"
        f"Username: {username}\n"
        f"🆔 <code>{account.user_id}</code>\n\n"
        f"🪙 Tangalar: <b>{format_price(account.coins)}</b>\n"
        f"🏆 Unvon: <b>{rank_title(account.wins)}</b>\n"
        f"🎮 O'ynagan o'yinlari: <b>{account.games_played}</b>\n"
        f"🥇 G'alabalari: <b>{account.wins}</b>"
    )


def leaderboard_text(top: list[UserAccount], me: UserAccount | None) -> str:
    """«🏆 Reyting va Top» xabari."""
    lines = ["🏆 <b>Reyting va Top</b>", ""]
    if not top:
        lines.append("Hali natijalar yo'q — birinchi bo'lib o'ynang! 🎯")
    else:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for place, account in enumerate(top, start=1):
            prefix = medals.get(place, f"{place}.")
            lines.append(
                f"{prefix} {escape(_display_name(account))} — "
                f"<b>{account.wins}</b> g'alaba · "
                f"{format_price(account.coins)} tanga"
            )
    if me is not None:
        lines.append("")
        lines.append(
            f"📊 Sizning natijangiz: <b>{me.wins}</b> g'alaba, "
            f"<b>{me.games_played}</b> o'yin."
        )
    return "\n".join(lines)


RULES_TEXT = (
    "ℹ️ <b>Qoidalar / Yordam</b>\n\n"
    "☢️ <b>Bunker nima?</b>\n"
    "Falokatdan keyin oz sonli odam bunkerga sig'adi. Har bir o'yinchining "
    "kartalari (kasb, biologiya, sog'liq, qiziqish, yuk va fakt) bo'yicha "
    "qaysi odam omon qolishga loyiqligini birgalikda hal qilasiz.\n\n"
    "🎮 <b>Qanday o'ynaladi?</b>\n"
    "1. Botni guruhga qo'shing va <code>/bunker</code> yuboring.\n"
    "2. Do'stlar «Guruh orqali qo'shilish» tugmasini bosadi.\n"
    "3. Xona egasi «O'yinni boshlash»ni bosadi.\n"
    "4. Mini App'da kartalaringizni birma-bir ochasiz.\n"
    "5. Ovoz berish raundida ortiqcha o'yinchilar haydaladi.\n\n"
    "🪙 <b>Tangalar va boosterlar</b>\n"
    "Tangalar «Tangalar do'koni»da sotib olinadi va qalqon, ikki ovoz yoki "
    "kartani qayta tanlash kabi boosterlarga sarflanadi.\n\n"
    "❓ Savol bo'lsa administratorga yozing."
)


@router.message(PRIVATE, F.text == SHOP_BUTTON)
async def menu_shop(message: Message, state: FSMContext) -> None:
    """🪙 Tangalar do'koni — /shop menyusini ochadi."""
    await shop.send_shop(message, state)


@router.message(PRIVATE, F.text == PROFILE_BUTTON)
async def menu_profile(message: Message) -> None:
    """👤 Mening profilim — tanga, g'alaba va unvon."""
    user = message.from_user
    if user is None:
        return
    try:
        account = get_economy().ensure_user(
            user.id, user.username or "", user.full_name
        )
    except Exception:
        logger.exception("Profilni yuklab bo'lmadi: %s", user.id)
        await message.answer(
            "⚠️ Profilni yuklab bo'lmadi. Birozdan keyin qayta urinib ko'ring."
        )
        return
    await message.answer(profile_text(account))


@router.message(PRIVATE, F.text == LEADERBOARD_BUTTON)
async def menu_leaderboard(message: Message) -> None:
    """🏆 Reyting va Top — eng ko'p g'alaba qozongan o'yinchilar."""
    user = message.from_user
    try:
        economy = get_economy()
        top = economy.top_users(10)
        me = economy.get_user(user.id) if user is not None else None
    except Exception:
        logger.exception("Reytingni yuklab bo'lmadi")
        await message.answer(
            "⚠️ Reytingni yuklab bo'lmadi. Birozdan keyin qayta urinib ko'ring."
        )
        return
    await message.answer(leaderboard_text(top, me))


@router.message(PRIVATE, F.text == NEW_GAME_BUTTON)
async def menu_new_game(message: Message) -> None:
    """🛡️ Yangi Bunker — guruhda xona ochish qo'llanmasi."""
    config = get_config()
    text = (
        "🛡️ <b>Yangi Bunker o'yini</b>\n\n"
        "Bunker faqat guruhda o'ynaladi. Uch qadam:\n"
        "1. Botni guruhingizga qo'shing (pastdagi tugma).\n"
        "2. Guruhda <code>/bunker</code> buyrug'ini yuboring.\n"
        "3. Do'stlaringiz «Guruh orqali qo'shilish» tugmasini bosadi, "
        "xona egasi esa «O'yinni boshlash»ni bosadi.\n\n"
        "Keyin hamma Mini App'da kartalarini ko'radi va ovoz berish "
        "boshlanadi. Omad! 🍀"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Guruhga qo'shish",
                    url=f"https://t.me/{config.bot_username}?startgroup=true",
                )
            ]
        ]
    )
    await message.answer(text, reply_markup=keyboard)


@router.message(PRIVATE, F.text == RULES_BUTTON)
async def menu_rules(message: Message) -> None:
    """ℹ️ Qoidalar / Yordam."""
    await message.answer(RULES_TEXT)


@router.message(PRIVATE, F.text == INVITE_BUTTON)
async def menu_invite(message: Message) -> None:
    """👥 Do'stlarni taklif qilish."""
    config = get_config()
    link = f"https://t.me/{config.bot_username}"
    share_text = "Revilend Games — Bunker o'yinini birga o'ynaymiz! 🎮"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Do'stga ulashish",
                    url=(
                        "https://t.me/share/url"
                        f"?url={quote(link, safe='')}&text={quote(share_text, safe='')}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Guruhga qo'shish",
                    url=f"https://t.me/{config.bot_username}?startgroup=true",
                )
            ],
        ]
    )
    await message.answer(
        "👥 <b>Do'stlarni taklif qilish</b>\n\n"
        f"Bot havolasi: <code>{link}</code>\n\n"
        "Havolani do'stlaringizga yuboring — ular botni ochib, birgalikda "
        "guruhda Bunker o'ynashlari mumkin.\n\n"
        "💡 Guruhga qo'shib, <code>/bunker</code> yuboring va o'yinni "
        "boshlang.",
        reply_markup=keyboard,
    )


@router.message(PRIVATE, F.text == ADMIN_BUTTON)
async def menu_admin(message: Message) -> None:
    """👑 Admin panel — /admin bilan bir xil panelni ochadi."""
    await admin.admin_panel(message)
