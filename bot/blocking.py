"""Bloklangan foydalanuvchiga sabab va murojaat yo'lini yuborish."""

from __future__ import annotations

import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)


def blocked_text(reason: str = "", admin_id: int = 0) -> str:
    """Blok xabarini sabab va admin murojaati bilan tayyorlaydi."""
    reason_text = escape(str(reason or "").strip() or "Sabab körsatilmagan")
    appeal = (
        f'<a href="tg://user?id={int(admin_id)}">admin bilan böğlaniş</a>'
        if admin_id
        else "admin bilan böğlaning"
    )
    return (
        "🚫 <b>Hisobingiz bloklangan.</b>\n\n"
        f"📋 <b>Sabab:</b> {reason_text}\n\n"
        f"✍️ <b>Murojaat:</b> {appeal}."
    )


async def notify_blocked_user(
    bot: Bot, user_id: int, reason: str, admin_id: int
) -> bool:
    """Bloklangan foydalanuvchiga shaxsiy xabar yuboradi."""
    try:
        await bot.send_message(
            int(user_id), blocked_text(reason, admin_id)
        )
        return True
    except TelegramAPIError:
        logger.info("Blok xabari yuborilmadi: %s", user_id)
        return False
    except Exception:
        logger.exception("Blok xabarida kutilmagan xatolik: %s", user_id)
        return False
