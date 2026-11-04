"""Aiogram chiqish xabarlarini yangi o'zbek lotin yozuviga o'tkazadi."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import TelegramMethod

from core.uzbek_alphabet import new_uzbek_latin


class UzbekAlphabetRequestMiddleware(BaseRequestMiddleware):
    """Bot API so'rovlaridagi matn, izoh va klaviatura yozuvlarini normallashtiradi."""

    async def __call__(
        self,
        make_request: Callable[[Any, TelegramMethod[Any]], Awaitable[Any]],
        bot: Any,
        method: TelegramMethod[Any],
    ) -> Any:
        updates: dict[str, Any] = {}
        for field_name in ("text", "caption"):
            value = getattr(method, field_name, None)
            if isinstance(value, str):
                updates[field_name] = new_uzbek_latin(value)

        markup = getattr(method, "reply_markup", None)
        if markup is not None:
            copied = markup.model_copy(deep=True)
            for collection_name in ("inline_keyboard", "keyboard"):
                rows = getattr(copied, collection_name, None)
                if rows is None:
                    continue
                for row in rows:
                    for button in row:
                        label = getattr(button, "text", None)
                        if isinstance(label, str):
                            button.text = new_uzbek_latin(label)
            updates["reply_markup"] = copied

        if updates:
            method = method.model_copy(update=updates)
        return await make_request(bot, method)
