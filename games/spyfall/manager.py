"""Josus xonalari reyestri: guruh boti va Mini App uchun umumiy menejer.

Menejer xonalarni kod bo'yicha xotirada saqlaydi va Supabase sozlangan
bo'lsa ``spyfall_rooms`` jadvaliga (JSONB holat) yozadi. Guruh handleri
ham, REST API ham **shu** menejerni ishlatadi — shuning uchun botda
ochilgan xona Mini App'da darhol ko'rinadi.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any

from core.db import get_store
from core.economy import EconomyStore, InsufficientCoinsError, get_economy
from games.spyfall.engine import (
    HINT_PRICE,
    MAX_PLAYERS,
    GuessOutcome,
    Phase,
    SpyfallError,
    SpyfallRoom,
    VoteOutcome,
)

logger = logging.getLogger(__name__)

SPYFALL_TABLE = "spyfall_rooms"
CODE_PREFIX = "SPY"
CODE_DIGITS = 3


class SpyfallRoomError(SpyfallError):
    """Amal ruxsat etilmagan yoki o'yin holati mos emas."""


class SpyfallNotFoundError(SpyfallRoomError):
    """Berilgan kodli xona topilmadi."""


class SpyfallManager:
    """Xonalar reyestri va o'yin amallari."""

    def __init__(self, *, seed: int | None = None) -> None:
        self._rooms: dict[str, SpyfallRoom] = {}
        self._times: dict[str, float] = {}
        self._lock = threading.RLock()
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------ kod
    def _new_code(self) -> str:
        for _ in range(1000):
            code = f"{CODE_PREFIX}{self._rng.randint(0, 10**CODE_DIGITS - 1):0{CODE_DIGITS}d}"
            if code not in self._rooms:
                return code
        raise SpyfallRoomError("Bo'sh Josus xonasi kodi topilmadi, keyinroq urinib ko'ring")

    # ------------------------------------------------------------------ xona
    def create_room(
        self,
        host_id: int,
        host_name: str = "",
        *,
        chat_id: int = 0,
    ) -> SpyfallRoom:
        """Yangi xona ochadi va hostni qo'shadi."""
        with self._lock:
            room = SpyfallRoom(self._new_code(), host_id, chat_id=chat_id)
            room.add_player(host_id, host_name, is_host=True)
            self._rooms[room.code] = room
            self._times[room.code] = time.time()
            self._persist(room)
            return room

    def get_room(self, code: str) -> SpyfallRoom:
        """Kod bo'yicha xonani qaytaradi (kerak bo'lsa bazadan tiklaydi)."""
        normalized = (code or "").strip().upper()
        with self._lock:
            room = self._rooms.get(normalized)
            if room is None:
                room = self._restore(normalized)
                if room is not None:
                    self._rooms[normalized] = room
            if room is None:
                raise SpyfallNotFoundError(
                    f"'{normalized or code}' kodli Josus xonasi topilmadi"
                )
            self._times[normalized] = time.time()
            return room

    def prune_lobbies(self, max_age_seconds: int = 30 * 60) -> int:
        """Uzoq vaqt harakatsiz qolgan Josus lobby'larini yopadi."""
        now = time.time()
        removed = 0
        with self._lock:
            for code, room in list(self._rooms.items()):
                if room.phase is not Phase.LOBBY:
                    continue
                if now - self._times.get(code, now) > max_age_seconds:
                    self._rooms.pop(code, None)
                    self._times.pop(code, None)
                    removed += 1
        return removed

    def expire_stale(
        self,
        *,
        lobby_idle_seconds: float = 15 * 60,
        game_idle_seconds: float = 30 * 60,
    ) -> dict[str, int]:
        """Tashlab ketilgan Josus xonalarini yopadi va xotiradan olib tashlaydi."""
        now = time.time()
        expired = 0
        finished = 0
        with self._lock:
            for code, room in list(self._rooms.items()):
                idle = now - self._times.get(code, now)
                if room.phase is Phase.LOBBY and idle > lobby_idle_seconds:
                    room.phase = Phase.EXPIRED
                    self._rooms.pop(code, None)
                    self._times.pop(code, None)
                    expired += 1
                elif (
                    room.phase in (Phase.PLAYING, Phase.VOTING)
                    and idle > game_idle_seconds
                ):
                    room.phase = Phase.FINISHED
                    self._rooms.pop(code, None)
                    self._times.pop(code, None)
                    finished += 1
        if expired or finished:
            logger.info(
                "Josus xonalari tozalandi: %s ta muddati o'tgan, %s ta yopilgan",
                expired,
                finished,
            )
        return {"expired": expired, "finished": finished}

    def open_rooms(self, limit: int = 50) -> list[SpyfallRoom]:
        """Global qidiruv uchun ochiq Josus lobby'lari."""
        self.prune_lobbies()
        with self._lock:
            rooms = [room for room in self._rooms.values() if room.phase is Phase.LOBBY]
            rooms.sort(key=lambda room: self._times.get(room.code, 0), reverse=True)
            return rooms[: max(1, int(limit))]

    def join(self, code: str, user_id: int, name: str = "") -> SpyfallRoom:
        """O'yinchini xonaga qo'shadi."""
        with self._lock:
            room = self.get_room(code)
            room.add_player(user_id, name)
            self._persist(room)
            return room

    def start(
        self, code: str, user_id: int, *, now: float | None = None
    ) -> SpyfallRoom:
        """O'yinni boshlaydi (faqat host)."""
        with self._lock:
            room = self.get_room(code)
            if int(user_id) != room.host_id:
                raise SpyfallRoomError("O'yinni faqat xona egasi boshlashi mumkin")
            room.start(now=now, rng=self._rng)
            self._persist(room)
            return room

    def guess(
        self,
        code: str,
        user_id: int,
        location_key: str,
        *,
        economy: EconomyStore | None = None,
        now: float | None = None,
    ) -> tuple[SpyfallRoom, GuessOutcome]:
        """Josus joyni taxmin qiladi va mukofotlarni tarqatadi."""
        with self._lock:
            room = self.get_room(code)
            outcome = room.guess(user_id, location_key, now=now)
            self._award(room, economy)
            self._persist(room)
            return room, outcome

    def vote(
        self,
        code: str,
        user_id: int,
        target_id: int,
        *,
        economy: EconomyStore | None = None,
        now: float | None = None,
    ) -> tuple[SpyfallRoom, VoteOutcome | None]:
        """Ovoz beradi; hamma ovoz bergan bo'lsa darhol sanaydi."""
        with self._lock:
            room = self.get_room(code)
            room.cast_vote(user_id, target_id, now=now)
            outcome: VoteOutcome | None = None
            if room.all_voted:
                outcome = room.tally()
                self._award(room, economy)
            self._persist(room)
            return room, outcome

    def tally(
        self,
        code: str,
        user_id: int,
        *,
        economy: EconomyStore | None = None,
    ) -> tuple[SpyfallRoom, VoteOutcome]:
        """Ovozlarni muddatidan oldin sanaydi (faqat host)."""
        with self._lock:
            room = self.get_room(code)
            if int(user_id) != room.host_id:
                raise SpyfallRoomError("Ovozlarni faqat xona egasi sanaydi")
            outcome = room.tally()
            self._award(room, economy)
            self._persist(room)
            return room, outcome

    def buy_hint(
        self,
        code: str,
        user_id: int,
        *,
        economy: EconomyStore | None = None,
    ) -> tuple[SpyfallRoom, tuple[str, ...], int]:
        """«Josus radari» boosteri: 20 tangaga 3 ta noto'g'ri joyni o'chiradi."""
        store = economy or get_economy()
        with self._lock:
            room = self.get_room(code)
            player = room.get_player(user_id)
            if player.hint_exclusions:
                coins = store.get_user(player.user_id).coins
                return room, tuple(player.hint_exclusions), coins
            if store.get_user(player.user_id).coins < HINT_PRICE:
                raise InsufficientCoinsError(
                    f"Radar uchun {HINT_PRICE} tanga kerak"
                )
            store.spend_coins(player.user_id, HINT_PRICE)
            try:
                excluded = room.add_hint(player.user_id, rng=self._rng)
            except Exception:
                store.add_coins(player.user_id, HINT_PRICE)
                raise
            self._persist(room)
            coins = store.get_user(player.user_id).coins
            return room, excluded, coins

    def active_room_for_chat(self, chat_id: int) -> SpyfallRoom | None:
        """Guruh uchun tugamagan xonani topadi."""
        with self._lock:
            for room in self._rooms.values():
                if room.chat_id == int(chat_id) and room.phase is not Phase.FINISHED:
                    return room
        return None

    # ------------------------------------------------------------------ mukofot
    @staticmethod
    def _award(room: SpyfallRoom, economy: EconomyStore | None) -> None:
        """G'oliblarga tanga beradi (xona uchun faqat bir marta)."""
        if room.winner is None or room.rewards_granted:
            return
        store = economy or get_economy()
        amount = room.reward_per_winner
        for user_id in room.winner_ids:
            try:
                store.add_coins(user_id, amount)
            except Exception:  # tanga yozilmasa o'yin holati buzilmasin
                logger.exception("Josus mukofotini qo'shib bo'lmadi: %s", user_id)
        room.rewards_granted = True
        recorder = getattr(store, "record_game_history", None)
        if callable(recorder):
            try:
                recorder(
                    "spyfall",
                    room.code,
                    room.players.keys(),
                    room.winner_ids,
                    {user_id: amount for user_id in room.winner_ids},
                )
            except Exception:
                logger.exception("Josus tarixini yozib bo'lmadi: %s", room.code)

    # ------------------------------------------------------------------ saqlash
    def _persist(self, room: SpyfallRoom) -> None:
        store = get_store()
        if not store.enabled:
            return
        try:
            store.client.table(SPYFALL_TABLE).upsert(
                {
                    "code": room.code,
                    "state": room.to_state(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="code",
            ).execute()
        except Exception:
            logger.exception("Josus %s xonasini Supabase'ga saqlab bo'lmadi", room.code)

    def _restore(self, code: str) -> SpyfallRoom | None:
        store = get_store()
        if not store.enabled:
            return None
        try:
            rows = (
                store.client.table(SPYFALL_TABLE)
                .select("state")
                .eq("code", code)
                .limit(1)
                .execute()
                .data
                or []
            )
            if not rows:
                return None
            state = rows[0].get("state") or {}
            return SpyfallRoom.from_state(state)
        except Exception:
            logger.exception("Josus %s xonasini Supabase'dan tiklab bo'lmadi", code)
            return None

    # ------------------------------------------------------------------ testlar
    def clear(self) -> None:
        """Barcha xonalarni xotiradan tozalaydi (testlar uchun)."""
        with self._lock:
            self._rooms.clear()


_default_manager: SpyfallManager | None = None
_default_manager_lock = threading.Lock()


def get_default_manager() -> SpyfallManager:
    """Jarayon bo'ylab umumiy menejerni qaytaradi."""
    global _default_manager
    if _default_manager is None:
        with _default_manager_lock:
            if _default_manager is None:
                _default_manager = SpyfallManager()
    return _default_manager


__all__ = [
    "MAX_PLAYERS",
    "SPYFALL_TABLE",
    "SpyfallManager",
    "SpyfallNotFoundError",
    "SpyfallRoomError",
    "get_default_manager",
]
