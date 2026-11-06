"""Global o'yin qidiruvi (matchmaking) uchun umumiy navbat.

Guruhda odam kam bo'lganda o'yinchilar shu navbatga qo'shiladi.  Minimal
o'yinchi soni yig'ilganda umumiy xona ochiladi va navbatdagi barcha
o'yinchilarga xona havolasi yuboriladi.

Navbat xotirada tez ishlaydi, lekin imkon bo'lsa Supabase'dagi
``matchmaking_queue`` jadvalida ham saqlanadi: ``join_global_queue``,
``leave_global_queue`` va ``check_and_create_matches`` shu qatlamni
boshqaradi. Shu tufayli server qayta ishga tushganda navbat yo'qolmaydi.

Modul ataylab o'yin menejerlariga bog'lanmagan: xona yaratish va
bildirishnoma yuborish funksiyalari tashqaridan (``api.server``) uzatiladi.
Shu tufayli navbatni testlarda bog'liqliklarsiz tekshirish mumkin.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

logger = logging.getLogger(__name__)

GAME_TYPES = ("bunker", "mafia", "spyfall", "alias", "bomb")

GAME_TITLES = {
    "bunker": "Bunker",
    "mafia": "Mafiya",
    "spyfall": "Josus",
    "alias": "Alias",
    "bomb": "Portlovçi Bomba",
}

# Navbat yig'ilganda o'yin boshlanishi uchun minimal o'yinchi soni.
MIN_PLAYERS = {
    "bunker": 5,
    "mafia": 6,
    "spyfall": 3,
    "alias": 3,
    "bomb": 2,
}

# Bitta navbatdan umumiy xonaga olinadigan maksimal o'yinchi soni.
MAX_PLAYERS = {
    "bunker": 16,
    "mafia": 20,
    "spyfall": 12,
    "alias": 20,
    "bomb": 8,
}

# Supabase'dagi global navbat jadvali.
MATCHMAKING_TABLE = "matchmaking_queue"

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
    if value in ("alias", "krokodil", "alies"):
        return "alias"
    if value in ("bomb", "bomba", "portlovchi", "portlovçi"):
        return "bomb"
    if value not in MIN_PLAYERS:
        raise MatchmakingError(f"Noma'lum o'yin turi: {game_type!r}")
    return value


class QueueStore:
    """Supabase'dagi ``matchmaking_queue`` jadvali bilan ishlash.

    Baza o'chirilgan yoki jadval bo'lmasa barcha metodlar jimgina ishlamaydi:
    navbat xotirada davom etadi, faqat qayta ishga tushirishda yo'qoladi.
    """

    def __init__(self, table: str = MATCHMAKING_TABLE) -> None:
        self._table = table
        self._client: Any = None
        self._resolved = False

    @property
    def client(self) -> Any:
        if not self._resolved:
            self._resolved = True
            try:
                from core.db import get_store

                store = get_store()
                self._client = store.client if store.enabled else None
            except Exception:
                logger.exception("Navbat uchun Supabase mijozini olib bo'lmadi")
                self._client = None
        return self._client

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def load(self) -> list[dict[str, Any]]:
        """Jadvaldagi navbat yozuvlarini o'qiydi."""
        client = self.client
        if client is None:
            return []
        try:
            rows = (
                client.table(self._table)
                .select("user_id,game_type,name,username,created_at")
                .execute()
                .data
                or []
            )
        except Exception:
            logger.exception("matchmaking_queue jadvalini o'qib bo'lmadi")
            return []
        entries: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                kind = normalize_game_type(str(row.get("game_type") or ""))
            except MatchmakingError:
                continue
            entries.append(
                {
                    "user_id": int(row.get("user_id") or 0),
                    "game_type": kind,
                    "name": str(row.get("name") or ""),
                    "username": str(row.get("username") or ""),
                    "joined_at": _parse_stamp(row.get("created_at")) or time.time(),
                }
            )
        return entries

    def add(self, entry: dict[str, Any]) -> None:
        """O'yinchini navbatga yozadi (takroriy yozuv yangilanadi)."""
        client = self.client
        if client is None:
            return
        try:
            client.table(self._table).upsert(
                {
                    "user_id": int(entry.get("user_id") or 0),
                    "game_type": str(entry.get("game_type") or ""),
                    "name": str(entry.get("name") or ""),
                    "username": str(entry.get("username") or ""),
                },
                on_conflict="user_id",
            ).execute()
        except Exception:
            logger.exception(
                "Navbatga yozib bo'lmadi: %s", entry.get("user_id")
            )

    def remove(self, user_id: int, game_type: str | None = None) -> None:
        """O'yinchini jadvaldan o'chiradi."""
        client = self.client
        if client is None:
            return
        try:
            query = client.table(self._table).delete().eq("user_id", int(user_id))
            if game_type is not None:
                query = query.eq("game_type", game_type)
            query.execute()
        except Exception:
            logger.exception("Navbatdan o'chirib bo'lmadi: %s", user_id)

    def remove_users(self, user_ids: Iterable[int]) -> None:
        """Bir nechta o'yinchini jadvaldan o'chiradi."""
        client = self.client
        ids = [int(uid) for uid in user_ids if int(uid) > 0]
        if client is None or not ids:
            return
        try:
            client.table(self._table).delete().in_("user_id", ids).execute()
        except Exception:
            logger.exception("Navbat yozuvlarini o'chirib bo'lmadi: %s", ids)

def _parse_stamp(value: Any) -> float | None:
    """ISO vaqt yozuvini ``time.time()`` shkalasiga o'giradi."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        from datetime import datetime

        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return moment.timestamp()
    except Exception:
        return None


class Matchmaker:
    """Har bir o'yin turi uchun xotiradagi umumiy navbat."""

    def __init__(
        self,
        *,
        min_players: dict[str, int] | None = None,
        max_players: dict[str, int] | None = None,
        ttl_seconds: int = QUEUE_TTL_SECONDS,
        store: QueueStore | None = None,
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
        self._store = store

    # ------------------------------------------------------------------
    # Bog'liqliklar
    # ------------------------------------------------------------------
    def set_room_factory(self, factory: RoomFactory | None) -> None:
        """Navbat to'lganda xona ochadigan funksiyani o'rnatadi."""
        self._room_factory = factory

    def set_notifier(self, notifier: Notifier | None) -> None:
        """O'yinchilarga xabar yuboradigan funksiyani o'rnatadi."""
        self._notifier = notifier

    def set_store(self, store: QueueStore | None) -> None:
        """Navbatni saqlaydigan Supabase omborini o'rnatadi."""
        self._store = store

    @property
    def store(self) -> QueueStore | None:
        return self._store

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
            entry = {
                "user_id": uid,
                "name": (name or username or f"ID {uid}").strip(),
                "username": username or "",
                "joined_at": time.time(),
            }
            queue.append(entry)

        # Navbat Supabase'da ham saqlanadi (imkon bo'lsa).
        store = self._store
        if store is not None:
            store.add({**entry, "game_type": kind})

        match = self._try_match(kind)
        with self._lock:
            status = self._status_locked(kind)
        return status | {"queued": True, "match": match}

    # ------------------------------------------------------------------
    # Mosliklarni tekshirish
    # ------------------------------------------------------------------
    def _try_match(self, game_type: str) -> dict[str, Any] | None:
        """Navbat yetarli bo'lsa xona ochadi, aks holda ``None``."""
        with self._lock:
            self._prune_locked(game_type)
            queue = self._queues.setdefault(game_type, [])
            minimum = int(self._min.get(game_type, 1))
            if len(queue) < minimum:
                return None
            take = min(len(queue), int(self._max.get(game_type, len(queue))))
            players = queue[:take]
            del queue[:take]

        match = self._open_room(game_type, players)
        if match is None:
            # Xona ochilmadi — o'yinchilarni navbatga qaytaramiz.
            with self._lock:
                restored = self._queues.setdefault(game_type, [])
                known = {int(item.get("user_id") or 0) for item in restored}
                restored[:0] = [
                    entry
                    for entry in players
                    if int(entry.get("user_id") or 0) not in known
                ]
            return None

        with self._lock:
            now = time.time()
            for entry in players:
                self._recent[int(entry.get("user_id") or 0)] = (now, match)
        store = self._store
        if store is not None:
            store.remove_users([int(e.get("user_id") or 0) for e in players])
        self._notify(players, match)
        return match

    def check_matches(self) -> list[dict[str, Any]]:
        """Barcha navbatlarni tekshirib, yetilganlarini xonaga aylantiradi."""
        with self._lock:
            kinds = list(self._queues)
        matches: list[dict[str, Any]] = []
        for kind in kinds:
            match = self._try_match(kind)
            if match is not None:
                matches.append(match)
        return matches

    def sync_from_store(self) -> int:
        """Supabase'dagi navbat yozuvlarini xotiraga qo'shadi."""
        store = self._store
        if store is None:
            return 0
        rows = store.load()
        added = 0
        stale: list[int] = []
        with self._lock:
            known = {
                int(entry.get("user_id") or 0)
                for queue in self._queues.values()
                for entry in queue
            }
            now = time.time()
            for row in rows:
                uid = int(row.get("user_id") or 0)
                kind = str(row.get("game_type") or "")
                if uid <= 0 or kind not in self._queues or uid in known:
                    continue
                joined = float(row.get("joined_at") or now)
                if now - joined > self._ttl:
                    stale.append(uid)
                    continue
                self._queues[kind].append(
                    {
                        "user_id": uid,
                        "name": str(row.get("name") or f"ID {uid}"),
                        "username": str(row.get("username") or ""),
                        "joined_at": joined,
                    }
                )
                known.add(uid)
                added += 1
        if stale:
            store.remove_users(stale)
        if added:
            logger.info("Navbatga bazadan %s ta o'yinchi qo'shildi", added)
        return added

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
        target = normalize_game_type(game_type) if game_type is not None else None
        store = self._store
        if store is not None:
            store.remove(uid, target)
        with self._lock:
            kinds = [target] if target is not None else list(self._queues)
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
_queue_store: QueueStore | None = None


def get_matchmaker() -> Matchmaker:
    """Jarayon uchun yagona navbat menejerini qaytaradi."""
    global _matchmaker
    with _matchmaker_lock:
        if _matchmaker is None:
            _matchmaker = Matchmaker()
        return _matchmaker


def get_queue_store() -> QueueStore:
    """Supabase navbat omborining yagona nusxasi."""
    global _queue_store
    with _matchmaker_lock:
        if _queue_store is None:
            _queue_store = QueueStore()
        return _queue_store


def attach_queue_store(store: QueueStore | None) -> None:
    """Testlar va server uchun navbat omborini almashtiradi."""
    get_matchmaker().set_store(store)


def join_global_queue(
    user_id: int,
    game_type: str,
    name: str = "",
    username: str = "",
) -> dict[str, Any]:
    """O'yinchini global navbatga qo'shadi va holatni qaytaradi."""
    manager = get_matchmaker()
    if manager.store is None:
        manager.set_store(get_queue_store())
    return manager.join(user_id, game_type, name=name, username=username)


def leave_global_queue(
    user_id: int, game_type: str | None = None
) -> dict[str, Any]:
    """O'yinchini global navbatdan chiqaradi."""
    manager = get_matchmaker()
    if manager.store is None:
        manager.set_store(get_queue_store())
    return manager.leave(user_id, game_type)


def check_and_create_matches() -> list[dict[str, Any]]:
    """Bazadagi navbatni xotira bilan sinxronlab, yetilgan mosliklarni ochadi."""
    manager = get_matchmaker()
    if manager.store is None:
        manager.set_store(get_queue_store())
    manager.sync_from_store()
    return manager.check_matches()
