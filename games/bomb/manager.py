"""«Xavfli Bomba» xonalari menejeri.

Guruh boti ham, Mini App API ham **shu** menejerni ishlatadi, shuning uchun
botda ochilgan xona Mini App'da darhol ko'rinadi. Xonalar hozircha xotirada
saqlanadi; keyingi bosqichda Supabase jadvaliga ko'chirish mumkin.
"""

from __future__ import annotations

import random
import threading

from games.bomb.engine import BombError, BombRoom, BombStatus

CODE_PREFIX = "BMB"
CODE_DIGITS = 3
MAX_LOBBY_AGE_SECONDS = 30 * 60


class BombRoomError(BombError):
    """Bomb xonasi amali bajarilmadi."""


class BombNotFoundError(BombRoomError):
    """Berilgan kodli Bomb xonasi topilmadi."""


class BombManager:
    """Bomb xonalari reyestri va lobbi amallari."""

    def __init__(
        self,
        *,
        seed: int | None = None,
        coin_award: object | None = None,
    ) -> None:
        self._rooms: dict[str, BombRoom] = {}
        self._lock = threading.RLock()
        self._rng = random.Random(seed)
        self._coin_award = coin_award

    def _new_code(self) -> str:
        for _ in range(1000):
            number = self._rng.randint(0, 10**CODE_DIGITS - 1)
            code = f"{CODE_PREFIX}{number:0{CODE_DIGITS}d}"
            if code not in self._rooms:
                return code
        raise BombRoomError("Bo'sh Bomb xona kodi topilmadi, keyinroq urinib köring")

    def create_room(
        self,
        host_id: int,
        host_name: str = "",
        *,
        chat_id: int = 0,
    ) -> BombRoom:
        """Yangi xona ochadi va xona egasini qo'shadi."""
        with self._lock:
            room = BombRoom(
                self._new_code(),
                rng=self._rng,
                coin_award=self._coin_award,
                chat_id=chat_id,
            )
            room.add_player(host_id, host_name, is_host=True)
            self._rooms[room.code] = room
            return room

    def get_room(self, code: str) -> BombRoom:
        """Kod bo'yicha xonani qaytaradi."""
        normalized = (code or "").strip().upper()
        with self._lock:
            room = self._rooms.get(normalized)
        if room is None:
            raise BombNotFoundError(
                f"'{normalized or code}' kodli Bomb xonasi topilmadi"
            )
        return room

    def join(self, code: str, user_id: int, name: str = "") -> BombRoom:
        """O'yinchini lobbiga qo'shadi."""
        with self._lock:
            room = self.get_room(code)
            room.add_player(user_id, name)
            return room

    def start(self, code: str, user_id: int) -> BombRoom:
        """O'yinni boshlaydi; faqat xona egasi boshlashi mumkin."""
        with self._lock:
            room = self.get_room(code)
            if room.host_id is not None and int(user_id) != room.host_id:
                raise BombRoomError("Öyinni faqat xona egasi boşlashi mumkin")
            if room.status is not BombStatus.LOBBY:
                raise BombRoomError("Bu xonada öyin allaqachon boşlangan")
            try:
                room.start()
            except BombError as exc:
                raise BombRoomError(str(exc)) from exc
            return room

    def drop(self, code: str) -> None:
        """Xonani xotiradan olib tashlaydi."""
        normalized = (code or "").strip().upper()
        with self._lock:
            self._rooms.pop(normalized, None)

    def reset(self) -> None:
        """Barcha xonalarni tozalaydi (testlar uchun)."""
        with self._lock:
            self._rooms.clear()

    @property
    def room_count(self) -> int:
        with self._lock:
            return len(self._rooms)


_MANAGER: BombManager | None = None
_MANAGER_LOCK = threading.RLock()


def get_default_manager() -> BombManager:
    """Global Bomb menejerini qaytaradi."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = BombManager()
        return _MANAGER


def set_default_manager(manager: BombManager | None) -> None:
    """Testlar uchun global menejerni almashtiradi."""
    global _MANAGER
    with _MANAGER_LOCK:
        _MANAGER = manager


__all__ = [
    "BombManager",
    "BombNotFoundError",
    "BombRoomError",
    "CODE_DIGITS",
    "CODE_PREFIX",
    "MAX_LOBBY_AGE_SECONDS",
    "get_default_manager",
    "set_default_manager",
]
