"""Faqat ADMIN_ID uchun admin panel buyruqlari."""

from __future__ import annotations

import asyncio
import logging
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.config import get_config
from core.economy import EconomyError, format_price, get_economy
from engine.game_manager import get_default_manager

logger = logging.getLogger(__name__)

router = Router(name="admin")


def is_admin(user_id: int) -> bool:
    """ADMIN_ID bilan mos kelsa yoki `users.role` ``admin`` bo'lsa ruxsat beradi."""
    config = get_config()
    if config.admin_id and int(user_id) == config.admin_id:
        return True
    try:
        return get_economy().is_admin_user(int(user_id))
    except Exception:
        logger.exception("`users` jadvalida rolni tekshirib bo'lmadi: %s", user_id)
        return False


async def _reply_denied(message: Message) -> None:
    await message.answer("⛔ Bu buyruq faqat administrator uchun.")


@router.message(Command("admin"))
async def admin_panel(message: Message) -> None:
    """/admin — foydalanuvchilar, tangalar va xonalar statistikasi."""
    if not is_admin(message.from_user.id):
        await _reply_denied(message)
        return
    try:
        economy = get_economy()
        manager = get_default_manager()
        stats = economy.stats(
            active_rooms=manager.active_room_count,
            total_rooms=manager.total_room_count,
        )
        text = (
            "🛠 <b>Admin panel</b>\n\n"
            f"👥 Jami o'yinchilar: <b>{stats['users']}</b>\n"
            f"🪙 Umumiy xarid qilingan tangalar: <b>{format_price(stats['coins_purchased'])}</b>\n"
            f"💰 Balanslardagi tangalar: <b>{format_price(stats['coins_in_balance'])}</b>\n"
            f"🏠 Faol xonalar: <b>{stats['active_rooms']}</b>\n"
            f"🗂 Jami xonalar: <b>{stats['total_rooms']}</b>\n\n"
            "Buyruqlar:\n"
            "<code>/give &lt;user_id&gt; &lt;miqdor&gt;</code> — tanga berish\n"
            "<code>/user &lt;user_id&gt;</code> — o'yinchini tekshirish\n"
            "<code>/broadcast &lt;matn&gt;</code> — hammaga xabar"
        )
        await message.answer(text)
    except Exception as exc:
        logger.exception("Admin statistikasida xatolik")
        await message.answer(f"⚠️ Xatolik: {escape(str(exc))}")


@router.message(Command("give"))
async def give_coins(message: Message, command: CommandObject) -> None:
    """/give <user_id> <miqdor> — qo'lda tanga berish."""
    if not is_admin(message.from_user.id):
        await _reply_denied(message)
        return
    args = (command.args or "").split()
    if len(args) != 2:
        await message.answer("Format: <code>/give 123456789 500</code>")
        return
    try:
        user_id = int(args[0])
        amount = int(args[1].replace(" ", ""))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("user_id va miqdor musbat butun son bo'lishi kerak.")
        return
    try:
        account = get_economy().add_coins(user_id, amount)
    except EconomyError as exc:
        await message.answer(f"⚠️ {escape(str(exc))}")
        return
    await message.answer(
        f"✅ <code>{user_id}</code>ga <b>+{format_price(amount)}</b> tanga qo'shildi.\n"
        f"Yangi balans: <b>{format_price(account.coins)}</b> tanga."
    )


@router.message(Command("user"))
async def user_info(message: Message, command: CommandObject) -> None:
    """/user <user_id> — balans, o'yinlar va g'alabalar."""
    if not is_admin(message.from_user.id):
        await _reply_denied(message)
        return
    raw = (command.args or "").strip().split()[0] if (command.args or "").strip() else ""
    try:
        user_id = int(raw)
    except ValueError:
        await message.answer("Format: <code>/user 123456789</code>")
        return
    try:
        account = get_economy().ensure_user(user_id)
    except EconomyError as exc:
        await message.answer(f"⚠️ {escape(str(exc))}")
        return
    name = account.full_name or account.username or "Ismsiz"
    await message.answer(
        "👤 <b>O'yinchi</b>\n"
        f"Ism: {escape(name)}\n"
        f"Username: {'@' + escape(account.username) if account.username else '—'}\n"
        f"🆔 <code>{account.user_id}</code>\n"
        f"🪙 Balans: <b>{format_price(account.coins)}</b> tanga\n"
        f"🛒 Xarid qilingan: <b>{format_price(account.total_purchased)}</b> tanga\n"
        f"🎮 O'ynagan o'yinlari: <b>{account.games_played}</b>\n"
        f"🏆 G'alabalari: <b>{account.wins}</b>"
    )


@router.message(Command("broadcast"))
async def broadcast(message: Message, command: CommandObject) -> None:
    """/broadcast <matn> — barcha ro'yxatdan o'tgan o'yinchilarga xabar."""
    if not is_admin(message.from_user.id):
        await _reply_denied(message)
        return
    text = (command.args or "").strip()
    if not text:
        await message.answer("Format: <code>/broadcast E'lon matni</code>")
        return
    user_ids = get_economy().list_user_ids()
    if not user_ids:
        await message.answer("ℹ️ Hali ro'yxatdan o'tgan o'yinchilar yo'q.")
        return

    sent = 0
    failed = 0
    for user_id in user_ids:
        try:
            await message.bot.send_message(user_id, text)
            sent += 1
        except TelegramAPIError:
            failed += 1
        except Exception:
            failed += 1
            logger.exception("Broadcast yuborishda xatolik: %s", user_id)
        await asyncio.sleep(0.04)

    await message.answer(
        f"📣 Broadcast tugadi: <b>{sent}</b> ta yuborildi, "
        f"<b>{failed}</b> ta yetkazilmadi."
    )
