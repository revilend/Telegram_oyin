"""Tashlab ketilgan o'yin xonalarini fon rejimida tozalash.

Server uzoq vaqt ishlaganda bo'sh lobby'lar va tugallanmagan partiyalar
xotirada to'planib qolmasligi kerak.  :class:`RoomCleaner` har 5 daqiqada
uch o'yin menejerini tekshiradi va muddati o'tgan xonalarni yopadi.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

CLEAN_INTERVAL_SECONDS = 5 * 60
LOBBY_IDLE_SECONDS = 15 * 60
GAME_IDLE_SECONDS = 30 * 60


def _bunker_sweep(
    lobby_idle_seconds: float, game_idle_seconds: float
) -> dict[str, int]:
    from engine.game_manager import get_default_manager

    return get_default_manager().expire_stale(
        lobby_idle_seconds=lobby_idle_seconds,
        game_idle_seconds=game_idle_seconds,
    )


def _mafia_sweep(
    lobby_idle_seconds: float, game_idle_seconds: float
) -> dict[str, int]:
    from bot.handlers.mafia_group import get_default_manager

    return get_default_manager().expire_stale(
        lobby_idle_seconds=lobby_idle_seconds,
        game_idle_seconds=game_idle_seconds,
    )


def _spyfall_sweep(
    lobby_idle_seconds: float, game_idle_seconds: float
) -> dict[str, int]:
    from games.spyfall.manager import get_default_manager

    return get_default_manager().expire_stale(
        lobby_idle_seconds=lobby_idle_seconds,
        game_idle_seconds=game_idle_seconds,
    )


def _alias_sweep(
    lobby_idle_seconds: float, game_idle_seconds: float
) -> dict[str, int]:
    from games.alias.engine import get_default_manager

    return get_default_manager().expire_stale(
        lobby_idle_seconds=lobby_idle_seconds,
        game_idle_seconds=game_idle_seconds,
    )


DEFAULT_SWEEPERS: dict[str, Callable[[float, float], dict[str, int]]] = {
    "bunker": _bunker_sweep,
    "mafia": _mafia_sweep,
    "spyfall": _spyfall_sweep,
    "alias": _alias_sweep,
}


class RoomCleaner:
    """Davriy tozalash vazifasi."""

    def __init__(
        self,
        *,
        interval_seconds: float = CLEAN_INTERVAL_SECONDS,
        lobby_idle_seconds: float = LOBBY_IDLE_SECONDS,
        game_idle_seconds: float = GAME_IDLE_SECONDS,
        sweepers: dict[str, Callable[[float, float], dict[str, int]]] | None = None,
    ) -> None:
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.lobby_idle_seconds = max(1.0, float(lobby_idle_seconds))
        self.game_idle_seconds = max(1.0, float(game_idle_seconds))
        self._sweepers = dict(sweepers or DEFAULT_SWEEPERS)
        self._task: asyncio.Task[None] | None = None
        self.total_expired = 0
        self.total_finished = 0
        self.sweeps = 0

    # ------------------------------------------------------------------
    # Bir marta tozalash
    # ------------------------------------------------------------------
    def sweep_once(self) -> dict[str, dict[str, int]]:
        """Barcha menejerlarni bir marta tekshiradi."""
        report: dict[str, dict[str, int]] = {}
        for name, sweeper in self._sweepers.items():
            try:
                result = sweeper(
                    self.lobby_idle_seconds, self.game_idle_seconds
                )
            except Exception:  # bitta o'yin xatosi boshqalarni to'xtatmaydi
                logger.exception("Xonalarni tozalashda xatolik: %s", name)
                continue
            report[name] = result
            self.total_expired += int(result.get("expired") or 0)
            self.total_finished += int(result.get("finished") or 0)
        self.sweeps += 1
        return report

    # ------------------------------------------------------------------
    # Fon vazifasi
    # ------------------------------------------------------------------
    async def run(self) -> None:
        """Tozallashni to'xtatilgunga qadar davriy bajaradi."""
        logger.info(
            "Xona tozalovchisi ishga tushdi (har %s soniya)", self.interval_seconds
        )
        while True:
            try:
                await asyncio.to_thread(self.sweep_once)
            except asyncio.CancelledError:
                raise
            except Exception:  # kutilmagan xatoda ham davom etamiz
                logger.exception("Tozalash sikli xato bilan tugadi")
            await asyncio.sleep(self.interval_seconds)

    def start(self) -> asyncio.Task[None]:
        """Fon vazifasini boshlaydi (qayta chaqirilsa eskisini qaytaradi)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())
        return self._task

    async def stop(self) -> None:
        """Fon vazifasini bekor qiladi."""
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def stats(self) -> dict[str, Any]:
        """Monitoring uchun tozalash statistikasi."""
        return {
            "sweeps": self.sweeps,
            "expired": self.total_expired,
            "finished": self.total_finished,
            "interval_seconds": self.interval_seconds,
            "lobby_idle_seconds": self.lobby_idle_seconds,
            "game_idle_seconds": self.game_idle_seconds,
        }


_cleaner: RoomCleaner | None = None


def get_cleaner() -> RoomCleaner:
    """Jarayon uchun yagona tozalovchini qaytaradi."""
    global _cleaner
    if _cleaner is None:
        _cleaner = RoomCleaner()
    return _cleaner
