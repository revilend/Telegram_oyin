"""«Xavfli Bomba» xonalari menejeri.

Guruh boti ham, Mini App API ham **shu** menejerni ishlatadi, shuning uchun
botda ochilgan xona Mini App'da darhol ko'rinadi. Xona holati Supabase'dagi
``bomb_rooms`` jadvaliga JSONB sifatida yoziladi va qayta ishga tushganda
kod bo'yicha yoki startupda tiklanadi.
"""

from __future__ import annotations

import random
import threading
from typing import Callable

from core import room_store
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
        self._on_change: Callable[[BombRoom], None] | None = None
        self._room_loader: Callable[[str], BombRoom | None] | None = None

    # ------------------------------------------------------------------
    # Saqlash integratsiyasi
    # ------------------------------------------------------------------
    def set_change_handler(
        self, handler: Callable[[BombRoom], None] | None
    ) -> None:
        """Har bir o'zgarishdan keyin chaqiriladigan saqlash funksiyasi."""
        self._on_change = handler

    def set_room_loader(
        self, loader: Callable[[str], BombRoom | None] | None
    ) -> None:
        """Xona xotirada bo'lmasa chaqiriladigan yuklash funksiyasi."""
        self._room_loader = loader

    def save(self, room: BombRoom) -> None:
        """Xonani darhol saqlashga yuboradi (API/bot amallari uchun)."""
        self._persist(room)

    def _persist(self, room: BombRoom) -> None:
        handler = self._on_change
        if handler is None:
            return
        try:
            handler(room)
        except Exception:
            logger.exception("Bomb %s xonasini saqlab bo'lmadi", room.code)

    def _restore(self, code: str) -> BombRoom | None:
        loader = self._room_loader
        if loader is None:
            return None
        try:
            return loader(code)
        except Exception:
            logger.exception("Bomb %s xonasini yuklab bo'lmadi", code)
            return None

    def sync_from_store(self) -> int:
        """Bazadagi tugamagan Bomb xonalarini xotiraga qaytaradi."""
        restored = 0
        for state in room_store.load_states(room_store.BOMB_ROOMS_TABLE):
            try:
                room = BombRoom.from_state(state)
            except Exception:
                logger.exception("Bomb xonasini bazadan tiklab bo'lmadi")
                continue
            if room.status is BombStatus.FINISHED:
                continue
            with self._lock:
                if room.code not in self._rooms:
                    self._rooms[room.code] = room
                    restored += 1
        if restored:
            logger.info("Bomb: bazadan %s ta xona tiklandi", restored)
        return restored

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
            self._persist(room)
            return room

    def get_room(self, code: str) -> BombRoom:
        """Kod bo'yicha xonani qaytaradi (kerak bo'lsa bazadan tiklaydi)."""
        normalized = (code or "").strip().upper()
        with self._lock:
            room = self._rooms.get(normalized)
            if room is None:
                room = self._restore(normalized)
                if room is not None:
                    self._rooms[normalized] = room
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
            self._persist(room)
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
            self._persist(room)
            return room

    def drop(self, code: str) -> None:
        """Xonani xotiradan olib tashlaydi."""
        normalized = (code or "").strip().upper()
        with self._lock:
            self._rooms.pop(normalized, None)
        room_store.delete_state(room_store.BOMB_ROOMS_TABLE, normalized)

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
