"""Global middleware: bloklangan foydalanuvchilarni botdan to'xtatadi."""

from __future__ import annotations

import logging

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from bot.blocking import blocked_text
from bot.config import get_config
from core.economy import get_economy

logger = logging.getLogger(__name__)


class BlockedUserMiddleware(BaseMiddleware):
    """Bloklangan öyinçining xabar va callbacklarini bajarilishidan oldin to'xtatadi."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user") or getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)
        config = get_config()
        # Bosh admin heç qaçon bloklanmaydi.
        if config.admin_id and int(user.id) == int(config.admin_id):
            return await handler(event, data)
        try:
            account = get_economy().find_user(int(user.id))
            blocked = bool(account is not None and account.is_blocked)
            reason = account.block_reason if account is not None else ""
        except Exception:
            logger.exception("Blok holatini tekşirib bölmadi: %s", user.id)
            blocked = False
            reason = ""
        if not blocked:
            return await handler(event, data)
        text = blocked_text(reason, int(config.admin_id or 0))
        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
        elif isinstance(event, Message) and event.chat.type == "private":
            await event.answer(text)
        return None
