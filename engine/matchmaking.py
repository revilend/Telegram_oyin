"""Global o'yin navbati: o'yinchilarni o'yin turi bo'yicha juftlaydi.

Modul Telegram va xona menejerlariga bevosita bog'lanmagan. Xona yaratish va
shaxsiy xabar yuborish callbacklari tashqaridan beriladi; shu sababli mavjud
Bunker/Mafiya/Josus dvigatellari almashtirilmaydi.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any

MIN_PLAYERS: dict[str, int] = {"bunker": 5, "mafia": 6, "spyfall": 3}


class MatchmakingError(ValueError):
    """Navbatga qo'shilish yoki undan chiqish xatosi."""


RoomFactory = Callable[[str, list[dict[str, Any]]], str | Awaitable[str]]
Notifier = Callable[[int, str], Any | Awaitable[Any]]


class Matchmaking:
    """Jarayon ichidagi global navbat, bir foydalanuvchi uchun bitta yozuv."""

    def __init__(
        self,
        room_factory: RoomFactory | None = None,
        notifier: Notifier | None = None,
        *,
        thresholds: dict[str, int] | None = None,
    ) -> None:
        self.queue: dict[str, list[dict[str, Any]]] = {
            game: [] for game in MIN_PLAYERS
        }
        self.thresholds = dict(MIN_PLAYERS)
        if thresholds:
            self.thresholds.update(thresholds)
        self.room_factory = room_factory
        self.notifier = notifier
        self._lock = asyncio.Lock()

    async def _call(self, callback: Callable[..., Any], *args: Any) -> Any:
        result = callback(*args)
        return await result if inspect.isawaitable(result) else result

    async def join_queue(
        self,
        user_id: int,
        game_type: str,
        *,
        name: str = "",
        username: str = "",
    ) -> dict[str, Any]:
        """Navbatga qo'shadi; yetarli odam bo'lsa xona factory'sini chaqiradi."""
        game = str(game_type).strip().lower()
        if game not in self.thresholds:
            raise MatchmakingError(f"Noma'lum o'yin turi: {game}")
        uid = int(user_id)
        if uid <= 0:
            raise MatchmakingError("Foydalanuvchi ID noto'g'ri")

        async with self._lock:
            # Bitta foydalanuvchi barcha o'yin navbatlarida faqat bir marta turadi.
            for queue in self.queue.values():
                queue[:] = [entry for entry in queue if entry["user_id"] != uid]

            entry = {
                "user_id": uid,
                "name": str(name or "").strip(),
                "username": str(username or "").strip(),
                "game_type": game,
                "joined_at": time.time(),
            }
            self.queue[game].append(entry)
            needed = self.thresholds[game]
            waiting = self.queue[game]
            if len(waiting) < needed:
                return {
                    "status": "waiting",
                    "game_type": game,
                    "count": len(waiting),
                    "required": needed,
                }

            # Xona yaratish muvaffaqiyatsiz bo'lsa, hech kim navbatdan yo'qolmaydi.
            matched = waiting[:needed]
            if self.room_factory is None:
                return {
                    "status": "ready",
                    "game_type": game,
                    "count": len(waiting),
                    "required": needed,
                    "players": [dict(item) for item in matched],
                }
            try:
                room_code = await self._call(
                    self.room_factory, game, [dict(item) for item in matched]
                )
            except Exception:
                raise
            if not room_code:
                raise MatchmakingError("Xona yaratilmadi; navbat saqlab qolindi")
            del waiting[:needed]

        # Tarmoq orqali xabarlar lock tashqarisida yuboriladi.
        if self.notifier is not None:
            message = (
                f"🎮 Siz uchun {game.title()} xonasi tayyor! "
                f"Xona kodi: {room_code}"
            )
            for player in matched:
                try:
                    await self._call(self.notifier, player["user_id"], message)
                except Exception:
                    # Bir foydalanuvchiga xabar yetmasligi qolganlarga ta'sir qilmasin.
                    continue

        return {
            "status": "matched",
            "game_type": game,
            "room_code": str(room_code),
            "count": needed,
            "required": needed,
            "players": [dict(item) for item in matched],
        }

    async def leave_queue(self, user_id: int) -> dict[str, int]:
        """Foydalanuvchini barcha navbatlardan chiqaradi."""
        uid = int(user_id)
        removed: dict[str, int] = {}
        async with self._lock:
            for game, waiting in self.queue.items():
                before = len(waiting)
                waiting[:] = [entry for entry in waiting if entry["user_id"] != uid]
                if before != len(waiting):
                    removed[game] = before - len(waiting)
        return removed

    async def status(self, game_type: str) -> dict[str, int | str]:
        """Mini App hisoblagichi uchun navbat holati."""
        game = str(game_type).strip().lower()
        if game not in self.thresholds:
            raise MatchmakingError(f"Noma'lum o'yin turi: {game}")
        async with self._lock:
            return {
                "game_type": game,
                "count": len(self.queue[game]),
                "required": self.thresholds[game],
            }


_default_matchmaking: Matchmaking | None = None


def get_matchmaking() -> Matchmaking:
    """Standart umumiy navbat instansiyasi."""
    global _default_matchmaking
    if _default_matchmaking is None:
        _default_matchmaking = Matchmaking()
    return _default_matchmaking


def set_matchmaking(instance: Matchmaking | None) -> None:
    """Test yoki ilova lifespan'i uchun umumiy instansiyani almashtiradi."""
    global _default_matchmaking
    _default_matchmaking = instance
