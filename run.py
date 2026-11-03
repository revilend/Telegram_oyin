"""Bot va Mini App API'sini bitta jarayonda ishga tushiradi.

Xonalar xotirada saqlangani uchun aiogram polling va FastAPI bir jarayonda
bo'lishi shart. Aks holda bot ochgan xona API'da ko'rinmaydi.

Ishga tushirish::

    python run.py

Muhit o'zgaruvchilari: ``WEB_HOST`` (standart ``0.0.0.0``), ``WEB_PORT``
(standart ``8000``).
"""

from __future__ import annotations

import asyncio
import logging
import os

import uvicorn
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from api.server import app as api_app
from bot.config import get_config
from bot.main import build_dispatcher, set_commands

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    config = get_config()
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8000"))

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher()
    server = uvicorn.Server(
        uvicorn.Config(api_app, host=host, port=port, log_level="info")
    )

    try:
        await set_commands(bot)
        logger.info("Mini App: http://%s:%s · bot @%s", host, port, config.bot_username)
        polling = asyncio.create_task(dispatcher.start_polling(bot))
        try:
            await server.serve()
        finally:
            server.should_exit = True
            polling.cancel()
            await asyncio.gather(polling, return_exceptions=True)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("To'xtatildi")
