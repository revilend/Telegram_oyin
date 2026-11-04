"""Botning foydalanuvchiga ko'rinadigan matnlarini yangi alifboga o'giradi.

Barcha handlerlar ``Message.answer`` va ``callback.bot.send_message`` kabi
yuqori darajadagi metodlardan foydalanadi.  Shu sababli konvertatsiya bitta
Bot qatlamida bajariladi: matn, izoh, callback javobi va tugma yozuvlari.
Buyruqlar va havolalar ``core.orthography`` tomonidan himoyalanadi.
"""

from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)

from core.orthography import to_new_alphabet


def localize_markup(markup: Any) -> Any:
    """Inline yoki reply klaviaturasidagi tugma yozuvlarini o'giradi."""
    if markup is None:
        return None
    if isinstance(markup, (InlineKeyboardMarkup, ReplyKeyboardMarkup)):
        copy = markup.model_copy(deep=True)
        for row in copy.inline_keyboard if isinstance(copy, InlineKeyboardMarkup) else copy.keyboard:
            for button in row:
                button.text = to_new_alphabet(button.text)
        return copy
    return markup


class LocalizedBot(Bot):
    """Aiogram Bot bilan bir xil, lekin chiqadigan matnlarni o'giradi."""

    async def send_message(self, chat_id: Any, text: str, *args: Any, **kwargs: Any) -> Any:
        kwargs["reply_markup"] = localize_markup(kwargs.get("reply_markup"))
        return await super().send_message(chat_id, to_new_alphabet(text), *args, **kwargs)

    async def send_photo(self, chat_id: Any, photo: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("caption") is not None:
            kwargs["caption"] = to_new_alphabet(str(kwargs["caption"]))
        kwargs["reply_markup"] = localize_markup(kwargs.get("reply_markup"))
        return await super().send_photo(chat_id, photo, *args, **kwargs)

    async def send_document(self, chat_id: Any, document: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("caption") is not None:
            kwargs["caption"] = to_new_alphabet(str(kwargs["caption"]))
        kwargs["reply_markup"] = localize_markup(kwargs.get("reply_markup"))
        return await super().send_document(chat_id, document, *args, **kwargs)

    async def send_animation(self, chat_id: Any, animation: Any, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("caption") is not None:
            kwargs["caption"] = to_new_alphabet(str(kwargs["caption"]))
        kwargs["reply_markup"] = localize_markup(kwargs.get("reply_markup"))
        return await super().send_animation(chat_id, animation, *args, **kwargs)

    async def edit_message_text(self, text: str | None = None, *args: Any, **kwargs: Any) -> Any:
        kwargs["reply_markup"] = localize_markup(kwargs.get("reply_markup"))
        return await super().edit_message_text(
            to_new_alphabet(text) if text is not None else None, *args, **kwargs
        )

    async def edit_message_caption(self, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("caption") is not None:
            kwargs["caption"] = to_new_alphabet(str(kwargs["caption"]))
        kwargs["reply_markup"] = localize_markup(kwargs.get("reply_markup"))
        return await super().edit_message_caption(*args, **kwargs)

    async def answer_callback_query(
        self, callback_query_id: str, text: str | None = None, *args: Any, **kwargs: Any
    ) -> Any:
        return await super().answer_callback_query(
            callback_query_id,
            to_new_alphabet(text) if text is not None else None,
            *args,
            **kwargs,
        )

    async def set_my_commands(self, commands: list[BotCommand], *args: Any, **kwargs: Any) -> Any:
        localized = [
            command.model_copy(update={"description": to_new_alphabet(command.description)})
            for command in commands
        ]
        return await super().set_my_commands(localized, *args, **kwargs)

    async def edit_message_reply_markup(self, *args: Any, **kwargs: Any) -> Any:
        kwargs["reply_markup"] = localize_markup(kwargs.get("reply_markup"))
        return await super().edit_message_reply_markup(*args, **kwargs)


__all__ = ["LocalizedBot", "localize_markup"]
