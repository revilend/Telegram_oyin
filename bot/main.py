"""Telegram botning kirish nuqtasi: Dispatcher, routerlar va polling."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent

from bot.config import get_config
from bot.handlers import (
    admin,
    boosters,
    bunker_group,
    common,
    games_catalog,
    leaderboard,
    mafia_group,
    menu,
    missions,
    profile,
    rewards,
    shop,
    spy_group,
)

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="Revilend Games haqida"),
    BotCommand(command="bunker", description="Yangi Bunker o'yini (guruhda)"),
    BotCommand(command="newgame", description="Yangi Bunker o'yini (guruhda)"),
    BotCommand(command="mafia", description="Yangi Mafiya o'yini (guruhda)"),
    BotCommand(command="spy", description="Yangi Josus o'yini (guruhda)"),
    BotCommand(command="games", description="O'yinlar ro'yxati"),
    BotCommand(command="missions", description="Missiyalar va mukofotlar"),
    BotCommand(command="rules", description="Barcha o'yinlar qoidalari"),
    BotCommand(command="login", description="Mini App kirish kodi"),
    BotCommand(command="shop", description="Tangalar xarid qilish"),
    BotCommand(command="profile", description="Mening profilim"),
    BotCommand(command="top", description="Reyting va Top"),
    BotCommand(command="cancel", description="Jarayonni bekor qilish"),
]


async def _log_unhandled_update(event: ErrorEvent) -> bool:
    """Aiogram'da ushlanmagan xatolarni to'liq traceback bilan qayd etadi."""
    exc = event.exception
    logger.error(
        "Unhandled Aiogram update: %s",
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return True


def build_dispatcher() -> Dispatcher:
    """Routerlarni ulab, tayyor Dispatcher qaytaradi."""
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.errors.register(_log_unhandled_update)
    # /cancel har qanday FSM holatida ishlashi uchun birinchi ulanadi.
    dispatcher.include_router(common.cancel_router)
    # /start shop_... deep linki umumiy /start handleridan oldin ushlanishi kerak.
    dispatcher.include_router(shop.router)
    dispatcher.include_router(boosters.router)
    dispatcher.include_router(rewards.router)
    # Missiya tugmalari ``mission_claim_`` callbacklari bilan keladi.
    dispatcher.include_router(missions.router)
    dispatcher.include_router(admin.router)
    # Mafiya callbacklari ``join_mafia_``/``start_mafia_`` bilan boshlanadi,
    # shuning uchun Bunker'dan oldin ulanadi.
    dispatcher.include_router(mafia_group.router)
    dispatcher.include_router(bunker_group.router)
    # Josus callbacklari ``spy_join_``/``spy_start_`` prefiksi bilan keladi.
    dispatcher.include_router(spy_group.router)
    dispatcher.include_router(games_catalog.router)
    dispatcher.include_router(profile.router)
    dispatcher.include_router(leaderboard.router)
    # Doimiy pastki menyu tugmalari /start va boshqa buyruqlardan keyin keladi.
    dispatcher.include_router(menu.router)
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
