"""Telegram botning kirish nuqtasi: Dispatcher, routerlar va polling."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from bot.localized import LocalizedBot
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import get_config
from core.daily_backup import start_daily_backup, stop_daily_backup
from bot.handlers import (
    testlab,
    admin,
    alias_group,
    bomb_group,
    boosters,
    bunker_group,
    common,
    games_catalog,
    leaderboard,
    mafia_group,
    matchmaking,
    menu,
    missions,
    profile,
    rewards,
    shop,
    spy_group,
    tournaments,
)

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="Revilend Games haqida"),
    BotCommand(command="bunker", description="Yangi Bunker öyini (guruhda)"),
    BotCommand(command="newgame", description="Yangi Bunker öyini (guruhda)"),
    BotCommand(command="mafia", description="Yangi Mafiya öyini (guruhda)"),
    BotCommand(command="spy", description="Yangi Josus öyini (guruhda)"),
    BotCommand(command="alias", description="Yangi Alias öyini (guruhda)"),
    BotCommand(command="bomb", description="Yangi Portlovçi Bomba öyini (guruhda)"),
    BotCommand(command="krokodil", description="Alias: sözni toping (guruhda)"),
    BotCommand(command="matchmaking", description="Global öyin qidiruvi"),
    BotCommand(command="games", description="Öyinlar röyxati"),
    BotCommand(command="missions", description="Missiyalar va mukofotlar"),
    BotCommand(command="rules", description="Barça öyinlar qoidalari"),
    BotCommand(command="login", description="Mini App kiriş kodi"),
    BotCommand(command="shop", description="Tangalar xarid qiliş"),
    BotCommand(command="tournaments", description="Haftalik turnirlar"),
    BotCommand(command="profile", description="Mening profilim"),
    BotCommand(command="top", description="Reyting va Top"),
    BotCommand(command="cancel", description="Jarayonni bekor qiliş"),
    BotCommand(command="test_game", description="Virtual botlar bilan test (admin)"),
]


def build_dispatcher() -> Dispatcher:
    """Routerlarni ulab, tayyor Dispatcher qaytaradi."""
    dispatcher = Dispatcher(storage=MemoryStorage())
    # /cancel har qanday FSM holatida ishlashi uchun birinchi ulanadi.
    dispatcher.include_router(common.cancel_router)
    # /start shop_... deep linki umumiy /start handleridan oldin ushlanishi kerak.
    dispatcher.include_router(shop.router)
    dispatcher.include_router(boosters.router)
    dispatcher.include_router(rewards.router)
    # Missiya tugmalari ``mission_claim_`` callbacklari bilan keladi.
    dispatcher.include_router(missions.router)
    dispatcher.include_router(admin.router)
    dispatcher.include_router(testlab.router)
    # Mafiya callbacklari ``join_mafia_``/``start_mafia_`` bilan boshlanadi,
    # shuning uchun Bunker'dan oldin ulanadi.
    # Alias javoblarini kuzatuvchi handler Mafiya moderatoridan oldin turadi.
    dispatcher.include_router(alias_group.router)
    dispatcher.include_router(mafia_group.router)
    dispatcher.include_router(bunker_group.router)
    # Josus callbacklari ``spy_join_``/``spy_start_`` prefiksi bilan keladi.
    dispatcher.include_router(spy_group.router)
    # Bomb callbacklari ``bomb_join_``/``bomb_start_`` prefiksi bilan keladi.
    dispatcher.include_router(bomb_group.router)
    dispatcher.include_router(games_catalog.router)
    dispatcher.include_router(matchmaking.router)
    dispatcher.include_router(tournaments.router)
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
        logger.exception("Buyruqlar menyusini örnatib bölmadi")


async def main() -> None:
    """Botni ishga tushiradi."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    config = get_config()
    bot = LocalizedBot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher()
    reminders = tournaments.start_reminder_loop(bot)
    # Har kuni 00:00 (Toshkent) da baza zaxirasi adminga yuboriladi.
    backups = start_daily_backup(bot, config.admin_id)

    try:
        await set_commands(bot)
        logger.info("Bot @%s sifatida işga tuşmoqda", config.bot_username)
        await dispatcher.start_polling(bot)
    finally:
        stop_daily_backup(backups)
        reminders.cancel()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot töxtatildi")
    except RuntimeError as exc:
        print(f"Konfiguratsiya xatosi: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
