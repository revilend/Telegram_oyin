"""Har 5 daqiqada faol bo'lmagan o'yin xonalarini tozalash."""
from __future__ import annotations

import asyncio
import logging

from bot.handlers import mafia_group
from engine.game_manager import get_default_manager
from games.spyfall.manager import get_default_manager as get_spyfall_manager

logger = logging.getLogger(__name__)

CLEAN_INTERVAL_SECONDS = 300
LOBBY_TIMEOUT_SECONDS = 15 * 60
ACTIVE_TIMEOUT_SECONDS = 30 * 60


def clean_once() -> dict[str, list[str]]:
    """Barcha o'yin menejerlarida muddati o'tgan xonalarni tekshiradi."""
    removed = {
        "bunker": get_default_manager().expire_inactive(
            lobby_seconds=LOBBY_TIMEOUT_SECONDS,
            active_seconds=ACTIVE_TIMEOUT_SECONDS,
        ),
        "mafia": mafia_group.get_default_manager().expire_inactive(
            lobby_seconds=LOBBY_TIMEOUT_SECONDS,
            active_seconds=ACTIVE_TIMEOUT_SECONDS,
        ),
        "spyfall": get_spyfall_manager().expire_inactive(
            lobby_seconds=LOBBY_TIMEOUT_SECONDS,
            active_seconds=ACTIVE_TIMEOUT_SECONDS,
        ),
    }
    total = sum(len(codes) for codes in removed.values())
    if total:
        logger.info("Faolsiz xonalar yopildi: %s", removed)
    return removed


async def cleaner_loop() -> None:
    """Server ishlayotgan paytda har 5 daqiqada tozalashni bajaradi."""
    while True:
        try:
            await asyncio.to_thread(clean_once)
        except Exception:
            logger.exception("Avtomatik xona tozalashda xatolik")
        await asyncio.sleep(CLEAN_INTERVAL_SECONDS)
