"""Shaxsiy chatdagi umumiy handlerlar: /start, /help, referallar va taklif menyusi.

«ℹ️ Qoidalar / Yordam» bo'limi shu modulda: barcha to'rt o'yin va tangalar
bo'yicha inline qo'llanma menyusi.
"""

from __future__ import annotations

import asyncio

import logging
from html import escape
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from bot.blocking import blocked_text
from bot.config import get_config
from bot.handlers.admin import is_admin
from bot.keyboards.main_menu import build_main_menu, mini_app_url_for
from bot.handlers.profile import language_keyboard
from core.i18n import LANGUAGES, all_button_texts, resolve_language, t
from core.economy import (
    REFERRAL_BONUS,
    START_COINS,
    EconomyError,
    UserAccount,
    format_price,
    get_economy,
    referral_earnings,
)
from core.login_codes import issue_login_code

logger = logging.getLogger(__name__)

# Fon vazifalari: taklif mukofoti va admin bildirishnomasi /start javobini
# bloklamaydi. To'plam kuchli havola saqlaydi (task o'chib ketmasin).
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _background(coro) -> asyncio.Task:
    """Vazifani fon rejimida ishga tushiradi (javobni kutmaydi)."""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


async def flush_background_tasks() -> None:
    """Fon vazifalarini kutadi (testlar va graceful shutdown uchun)."""
    pending = [task for task in _BACKGROUND_TASKS if not task.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

router = Router(name="common")

# Yuqori ustuvorlikdagi bekor qilish routeri: Dispatcher'ga birinchi ulanadi,
# shuning uchun FSM holatidagi handlerlardan oldin ishlaydi.
cancel_router = Router(name="cancel")

REFERRAL_PREFIX = "ref_"

CANCELLED_TEXT = t("uz", "cancelled")
CANCELLED_TEXTS: frozenset[str] = frozenset(
    t(language, "cancelled") for language in LANGUAGES
)
CANCEL_TEXTS: frozenset[str] = frozenset(
    {"/cancel", "❌ Bekor qiliş", "Bekor qiliş", "❌ Tölov bekor qilindi."}
    | CANCELLED_TEXTS
)

# ----------------------------------------------------------------------
# Referal havolalari
# ----------------------------------------------------------------------
def referral_link(bot_username: str, user_id: int) -> str:
    """Taklif havolasi: ``https://t.me/<bot>?start=ref_<user_id>``."""
    return f"https://t.me/{bot_username}?start={REFERRAL_PREFIX}{int(user_id)}"


def parse_referral_arg(args: str | None) -> int | None:
    """``/start ref_12345`` argumentidan taklif qiluvchining id'sini ajratadi."""
    raw = (args or "").strip()
    if not raw:
        return None
    first = raw.split()[0]
    if not first.lower().startswith(REFERRAL_PREFIX):
        return None
    digits = first[len(REFERRAL_PREFIX) :].strip()
    if not digits.isdigit():
        return None
    inviter_id = int(digits)
    return inviter_id if inviter_id > 0 else None


def invite_text(account: UserAccount, bot_username: str) -> str:
    """«👥 Do'stlarni taklif qilish» xabari."""
    link = referral_link(bot_username, account.user_id)
    count = account.referral_count
    language = getattr(account, 'language_code', None) or "uz"
    return (
        f"{t(language, 'invite_title')}\n\n"
        + t(
            language,
            "invite_body",
            bonus=REFERRAL_BONUS,
            link=link,
            count=format_price(count),
            earned=format_price(referral_earnings(account)),
        )
    )


def invite_keyboard(account: UserAccount, bot_username: str) -> InlineKeyboardMarkup:
    """Do'stlarga ulashish tugmasi."""
    link = referral_link(bot_username, account.user_id)
    language = getattr(account, "language_code", None) or "uz"
    share_text = t(language, "invite_share_text", link=link)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "invite_share_button"),
                    url=(
                        "https://t.me/share/url"
                        f"?url={quote(link, safe='')}"
                        f"&text={quote(share_text, safe='')}"
                    ),
                )
            ]
        ]
    )


LOGIN_START_ARG = "login"


def login_text(code: str, language: str | None = None) -> str:
    """Mini App'ga kirish kodi va avtomatik kirish haqidagi xabar."""
    lang = language or "uz"
    return f"{t(lang, 'login_title')}\n\n{t(lang, 'login_body', code=code)}"


def login_keyboard(user: UserAccount) -> InlineKeyboardMarkup | None:
    """Mini App'ni foydalanuvchi profili bilan avtomatik ochuvchi tugma."""
    config = get_config()
    url = mini_app_url_for(
        config.mini_app_url or "",
        user_id=user.user_id,
        username=user.username,
        full_name=user.full_name,
    )
    if not url.startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(getattr(user, "language_code", None) or "uz", "login_button"),
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )


async def send_login_code(
    message: Message, account: UserAccount | None = None
) -> None:
    """Foydalanuvchiga yangi bir martalik kod va kirish tugmasini yuboradi."""
    user = message.from_user
    if user is None:
        return
    if account is None:
        account = get_economy().ensure_user(
            user.id, user.username or "", user.full_name
        )
    code = issue_login_code(user.id)
    language = resolve_language(user.id, getattr(user, 'language_code', None))
    await message.answer(
        login_text(code, language), reply_markup=login_keyboard(account)
    )


def new_user_admin_text(
    user, inviter: UserAccount | None, total_users: int, language: str = "uz"
) -> str:
    """Yangi o'yinchi haqida bosh adminga yuboriladigan xabar."""
    username = (
        f"@{escape(user.username)}"
        if user.username
        else t(language, "admin_none")
    )
    user_language = str(
        getattr(user, "language_code", None) or t(language, "admin_unknown")
    )
    if inviter is None:
        inviter_text = t(language, "admin_direct")
    elif inviter.username:
        inviter_text = (
            f"@{escape(inviter.username)} "
            f"(ID: <code>{inviter.user_id}</code>)"
        )
    else:
        inviter_text = (
            f"{escape(inviter.full_name or t(language, 'admin_unknown'))} "
            f"(ID: <code>{inviter.user_id}</code>)"
        )
    return t(
        language,
        "admin_new_user",
        name=escape(user.full_name),
        username=username,
        user_id=user.id,
        language=escape(user_language),
        inviter=inviter_text,
        total=format_price(total_users),
    )


def _create_account(economy, user) -> UserAccount:
    """Yangi hisobni yaratadi (SELECT'siz, chunki yo'qligi allaqachon ma'lum)."""
    try:
        return economy.ensure_user(
            user.id,
            user.username or "",
            user.full_name,
            known_missing=True,
        )
    except TypeError:
        # Eski/test store'lari ``known_missing``ni bilmasligi mumkin.
        return economy.ensure_user(
            user.id, user.username or "", user.full_name
        )


def _lookup_account(economy, user_id: int) -> UserAccount | None:
    """Hisobni bir marta o'qiydi (yangi yozuv yaratmaydi, keshdan foydalanadi)."""
    finder = getattr(economy, "find_user", None)
    if not callable(finder):
        return None
    return finder(int(user_id))


async def _pay_referral(
    message: Message, economy, inviter_id: int, user
) -> None:
    """Taklif qiluvchiga +bonus tanga beradi va unga xabar yuboradi.

    Supabase ``referrals`` jadvali bilan bog'liq har qanday xato yutiladi:
    yangi o'yinchi baribir xush kelibsiz xabarini va menyuni oladi.
    """
    try:
        result = economy.register_referral(inviter_id, int(user.id))
    except Exception:
        logger.exception(
            "Taklifni saqlab bölmadi: %s -> %s", inviter_id, user.id
        )
        return
    if result is None:
        return
    inviter = None
    finder = getattr(economy, "find_user", None)
    if callable(finder):
        try:
            inviter = finder(int(inviter_id))
        except Exception:
            inviter = None
    try:
        await _notify_inviter(
            message.bot,
            result,
            user.full_name or "",
            getattr(inviter, "language_code", None) or "uz",
        )
    except Exception:
        logger.exception("Taklif egasiga xabar yuborilmadi: %s", inviter_id)


async def _finish_new_user(
    message: Message,
    economy,
    inviter_id: int | None,
    user,
    is_new: bool,
    account: UserAccount | None,
) -> None:
    """Yangi foydalanuvchi uchun taklif mukofoti va admin bildirishnomasi."""
    if user is None or not is_new or account is None:
        return
    try:
        if inviter_id is not None and int(inviter_id) != int(user.id):
            await _pay_referral(message, economy, int(inviter_id), user)
        await notify_admin_new_user(message, economy, inviter_id)
    except Exception:
        # Fon vazifasi /start oqimiga ta'sir qilmaydi.
        logger.exception(
            "Fon vazifasi xatosi: %s -> %s", inviter_id, user.id
        )


async def notify_admin_new_user(
    message: Message, economy, inviter_id: int | None = None
) -> None:
    """Yangi ro'yxatdan o'tgan o'yinchi haqida ADMIN_ID'ga xabar beradi."""
    user = message.from_user
    if user is None:
        return
    try:
        admin_id = int(get_config().admin_id or 0)
        if admin_id <= 0:
            return
        inviter = None
        if inviter_id is not None and int(inviter_id) != int(user.id):
            inviter = economy.find_user(int(inviter_id))
        # Adminning tili lug'atdagi zaxira (uz) — qo'shimcha so'rovsiz.
        text = new_user_admin_text(user, inviter, economy.count_users())
        await message.bot.send_message(admin_id, text)
    except TelegramAPIError:
        logger.info("Yangi öyinçi haqida adminga xabar yuborilmadi")
    except Exception:
        # Bildirishnoma xatosi foydalanuvçining /start oqimini buzmasin.
        logger.exception("Yangi öyinçi bildirişida xatolik")


async def _notify_inviter(
    bot: Bot, result, invited_name: str, language: str = "uz"
) -> None:
    """Taklif qilganga bot nomidan minnatdorchilik xabarini yuboradi."""
    text = t(
        language,
        "invited_notification",
        name=escape(invited_name),
        bonus=format_price(result.bonus),
    )
    try:
        await bot.send_message(result.inviter_id, text)
    except TelegramAPIError:
        logger.info("Taklif egasiga xabar yuborilmadi: %s", result.inviter_id)
    except Exception:
        logger.exception("Taklif egasiga xabar yuborişda xatolik")


# ----------------------------------------------------------------------
# Global bekor qilish
# ----------------------------------------------------------------------
@cancel_router.message(Command("cancel"))
@cancel_router.message(F.text.in_(CANCEL_TEXTS))
async def cancel_process(message: Message, state: FSMContext) -> None:
    """Har qanday FSM holatida ishlaydi: holatni tozalab, menyuga qaytaradi."""
    try:
        await state.clear()
    except Exception:  # holat yo'q bo'lsa ham xabar yuborilishi kerak
        logger.exception("FSM holatini tozalab bölmadi")

    if message.chat.type in {"group", "supergroup"}:
        # Guruhda /cancel faol Alias o'yinini ham to'xtatadi (ega yoki admin).
        from bot.handlers import alias_group as alias_handlers

        user = message.from_user
        if user is not None and alias_handlers.has_active_room(message.chat.id):
            await alias_handlers.stop_alias_for_chat(
                message.bot, message.chat.id, user.id
            )
            return

    user = message.from_user
    language = resolve_language(
        user.id if user is not None else None,
        getattr(user, "language_code", None) if user is not None else None,
    )
    cancelled_text = t(language, "cancelled") or CANCELLED_TEXT
    if message.chat.type == "private":
        try:
            menu_kwargs: dict[str, object] = {
                "is_admin": is_admin(user.id) if user is not None else False,
                "language": language,
            }
            if user is not None:
                menu_kwargs.update(
                    user_id=user.id,
                    username=user.username or "",
                    full_name=user.full_name,
                )
            await message.answer(
                cancelled_text,
                reply_markup=build_main_menu(**menu_kwargs),
            )
            return
        except TelegramAPIError:
            logger.exception("Bekor qiliş xabarini menyu bilan yuborib bölmadi")
    await message.answer(cancelled_text)


# ----------------------------------------------------------------------
# Handlerlar
# ----------------------------------------------------------------------
@router.message(CommandStart())
async def start_command(message: Message, command: CommandObject | None = None) -> None:
    """/start — xush kelibsiz xabari, doimiy menyu va referal hisobi."""
    user = message.from_user
    if message.chat.type != "private":
        language = resolve_language(
            user.id if user is not None else None,
            getattr(user, "language_code", None) if user is not None else None,
        )
        await message.answer(t(language, "welcome_group_only"))
        return

    language = resolve_language(
        user.id if user is not None else None,
        getattr(user, "language_code", None) if user is not None else None,
    )
    name = escape(user.full_name if user else "döstim")
    economy = get_economy()
    notes: list[str] = []
    account: UserAccount | None = None
    inviter_id: int | None = None
    is_new = False

    if user is not None:
        # Bitta o'qish (keshdan yoki bazadan) blok holati va "yangi
        # foydalanuvchi"mi degan savolga birga javob beradi. Avval bu yerda
        # ketma-ket 3 ta Supabase so'rovi ketardi — shu sababli /start sekin
        # javob berardi.
        try:
            account = _lookup_account(economy, user.id)
        except Exception:
            # Baza javob bermasa ham /start to'xtamaydi.
            logger.exception("Foydalanuvçi holatini öqib bölmadi: %s", user.id)
            account = None

        if account is not None and account.is_blocked:
            await message.answer(
                blocked_text(
                    account.block_reason,
                    int(get_config().admin_id or 0),
                )
            )
            return

        inviter_id = parse_referral_arg(
            command.args if command is not None else None
        )
        is_new = account is None
        if is_new:
            try:
                account = _create_account(economy, user)
                notes.append(
                    t(
                        language,
                        "registered_bonus",
                        amount=format_price(account.coins),
                    )
                )
            except EconomyError as exc:
                logger.exception("Foydalanuvçini saqlab bölmadi: %s", user.id)
                notes.append(f"⚠️ {escape(str(exc))}")
            except Exception:
                # Taklif/jadval xatosi xush kelibsiz xabarini to'xtatmaydi.
                logger.exception("Foydalanuvçini saqlab bölmadi: %s", user.id)

    args = (command.args if command is not None else "") or ""
    if args.strip().split()[:1] == [LOGIN_START_ARG]:
        if user is None:
            return
        await send_login_code(message, account)
        # Taklif hisobi orqa fonda: javob darhol qaytadi.
        if is_new and account is not None:
            _background(
                _finish_new_user(
                    message, economy, inviter_id, user, is_new, account
                )
            )
        return

    # Yangi foydalanuvchi uchun birinchi til tanlash oynasi.
    if account is not None and not getattr(account, 'language_code', None):
        await message.answer(
            t(language, "language_prompt"),
            reply_markup=language_keyboard(language),
        )
    text = t(language, "welcome", name=name)
    if notes:
        text = f"{text}\n\n" + "\n".join(notes)

    await _send_welcome(
        message, text, is_admin(user.id) if user else False, language
    )

    # Taklif hisobi va admin bildirishnomasi ``asyncio.create_task`` bilan
    # orqa fonda yuritiladi: yangi o'yinchi xush kelibsiz xabarini kutmasdan
    # oladi, Supabase yozuvlari esa parallel bajariladi.
    if is_new and account is not None:
        _background(
            _finish_new_user(
                message, economy, inviter_id, user, is_new, account
            )
        )


async def _send_welcome(
    message: Message, text: str, admin: bool, language: str | None = None
) -> None:
    """Menyuni yuboradi; web_app tugmasi rad etilsa, oddiy menyuga qaytadi.

    Mini App havolasiga foydalanuvchi id'si va ismi qo'shiladi, shuning uchun
    pastki klaviaturadan ochilganda ham profil haqiqiy ma'lumot bilan to'ladi.
    """
    user = message.from_user
    menu_kwargs: dict[str, object] = {"is_admin": admin, "language": language}
    if user is not None:
        menu_kwargs.update(
            user_id=user.id,
            username=user.username or "",
            full_name=user.full_name,
        )
    try:
        await message.answer(
            text,
            reply_markup=build_main_menu(**menu_kwargs),
        )
    except TelegramAPIError:
        # Masalan MINI_APP_URL http bo'lsa Telegram web_app tugmasini rad etadi.
        logger.exception("Menyu bilan xabar yuborilmadi, web_app'siz qayta uriniş")
        await message.answer(
            text,
            reply_markup=build_main_menu(
                include_web_app=False, **menu_kwargs
            ),
        )


@router.message(F.chat.type == "private", Command("login"))
async def login_command(message: Message) -> None:
    """``/login`` — Mini App uchun yangi 6 xonali kirish kodi."""
    user = message.from_user
    if user is None:
        return
    try:
        account = get_economy().ensure_user(
            user.id, user.username or "", user.full_name
        )
    except Exception:
        logger.exception("Kiriş kodini yaratib bölmadi: %s", user.id)
        language = resolve_language(
            user.id, getattr(user, "language_code", None)
        )
        await message.answer(t(language, "login_error"))
        return
    await send_login_code(message, account)


@router.message(F.chat.type == "private", F.text.in_(all_button_texts("invite")))
async def invite_friends(message: Message) -> None:
    """👥 Do'stlarni taklif qilish — shaxsiy havola va ishlangan tangalar."""
    user = message.from_user
    if user is None:
        return
    config = get_config()
    economy = get_economy()
    account = None
    try:
        account = _lookup_account(economy, user.id)
        if account is None:
            account = economy.ensure_user(
                user.id, user.username or "", user.full_name
            )
    except Exception:
        # Baza vaqtincha ishlamasa ham havola körsatiladi — xato xabari yöq.
        logger.exception("Taklif ma'lumotlarini öqib bölmadi: %s", user.id)
    if account is None:
        account = UserAccount(
            user_id=int(user.id),
            username=user.username or "",
            full_name=user.full_name or "",
            coins=START_COINS,
            language_code=resolve_language(
                user.id, getattr(user, "language_code", None)
            ),
        )
    await message.answer(
        invite_text(account, config.bot_username),
        reply_markup=invite_keyboard(account, config.bot_username),
    )


# ----------------------------------------------------------------------
# ℹ️ Qoidalar / Yordam
# ----------------------------------------------------------------------
RULES_BUNKER = "rules_bunker"
RULES_MAFIA = "rules_mafia"
RULES_SPY = "rules_spy"
RULES_ALIAS = "rules_alias"
RULES_ECONOMY = "rules_economy"
RULES_BACK = "rules_back"

def rules_keyboard(language: str = "uz") -> InlineKeyboardMarkup:
    """Barcha bo'limlar uchun inline menyu (tanlangan tilda)."""
    sections = (
        (RULES_BUNKER, "rules_tab_bunker"),
        (RULES_MAFIA, "rules_tab_mafia"),
        (RULES_SPY, "rules_tab_spy"),
        (RULES_ALIAS, "rules_tab_alias"),
        (RULES_ECONOMY, "rules_tab_economy"),
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(language, key), callback_data=data)]
            for data, key in sections
        ]
    )


def rules_section_keyboard(language: str = "uz") -> InlineKeyboardMarkup:
    """Bo'lim ichidan menyuga qaytish tugmasi."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(language, "rules_tab_back"), callback_data=RULES_BACK
                )
            ]
        ]
    )


def _callback_language(callback: CallbackQuery) -> str:
    """Callback egasining tili — tugma va matn bir tilda bo'lsin."""
    user = callback.from_user
    return resolve_language(
        getattr(user, "id", None), getattr(user, "language_code", None)
    )


async def _edit_or_send(
    callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup
) -> None:
    """Bo'lim matnini tahrirlaydi, imkoni bo'lmasa yangi xabar yuboradi."""
    message = callback.message
    if message is not None and hasattr(message, "edit_text"):
        try:
            await message.edit_text(text, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            logger.debug("Qoidalar xabarini tahrirlab bölmadi")
    await callback.bot.send_message(
        callback.from_user.id, text, reply_markup=keyboard
    )


@router.message(Command("help", "rules"))
@router.message(F.chat.type == "private", F.text.in_(all_button_texts("rules")))
async def menu_rules(message: Message) -> None:
    """ℹ️ Qoidalar / Yordam — barcha o'yinlar bo'yicha inline menyu."""
    user = message.from_user
    language = resolve_language(
        user.id if user is not None else None,
        getattr(user, "language_code", None) if user is not None else None,
    )
    await message.answer(
        t(language, "help_text"), reply_markup=rules_keyboard(language)
    )


@router.callback_query(F.data == RULES_BUNKER)
async def rules_bunker(callback: CallbackQuery) -> None:
    await callback.answer()
    language = _callback_language(callback)
    await _edit_or_send(
        callback, t(language, "rules_bunker"), rules_section_keyboard(language)
    )


@router.callback_query(F.data == RULES_MAFIA)
async def rules_mafia(callback: CallbackQuery) -> None:
    await callback.answer()
    language = _callback_language(callback)
    await _edit_or_send(
        callback, t(language, "rules_mafia"), rules_section_keyboard(language)
    )


@router.callback_query(F.data == RULES_SPY)
async def rules_spy(callback: CallbackQuery) -> None:
    await callback.answer()
    language = _callback_language(callback)
    await _edit_or_send(
        callback, t(language, "rules_spy"), rules_section_keyboard(language)
    )


@router.callback_query(F.data == RULES_ALIAS)
async def rules_alias(callback: CallbackQuery) -> None:
    await callback.answer()
    language = _callback_language(callback)
    await _edit_or_send(
        callback, t(language, "rules_alias"), rules_section_keyboard(language)
    )


@router.callback_query(F.data == RULES_ECONOMY)
async def rules_economy(callback: CallbackQuery) -> None:
    await callback.answer()
    language = _callback_language(callback)
    await _edit_or_send(
        callback, t(language, "rules_economy"), rules_section_keyboard(language)
    )


@router.callback_query(F.data == RULES_BACK)
async def rules_back(callback: CallbackQuery) -> None:
    await callback.answer()
    language = _callback_language(callback)
    await _edit_or_send(
        callback, t(language, "help_text"), rules_keyboard(language)
    )
