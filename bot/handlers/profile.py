"""«👤 Profilim / Мой профиль / My Profile» kartochkasi (3 til)."""

from __future__ import annotations

import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from core.economy import (
    START_COINS,
    UserAccount,
    format_price,
    get_economy,
    player_rating,
)
from core.i18n import (
    LANGUAGE_NAMES,
    all_button_texts,
    normalize_language,
    resolve_language,
    set_language,
    t,
)

logger = logging.getLogger(__name__)

router = Router(name="profile")

CHANGE_LANGUAGE_CALLBACK = "change_language"
SET_LANGUAGE_PREFIX = "set_lang:"


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


def profile_text(
    account: UserAccount, title: str = "", language: str | None = None
) -> str:
    """Chiroyli profil kartochkasi (barcha maydonlar xavfsiz)."""
    lang = normalize_language(language or getattr(account, 'language_code', None))
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
    title_line = (
        f"\n👑 {t(lang, 'profile_title_label')}: <b>{escape(title)}</b>"
        if title
        else ""
    )
    title_block = t(lang, "profile_title")
    return (
        "╭───────────────────────╮\n"
        f"    {title_block}\n"
        "╰───────────────────────╯\n\n"
        f"👤 {t(lang, 'profile_name')}: <b>{name}</b>{title_line}\n"
        f"🔗 {t(lang, 'profile_username')}: {username}\n"
        f"🆔 ID: <code>{account.user_id}</code>\n"
        f"🪙 {t(lang, 'profile_coins')}: <b>{format_price(coins)}</b>\n"
        f"🎮 {t(lang, 'profile_games')}: <b>{games}</b> | "
        f"🥇 {t(lang, 'profile_wins')}: <b>{wins}</b>\n"
        f"🛡️ {t(lang, 'profile_bunker')}: <b>{bunker_wins}</b> | "
        f"🕵️ {t(lang, 'profile_mafia')}: <b>{mafia_wins}</b>\n"
        f"🕶️ {t(lang, 'profile_spy')}: <b>{spy_wins}</b> | "
        f"🐊 {t(lang, 'profile_alias')}: <b>{alias_wins}</b>\n"
        f"💣 {t(lang, 'profile_bomb')}: <b>{bomb_wins}</b>\n"
        f"🏅 {t(lang, 'profile_total_wins')}: <b>{total_wins}</b>\n"
        f"🏆 {t(lang, 'profile_rating')}: "
        f"<b>{format_price(player_rating(account))}</b>"
    )


def load_account(user) -> UserAccount:
    """Hisobni qaytaradi; yo'q bo'lsa 100 tanga bilan yaratadi."""
    return get_economy().ensure_user(user.id, user.username or "", user.full_name or "")


def language_keyboard(language: str) -> InlineKeyboardMarkup:
    """Tilni almashtirish inline klaviaturasi."""
    rows = [
        [
            InlineKeyboardButton(
                text=LANGUAGE_NAMES[code],
                callback_data=f"{SET_LANGUAGE_PREFIX}{code}",
            )
            for code in ("uz", "ru", "en")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_keyboard(language: str) -> InlineKeyboardMarkup:
    """Profil ostidagi inline tugmalar: tilni almashtirish."""
    from core.i18n import default_label

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=default_label("change_language", language),
                    callback_data=CHANGE_LANGUAGE_CALLBACK,
                )
            ]
        ]
    )


@router.message(Command("profile", "me"))
@router.message(F.chat.type == "private", F.text.in_(all_button_texts("profile")))
async def show_profile(message: Message) -> None:
    """Profil kartochkasini yuboradi."""
    user = message.from_user
    if user is None:
        return
    language = resolve_language(user.id, getattr(user, 'language_code', None))
    try:
        account = load_account(user)
    except Exception as exc:  # xatoni yashirmaymiz
        logger.exception("Profil xatosi: %s", user.id)
        await message.answer(t(language, "profile_error", error=escape(str(exc))))
        return

    text = profile_text(account, equipped_title(user.id), language)
    if account.coins == START_COINS and account.games_played == 0:
        text += f"\n\n{t(language, 'profile_free_coins', amount=START_COINS)}"
    await message.answer(text, reply_markup=profile_keyboard(language))


@router.callback_query(F.data == CHANGE_LANGUAGE_CALLBACK)
async def change_language(callback: CallbackQuery) -> None:
    """Profil menyusidan til almashtirish oynasi."""
    user = callback.from_user
    language = resolve_language(user.id, getattr(user, 'language_code', None)) if user else "uz"
    await callback.message.answer(
        t(language, "language_prompt"), reply_markup=language_keyboard(language)
    )
    await callback.answer()


@router.callback_query(F.data.startswith(SET_LANGUAGE_PREFIX))
async def choose_language(callback: CallbackQuery) -> None:
    """Tanlangan tilni saqlab, botni shu tilga o'tkazadi."""
    user = callback.from_user
    code = (callback.data or "").removeprefix(SET_LANGUAGE_PREFIX)
    normalized = normalize_language(code)
    if user is not None:
        try:
            set_language(user.id, normalized)
        except Exception:
            logger.exception("Til saqlanmadi: %s", user.id)
    await callback.message.answer(
        t(normalized, "language_changed", language=LANGUAGE_NAMES[normalized])
    )
    await callback.answer(t(normalized, "language_changed", language=LANGUAGE_NAMES[normalized]))
