"""Supabase'da «Bunker» xonalari holatini saqlash va qayta yuklash.

Ma'lumotlar ikki jadvalda turadi: ``rooms`` (xona holati, ovozlar) va
``room_players`` (o'yinchilar va ularning kartalari). Jadval SQL'i
``core/schema.sql`` faylida.

``SUPABASE_URL`` yoki ``SUPABASE_KEY`` berilmagan bo'lsa, saqlash o'chiriladi
va o'yin avvalgidek faqat xotirada ishlaydi.
"""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from models.game import GameRoom, Player, PlayerCard

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

ROOMS_TABLE = "rooms"
PLAYERS_TABLE = "room_players"
LOAD_TIMEOUT_SECONDS = 15.0


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


class SupabaseStore:
    """Xona holatini Supabase jadvallariga yozadi va ulardan o'qiydi.

    Barcha tarmoq amallari bitta fon oqimida ketma-ket bajariladi — shu bilan
    asosiy event loop bloklanmaydi va yozishlar tartibi saqlanadi.
    """

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.url = (url if url is not None else _env("SUPABASE_URL")).strip()
        self.key = (key if key is not None else _env("SUPABASE_KEY")).strip()
        self._client = client
        self._client_lock = threading.Lock()
        self._closed = False
        self._executor: ThreadPoolExecutor | None = (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="supabase")
            if self.enabled
            else None
        )
        if not self.enabled:
            logger.info("Supabase sozlanmagan — xonalar faqat xotirada saqlanadi")

    @property
    def enabled(self) -> bool:
        return self._client is not None or bool(self.url and self.key)

    @property
    def client(self) -> Any:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    from supabase import create_client

                    self._client = create_client(self.url, self.key)
        return self._client

    # ------------------------------------------------------------------
    # Yozish
    # ------------------------------------------------------------------
    def persist(self, room: GameRoom, votes: dict[int, int]) -> None:
        """Holatning nusxasini fon oqimiga yuboradi (fire-and-forget)."""
        if not self.enabled or self._closed or self._executor is None:
            return
        snapshot = room.model_copy(deep=True)
        votes_snapshot = {int(voter): int(target) for voter, target in votes.items()}
        try:
            self._executor.submit(self._write, snapshot, votes_snapshot)
        except RuntimeError:  # executor yopilgan
            logger.debug("Supabase executor yopilgan, yozuv tashlab yuborildi")

    def _write(self, room: GameRoom, votes: dict[int, int]) -> None:
        try:
            self.save_room(room, votes)
        except Exception:  # baza xatosi o'yinni to'xtatmasligi kerak
            logger.exception("Supabase'ga %s xonasini saqlab bo'lmadi", room.code)

    def save_room(self, room: GameRoom, votes: dict[int, int] | None = None) -> None:
        """Xona va o'yinchilarni `upsert` qiladi."""
        votes = votes or {}
        updated_at = datetime.now(timezone.utc).isoformat()
        client = self.client

        client.table(ROOMS_TABLE).upsert(
            {
                "code": room.code,
                "room_id": room.room_id,
                "game_type": "bunker",
                "status": room.status.value,
                "host_id": room.host_id,
                "max_players": room.max_players,
                "bunker_capacity": room.bunker_capacity,
                "current_round": room.current_round,
                "catastrophe": room.catastrophe,
                "eliminated_players": room.eliminated_players,
                "votes": {str(voter): int(target) for voter, target in votes.items()},
                "updated_at": updated_at,
            },
            on_conflict="code",
        ).execute()

        player_rows = [
            {
                "room_code": room.code,
                "user_id": player.user_id,
                "username": player.username,
                "full_name": player.full_name,
                "is_alive": player.is_alive,
                "is_host": player.is_host,
                "cards": {
                    key: card.model_dump(mode="json")
                    for key, card in player.cards.items()
                },
                "votes_against": player.votes_against,
                "updated_at": updated_at,
            }
            for player in room.players.values()
        ]
        if player_rows:
            client.table(PLAYERS_TABLE).upsert(
                player_rows,
                on_conflict="room_code,user_id",
            ).execute()

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------
    def load_room(self, code: str) -> tuple[GameRoom, dict[int, int]] | None:
        """Xonani Supabase'dan yuklaydi; topilmasa yoki xato bo'lsa ``None``."""
        if not self.enabled or self._closed or self._executor is None:
            return None
        try:
            return self._executor.submit(self._load_sync, code).result(
                timeout=LOAD_TIMEOUT_SECONDS
            )
        except Exception:
            logger.exception("Supabase'dan %s xonasini yuklab bo'lmadi", code)
            return None

    def _load_sync(self, code: str) -> tuple[GameRoom, dict[int, int]] | None:
        client = self.client
        room_rows = (
            client.table(ROOMS_TABLE)
            .select("*")
            .eq("code", code)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not room_rows:
            return None
        row = room_rows[0]

        player_rows = (
            client.table(PLAYERS_TABLE)
            .select("*")
            .eq("room_code", code)
            .execute()
            .data
            or []
        )

        players: dict[int, Player] = {}
        for player_row in player_rows:
            raw_cards = player_row.get("cards") or {}
            cards = {
                key: PlayerCard.model_validate(card)
                for key, card in raw_cards.items()
            }
            player = Player(
                user_id=int(player_row["user_id"]),
                username=player_row.get("username") or "",
                full_name=player_row.get("full_name") or "",
                is_alive=bool(player_row.get("is_alive", True)),
                is_host=bool(player_row.get("is_host", False)),
                cards=cards,
                votes_against=int(player_row.get("votes_against") or 0),
            )
            players[player.user_id] = player

        room = GameRoom(
            room_id=row["room_id"],
            code=row["code"],
            host_id=int(row["host_id"]),
            status=row.get("status") or "LOBBY",
            max_players=int(row.get("max_players") or 12),
            bunker_capacity=int(row.get("bunker_capacity") or 5),
            current_round=int(row.get("current_round") or 0),
            catastrophe=row.get("catastrophe") or {},
            players=players,
            eliminated_players=[int(item) for item in row.get("eliminated_players") or []],
        )

        votes = {
            int(voter): int(target)
            for voter, target in (row.get("votes") or {}).items()
        }
        return room, votes

    def close(self) -> None:
        """Navbatdagi yozuvlarni tugatib, fon oqimini yopadi."""
        self._closed = True
        executor = self._executor
        self._executor = None
        if executor is not None:
            executor.shutdown(wait=True)


_store: SupabaseStore | None = None
_store_lock = threading.Lock()


def get_store() -> SupabaseStore:
    """Umumiy SupabaseStore nusxasini qaytaradi."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = SupabaseStore()
    return _store
