"""Doimiy (persistent) pastki menyu klaviaturasi.

Telegram ``ReplyKeyboardMarkup`` faqat shaxsiy chatda ko'rsatiladi. Menyu
ikki ustunli bo'lib, ``is_persistent=True`` tufayli foydalanuvchi klaviaturani
yopib qo'ysa ham, chat ochilganda qaytadan ko'rinadi.

«👑 Admin panel» tugmasi faqat administratorga qo'shiladi: ``ADMIN_ID`` bilan
mos keladigan yoki ``users`` jadvalida ``role = 'admin'`` bo'lgan foydalanuvchiga.
"""

from __future__ import annotations

from urllib.parse import quote

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from bot.config import get_config
from core.i18n import BUTTONS, LANGUAGES, STRINGS, default_label, normalize_language

STRINGS_PLACEHOLDER = {lang: STRINGS["menu_placeholder"][lang] for lang in LANGUAGES}

# Eski UZ konstantalar (orqaga moslik); tilga xos matnlar BUTTONS'dan olinadi.
GAMES_BUTTON = "🌐 Mini App (Portal)"
GAME_LIST_BUTTON = "📋 Öyinlar"
# «Tezkor öyin» global navbatni ochadi; uzun matchmaking yozuvi yo'q.
MATCHMAKING_BUTTON = "🎮 Tezkor öyin"
MISSIONS_BUTTON = "🎯 Missiyalar"
SHOP_BUTTON = "🛍️ Dökon"
TOURNAMENTS_BUTTON = "🏆 Turnirlar"
NEW_GAME_BUTTON = GAME_LIST_BUTTON
PROFILE_BUTTON = "👤 Profilim"
LEADERBOARD_BUTTON = "👑 Reyting"
RULES_BUTTON = "ℹ️ Qoidalar / Yordam"
INVITE_BUTTON = "👥 Döstlar"
BONUS_BUTTON = "🎁 Kunlik bonus"
PROMO_BUTTON = "🎟️ Promo kod"
ADMIN_BUTTON = "👑 Admin panel"
CHANGE_LANGUAGE_BUTTON = default_label("change_language", language="uz")

_BUTTON_KEYS = (
    "games",
    "quick_game",
    "games_list",
    "missions",
    "bonus",
    "shop",
    "tournaments",
    "profile",
    "leaderboard",
    "promo",
    "invite",
    "rules",
    "admin",
    "change_language",
)

# Handlerlar shu to'plam orqali menyu tugmalarini taniydi.
# Barcha uch tildagi matnlar qo'llab-quvvatlanadi.
def _all_button_texts() -> frozenset[str]:
    return frozenset(
        BUTTONS[key][lang]
        for key in _BUTTON_KEYS
        for lang in LANGUAGES
    )


BUTTON_TEXTS: frozenset[str] = _all_button_texts()

INPUT_PLACEHOLDER = "Menyudan tanlang yoki /bunker, /mafia, /spy, /alias, /bomb yozing"


def mini_app_url_for(
    base_url: str,
    *,
    user_id: int | None = None,
    username: str = "",
    full_name: str = "",
) -> str:
    """Mini App havolasiga foydalanuvchi ma'lumotlarini qo'shadi.

    Telegram pastki (reply) klaviaturasidagi ``web_app`` tugmasi ba'zi
    holatlarda ``initData`` yubormaydi. Shu sababli foydalanuvchi id'si va
    ismi havola query parametrlariga qo'shiladi — Mini App ularni o'qib,
    haqiqiy balans va statistikani ko'rsatadi.
    """
    url = (base_url or "").strip()
    if not url:
        return url
    params: list[str] = []
    if user_id is not None and int(user_id) > 0:
        params.append(f"uid={int(user_id)}")
    clean_username = (username or "").strip().lstrip("@")
    if clean_username:
        params.append(f"uname={quote(clean_username, safe='')}")
    clean_name = (full_name or "").strip()
    if clean_name:
        params.append(f"fname={quote(clean_name, safe='')}")
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{'&'.join(params)}"


def build_main_menu(
    *,
    is_admin: bool = False,
    include_web_app: bool = True,
    language: str | None = None,
    user_id: int | None = None,
    username: str = "",
    full_name: str = "",
) -> ReplyKeyboardMarkup:
    """Ixcham, 2 ustunli pastki menyuni qaytaradi.

    Oxirgi qatorda Mini App portali bitta keng tugma sifatida turadi.

    Args:
        is_admin: ``True`` bo'lsa oxirgi qatorga «👑 Admin panel» qo'shiladi.
        include_web_app: ``False`` bo'lsa «Mini App (Portal)» oddiy matn
            tugmasi bo'ladi.
        user_id, username, full_name: Mini App havolasiga qo'shiladigan
            foydalanuvchi ma'lumotlari (``?uid=...&uname=...&fname=...``).
    """
    language = normalize_language(language)
    label = lambda key: default_label(key, language)  # noqa: E731
    config = get_config()
    mini_app_url = mini_app_url_for(
        config.mini_app_url or "",
        user_id=user_id,
        username=username,
        full_name=full_name,
    )
    portal_button = KeyboardButton(text=label("games"))
    if include_web_app and mini_app_url.startswith("https://"):
        portal_button = KeyboardButton(
            text=label("games"),
            web_app=WebAppInfo(url=mini_app_url),
        )
    rows: list[list[KeyboardButton]] = [
        [
            KeyboardButton(text=label("quick_game")),
            KeyboardButton(text=label("games_list")),
        ],
        [
            KeyboardButton(text=label("missions")),
            KeyboardButton(text=label("bonus")),
        ],
        [
            KeyboardButton(text=label("shop")),
            KeyboardButton(text=label("tournaments")),
        ],
        [
            KeyboardButton(text=label("profile")),
            KeyboardButton(text=label("leaderboard")),
        ],
        [
            KeyboardButton(text=label("promo")),
            KeyboardButton(text=label("invite")),
        ],
        [portal_button],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=label("admin"))])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=STRINGS_PLACEHOLDER[language],
    )
