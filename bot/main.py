"""Telegram botning kirish nuqtasi: Dispatcher, routerlar va polling."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from bot.config import get_config
from bot.handlers import bunker_group, common

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="Revilend Games haqida"),
    BotCommand(command="bunker", description="Yangi Bunker o'yini (guruhda)"),
    BotCommand(command="newgame", description="Yangi Bunker o'yini (guruhda)"),
]


def build_dispatcher() -> Dispatcher:
    """Routerlarni ulab, tayyor Dispatcher qaytaradi."""
    dispatcher = Dispatcher()
    dispatcher.include_router(bunker_group.router)
    dispatcher.include_router(common.router)
    return dispatcher


async def set_commands(bot: Bot) -> None:
    """Bot menyusidagi buyruqlarni o'rnatadi."""
    try:
        await bot.set_my_commands(BOT_COMMANDS)
    except Exception:  # tarmoq xatosi bot ishga tushishiga to'sqinlik qilmasin
        logger.exception("Buyruqlar menyusini o'rnatib bo'lmadi")


async def main() -> None:
    """Botni ishga tushiradi."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    config = get_config()
    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher()

    try:
        await set_commands(bot)
        logger.info("Bot @%s sifatida ishga tushmoqda", config.bot_username)
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatildi")
    except RuntimeError as exc:
        print(f"Konfiguratsiya xatosi: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
