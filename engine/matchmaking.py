"""Global o'yin qidiruvi (matchmaking) uchun umumiy navbat.

Guruhda odam kam bo'lganda o'yinchilar shu navbatga qo'shiladi.  Minimal
o'yinchi soni yig'ilganda umumiy xona ochiladi va navbatdagi barcha
o'yinchilarga xona havolasi yuboriladi.

Modul ataylab o'yin menejerlariga bog'lanmagan: xona yaratish va
bildirishnoma yuborish funksiyalari tashqaridan (``api.server``) uzatiladi.
Shu tufayli navbatni testlarda bog'liqliklarsiz tekshirish mumkin.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

GAME_TYPES = ("bunker", "mafia", "spyfall")

GAME_TITLES = {
    "bunker": "Bunker",
    "mafia": "Mafiya",
    "spyfall": "Josus",
}

# Navbat yig'ilganda o'yin boshlanishi uchun minimal o'yinchi soni.
MIN_PLAYERS = {
    "bunker": 5,
    "mafia": 6,
    "spyfall": 4,
}

# Bitta navbatdan umumiy xonaga olinadigan maksimal o'yinchi soni.
MAX_PLAYERS = {
    "bunker": 8,
    "mafia": 10,
    "spyfall": 8,
}

# Navbatda uzoq kutib qolgan o'yinchini chiqarib yuborish muddati.
QUEUE_TTL_SECONDS = 30 * 60

# Topilgan moslik haqidagi ma'lumot qancha vaqt saqlanadi (polling uchun).
RECENT_MATCH_TTL_SECONDS = 15 * 60

RoomFactory = Callable[[str, list[dict[str, Any]]], dict[str, Any] | None]
Notifier = Callable[[list[dict[str, Any]], dict[str, Any]], None]


class MatchmakingError(Exception):
    """Navbat bilan bog'liq xatolik (noma'lum o'yin turi va h.k.)."""


def normalize_game_type(game_type: str) -> str:
    """O'yin turini tekshirib, kichik harflarga keltiradi."""
    value = str(game_type or "").strip().lower()
    if value in ("spy", "spyfall", "josus"):
        return "spyfall"
    if value in ("mafia", "mafiya"):
        return "mafia"
    if value in ("bunker", "bunkier"):
        return "bunker"
    if value not in MIN_PLAYERS:
        raise MatchmakingError(f"Noma'lum o'yin turi: {game_type!r}")
    return value


class Matchmaker:
    """Har bir o'yin turi uchun xotiradagi umumiy navbat."""

    def __init__(
        self,
        *,
        min_players: dict[str, int] | None = None,
        max_players: dict[str, int] | None = None,
        ttl_seconds: int = QUEUE_TTL_SECONDS,
    ) -> None:
        self._min = dict(min_players or MIN_PLAYERS)
        self._max = dict(max_players or MAX_PLAYERS)
        self._ttl = max(60, int(ttl_seconds))
        self._queues: dict[str, list[dict[str, Any]]] = {
            game: [] for game in self._min
        }
        self._lock = threading.RLock()
        self._room_factory: RoomFactory | None = None
        self._notifier: Notifier | None = None
        self._matches = 0
        self._matches_by_game: dict[str, int] = {game: 0 for game in self._min}
        # Yaqinda topilgan moslik: navbatdagi qolgan o'yinchilar holat
        # so'rovida xona havolasini olishi uchun.
        self._recent: dict[int, tuple[float, dict[str, Any]]] = {}
        self._recent_ttl = RECENT_MATCH_TTL_SECONDS

    # ------------------------------------------------------------------
    # Bog'liqliklar
    # ------------------------------------------------------------------
    def set_room_factory(self, factory: RoomFactory | None) -> None:
        """Navbat to'lganda xona ochadigan funksiyani o'rnatadi."""
        self._room_factory = factory

    def set_notifier(self, notifier: Notifier | None) -> None:
        """O'yinchilarga xabar yuboradigan funksiyani o'rnatadi."""
        self._notifier = notifier

    # ------------------------------------------------------------------
    # Navbat holati
    # ------------------------------------------------------------------
    def _public_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Navbat yozuvini API uchun xavfsiz ko'rinishga keltiradi."""
        return {
            "user_id": int(entry.get("user_id") or 0),
            "name": str(entry.get("name") or ""),
        }

    def _status_locked(self, game_type: str) -> dict[str, Any]:
        queue = self._queues.setdefault(game_type, [])
        minimum = int(self._min.get(game_type, 1))
        count = len(queue)
        return {
            "game_type": game_type,
            "title": GAME_TITLES.get(game_type, game_type),
            "count": count,
            "min": minimum,
            "need": max(0, minimum - count),
            "players": [self._public_entry(entry) for entry in queue],
        }

    def status(self, game_type: str | None = None) -> dict[str, Any]:
        """Bitta yoki barcha navbatlarning holati."""
        with self._lock:
            if game_type is not None:
                return self._status_locked(normalize_game_type(game_type))
            return {
                "queues": [
                    self._status_locked(game) for game in self._queues
                ]
            }

    def position(self, user_id: int, game_type: str) -> int:
        """O'yinchining navbatdagi o'rni (0 — navbatda emas)."""
        with self._lock:
            queue = self._queues.get(normalize_game_type(game_type), [])
            for index, entry in enumerate(queue, start=1):
                if int(entry.get("user_id") or 0) == int(user_id):
                    return index
        return 0

    # ------------------------------------------------------------------
    # Navbatga kirish / chiqish
    # ------------------------------------------------------------------
    def _prune_locked(self, game_type: str) -> None:
        """Muddati o'tgan kutish yozuvlarini olib tashlaydi."""
        now = time.time()
        queue = self._queues.get(game_type) or []
        alive = [
            entry
            for entry in queue
            if now - float(entry.get("joined_at") or now) <= self._ttl
        ]
        if len(alive) != len(queue):
            self._queues[game_type] = alive

    def join(
        self,
        user_id: int,
        game_type: str,
        name: str = "",
        username: str = "",
    ) -> dict[str, Any]:
        """O'yinchini navbatga qo'shadi va kerak bo'lsa xona ochadi."""
        kind = normalize_game_type(game_type)
        uid = int(user_id)
        if uid <= 0:
            raise MatchmakingError("user_id noto'g'ri")

        with self._lock:
            self._prune_locked(kind)
            queue = self._queues.setdefault(kind, [])
            if any(int(item.get("user_id") or 0) == uid for item in queue):
                return self._status_locked(kind) | {"queued": True, "match": None}
            queue.append(
                {
                    "user_id": uid,
                    "name": (name or username or f"ID {uid}").strip(),
                    "username": username or "",
                    "joined_at": time.time(),
                }
            )
            status = self._status_locked(kind)
            minimum = int(self._min.get(kind, 1))
            if len(queue) < minimum:
                return status | {"queued": True, "match": None}
            # Navbat to'ldi: bitta umumiy xona uchun o'yinchilarni olamiz.
            take = min(len(queue), int(self._max.get(kind, len(queue))))
            players = queue[:take]
            del queue[:take]
            status = self._status_locked(kind)

        match = self._open_room(kind, players)
        if match is None:
            # Xona ochilmadi — o'yinchilarni navbatga qaytaramiz.
            with self._lock:
                restored = self._queues.setdefault(kind, [])
                known = {int(item.get("user_id") or 0) for item in restored}
                restored[:0] = [
                    entry
                    for entry in players
                    if int(entry.get("user_id") or 0) not in known
                ]
                status = self._status_locked(kind)
            return status | {"queued": True, "match": None}

        with self._lock:
            now = time.time()
            for entry in players:
                self._recent[int(entry.get("user_id") or 0)] = (now, match)
        self._notify(players, match)
        return status | {"queued": True, "match": match}

    def recent_match(
        self, user_id: int, game_type: str | None = None
    ) -> dict[str, Any] | None:
        """O'yinchi uchun yaqinda topilgan moslikni qaytaradi.

        Navbat to'lganini faqat oxirgi qo'shilgan o'yinchi bilib qolmasligi
        uchun qolgan ishtirokchilar ham holat so'rovida xonani oladi.
        """
        uid = int(user_id)
        kind = normalize_game_type(game_type) if game_type else None
        with self._lock:
            now = time.time()
            for key, (stamp, _) in list(self._recent.items()):
                if now - stamp > self._recent_ttl:
                    self._recent.pop(key, None)
            found = self._recent.get(uid)
            if found is None:
                return None
            match = found[1]
            if kind is not None and match.get("game_type") != kind:
                return None
            return dict(match)

    def leave(self, user_id: int, game_type: str | None = None) -> dict[str, Any]:
        """O'yinchini navbatdan chiqaradi."""
        uid = int(user_id)
        with self._lock:
            kinds = (
                [normalize_game_type(game_type)]
                if game_type is not None
                else list(self._queues)
            )
            removed = 0
            for kind in kinds:
                queue = self._queues.get(kind) or []
                kept = [
                    entry
                    for entry in queue
                    if int(entry.get("user_id") or 0) != uid
                ]
                removed += len(queue) - len(kept)
                self._queues[kind] = kept
            if game_type is not None:
                return self._status_locked(normalize_game_type(game_type)) | {
                    "left": removed > 0
                }
            return {
                "queues": [self._status_locked(kind) for kind in self._queues],
                "left": removed > 0,
            }

    # ------------------------------------------------------------------
    # Xona ochish
    # ------------------------------------------------------------------
    def _open_room(
        self, game_type: str, players: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        factory = self._room_factory
        if factory is None:
            logger.warning(
                "Navbat to'ldi, lekin xona fabrikasi o'rnatilmagan: %s", game_type
            )
            return None
        try:
            match = factory(game_type, players)
        except Exception:  # xona ochilmasa navbat saqlanib qoladi
            logger.exception(
                "Navbatdan xona ochib bo'lmadi: %s (%s o'yinchi)",
                game_type,
                len(players),
            )
            return None
        if not match:
            return None
        with self._lock:
            self._matches += 1
            self._matches_by_game[game_type] = (
                self._matches_by_game.get(game_type, 0) + 1
            )
        return match

    def _notify(self, players: list[dict[str, Any]], match: dict[str, Any]) -> None:
        notifier = self._notifier
        if notifier is None:
            return
        try:
            notifier(players, match)
        except Exception:  # bildirishnoma xatosi navbatni buzmaydi
            logger.exception("Navbat bildirishnomasini yuborib bo'lmadi")

    # ------------------------------------------------------------------
    # Xizmat
    # ------------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        """Monitoring uchun navbat statistikasi."""
        with self._lock:
            return {
                "queued": {
                    game: len(self._queues.get(game) or [])
                    for game in self._queues
                },
                "matches": int(self._matches),
                "matches_by_game": dict(self._matches_by_game),
            }

    def reset(self) -> None:
        """Navbatni tozalaydi (testlar va qayta ishga tushirish uchun)."""
        with self._lock:
            for kind in self._queues:
                self._queues[kind] = []
            self._recent.clear()


_matchmaker: Matchmaker | None = None
_matchmaker_lock = threading.Lock()


def get_matchmaker() -> Matchmaker:
    """Jarayon uchun yagona navbat menejerini qaytaradi."""
    global _matchmaker
    with _matchmaker_lock:
        if _matchmaker is None:
            _matchmaker = Matchmaker()
        return _matchmaker
