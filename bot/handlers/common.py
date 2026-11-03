"""Shaxsiy chatdagi umumiy handlerlar: /start, referallar va taklif menyusi."""

from __future__ import annotations

import logging
from html import escape
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import get_config
from bot.handlers.admin import is_admin
from bot.keyboards.main_menu import INVITE_BUTTON, build_main_menu
from core.economy import (
    REFERRAL_BONUS,
    EconomyError,
    UserAccount,
    format_price,
    get_economy,
    referral_earnings,
)

logger = logging.getLogger(__name__)

router = Router(name="common")

REFERRAL_PREFIX = "ref_"

WELCOME_TEXT = (
    "Salom, <b>{name}</b>! 👋\n\n"
    "<b>Revilend Games</b> — Telegram ichida o'ynaladigan stol o'yinlari platformasi.\n\n"
    "«Bunker» o'yinida falokatdan keyin omon qolish uchun guruh bilan birga qaror "
    "qabul qilasiz: kasbingiz, sog'lig'ingiz va yukingizga qarab kim bunkerga "
    "tushishini aniqlaysiz.\n\n"
    "🎮 O'yinlarni ochish uchun pastdagi menyudan foydalaning.\n"
    "➕ Guruhda yangi o'yin ochish uchun: /bunker"
)

WELCOME_ONLY_TEXT = (
    "Salom, <b>{name}</b>! 👋\n\n"
    "O'yinni faqat guruhda ochish mumkin: botni guruhga qo'shib, /bunker yuboring."
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
    return (
        "👥 <b>Do'stlarni taklif qiling va tanga ishlang!</b>\n\n"
        f"Har bir taklif qilgan yangi do'stingiz uchun "
        f"<b>+{REFERRAL_BONUS} tanga</b> olasiz!\n\n"
        "🔗 <b>Sizning taklif havolangiz:</b>\n"
        f"<code>{link}</code>\n\n"
        f"📊 Siz taklif qilganlar: <b>{format_price(count)}</b> kishi\n"
        f"🪙 Ishlangan tangalar: <b>{format_price(referral_earnings(account))}</b> tanga"
    )


def invite_keyboard(account: UserAccount, bot_username: str) -> InlineKeyboardMarkup:
    """Do'stlarga ulashish tugmasi."""
    link = referral_link(bot_username, account.user_id)
    share_text = (
        "Revilend Games — Bunker o'yinini birga o'ynaymiz! 🎮 "
        f"Taklif havolam: {link}"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Do'stlarga yuborish",
                    url=(
                        "https://t.me/share/url"
                        f"?url={quote(link, safe='')}"
                        f"&text={quote(share_text, safe='')}"
                    ),
                )
            ]
        ]
    )


async def _notify_inviter(
    bot: Bot, result, invited_name: str
) -> None:
    """Taklif qilganga bot nomidan minnatdorchilik xabarini yuboradi."""
    text = (
        f"🎉 Do'stingiz ({escape(invited_name)}) taklifingiz bilan qo'shildi! "
        f"Sizga +{format_price(result.bonus)} tanga berildi 🪙"
    )
    try:
        await bot.send_message(result.inviter_id, text)
    except TelegramAPIError:
        logger.info("Taklif egasiga xabar yuborilmadi: %s", result.inviter_id)
    except Exception:
        logger.exception("Taklif egasiga xabar yuborishda xatolik")


# ----------------------------------------------------------------------
# Handlerlar
# ----------------------------------------------------------------------
@router.message(CommandStart())
async def start_command(message: Message, command: CommandObject | None = None) -> None:
    """/start — xush kelibsiz xabari, doimiy menyu va referal hisobi."""
    user = message.from_user
    if message.chat.type != "private":
        await message.answer(
            "Yangi Bunker o'yinini ochish uchun /bunker yoki /newgame buyrug'ini yuboring."
        )
        return

    name = escape(user.full_name if user else "do'stim")
    economy = get_economy()
    notes: list[str] = []

    if user is not None:
        inviter_id = parse_referral_arg(command.args if command is not None else None)
        try:
            is_new = not economy.has_user(user.id)
            account = economy.ensure_user(
                user.id, user.username or "", user.full_name
            )
            if is_new:
                notes.append(
                    f"🎁 Ro'yxatdan o'tganingiz uchun <b>{format_price(account.coins)}</b> "
                    "bepul tanga berildi!"
                )
                if inviter_id is not None and inviter_id != user.id:
                    result = economy.register_referral(inviter_id, user.id)
                    if result is not None:
                        await _notify_inviter(message.bot, result, user.full_name)
        except EconomyError as exc:
            logger.exception("Foydalanuvchini saqlab bo'lmadi: %s", user.id)
            notes.append(f"⚠️ {escape(str(exc))}")
        except Exception:
            logger.exception("Foydalanuvchini saqlab bo'lmadi: %s", user.id)

    text = WELCOME_TEXT.format(name=name)
    if notes:
        text = f"{text}\n\n" + "\n".join(notes)

    await _send_welcome(message, text, is_admin(user.id) if user else False)


async def _send_welcome(message: Message, text: str, admin: bool) -> None:
    """Menyuni yuboradi; web_app tugmasi rad etilsa, oddiy menyuga qaytadi."""
    try:
        await message.answer(
            text,
            reply_markup=build_main_menu(is_admin=admin),
        )
    except TelegramAPIError:
        # Masalan MINI_APP_URL http bo'lsa Telegram web_app tugmasini rad etadi.
        logger.exception("Menyu bilan xabar yuborilmadi, web_app'siz qayta urinish")
        await message.answer(
            text,
            reply_markup=build_main_menu(is_admin=admin, include_web_app=False),
        )


@router.message(F.chat.type == "private", F.text == INVITE_BUTTON)
async def invite_friends(message: Message) -> None:
    """👥 Do'stlarni taklif qilish — shaxsiy havola va ishlangan tangalar."""
    user = message.from_user
    if user is None:
        return
    config = get_config()
    try:
        account = get_economy().ensure_user(
            user.id, user.username or "", user.full_name
        )
    except Exception:
        logger.exception("Taklif ma'lumotlarini yuklab bo'lmadi: %s", user.id)
        await message.answer(
            "⚠️ Taklif ma'lumotlarini yuklab bo'lmadi. Birozdan keyin urinib ko'ring."
        )
        return
    await message.answer(
        invite_text(account, config.bot_username),
        reply_markup=invite_keyboard(account, config.bot_username),
    )
