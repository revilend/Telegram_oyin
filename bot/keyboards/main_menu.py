"""Doimiy (persistent) pastki menyu klaviaturasi.

Telegram ``ReplyKeyboardMarkup`` faqat shaxsiy chatda ko'rsatiladi. Menyu
ikki ustunli bo'lib, ``is_persistent=True`` tufayli foydalanuvchi klaviaturani
yopib qo'ysa ham, chat ochilganda qaytadan ko'rinadi.

«👑 Admin panel» tugmasi faqat administratorga qo'shiladi: ``ADMIN_ID`` bilan
mos keladigan yoki ``users`` jadvalida ``role = 'admin'`` bo'lgan foydalanuvchiga.
"""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from bot.config import get_config

GAMES_BUTTON = "🎮 O'yinlar (Mini App)"
SHOP_BUTTON = "🪙 Tangalar do'koni"
NEW_GAME_BUTTON = "🛡️ Yangi Bunker"
PROFILE_BUTTON = "👤 Mening profilim"
LEADERBOARD_BUTTON = "🏆 Reyting va Top"
RULES_BUTTON = "ℹ️ Qoidalar / Yordam"
INVITE_BUTTON = "👥 Do'stlarni taklif qilish"
ADMIN_BUTTON = "👑 Admin panel"

# Handlerlar shu to'plam orqali menyu tugmalarini taniydi.
BUTTON_TEXTS: frozenset[str] = frozenset(
    {
        GAMES_BUTTON,
        SHOP_BUTTON,
        NEW_GAME_BUTTON,
        PROFILE_BUTTON,
        LEADERBOARD_BUTTON,
        RULES_BUTTON,
        INVITE_BUTTON,
        ADMIN_BUTTON,
    }
)

INPUT_PLACEHOLDER = "Menyudan tanlang yoki /bunker yozing"


def build_main_menu(
    *, is_admin: bool = False, include_web_app: bool = True
) -> ReplyKeyboardMarkup:
    """Doimiy 2 ustunli pastki menyuni qaytaradi.

    Args:
        is_admin: ``True`` bo'lsa oxirgi qatorga «👑 Admin panel» qo'shiladi.
        include_web_app: ``False`` bo'lsa «O'yinlar» oddiy matn tugmasi bo'ladi.
            Telegram ``web_app`` tugmasini faqat to'g'ri HTTPS manzil bilan
            qabul qiladi, shuning uchun xato bo'lsa shu rejim ishlatiladi.
    """
    config = get_config()
    mini_app_url = config.mini_app_url or ""
    games_button = KeyboardButton(text=GAMES_BUTTON)
    if include_web_app and mini_app_url.startswith("https://"):
        games_button = KeyboardButton(
            text=GAMES_BUTTON,
            web_app=WebAppInfo(url=mini_app_url),
        )
    rows: list[list[KeyboardButton]] = [
        [
            games_button,
            KeyboardButton(text=SHOP_BUTTON),
        ],
        [
            KeyboardButton(text=NEW_GAME_BUTTON),
            KeyboardButton(text=PROFILE_BUTTON),
        ],
        [
            KeyboardButton(text=LEADERBOARD_BUTTON),
            KeyboardButton(text=RULES_BUTTON),
        ],
        [KeyboardButton(text=INVITE_BUTTON)],
    ]
    if is_admin:
        rows[-1].append(KeyboardButton(text=ADMIN_BUTTON))

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=INPUT_PLACEHOLDER,
    )
