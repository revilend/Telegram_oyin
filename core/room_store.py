"""O'yin xonalarini Supabase JSONB jadvallarida saqlash.

Har bir o'yin turi o'z jadvalida ``code``, ``state`` va ``updated_at``
ustunlariga ega.  Holat JSONB ko'rinishida yoziladi, shuning uchun server
qayta ishga tushganda xona kod bo'yicha tiklanadi.  Supabase sozlanmagan
bo'lsa barcha funksiyalar jimgina hech narsa qilmaydi va o'yin avvalgidek
faqat xotirada ishlaydi.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.db import get_store, safe_upsert
from models.game import GameRoom

logger = logging.getLogger(__name__)

BUNKER_ROOMS_TABLE = "bunker_rooms"
MAFIA_ROOMS_TABLE = "mafia_rooms"
BOMB_ROOMS_TABLE = "bomb_rooms"
ALIAS_ROOMS_TABLE = "alias_rooms"
SPYFALL_ROOMS_TABLE = "spyfall_rooms"

ROOM_TABLES = (
    BUNKER_ROOMS_TABLE,
    MAFIA_ROOMS_TABLE,
    BOMB_ROOMS_TABLE,
    ALIAS_ROOMS_TABLE,
    SPYFALL_ROOMS_TABLE,
)

LOAD_LIMIT = 500


def _normalize_code(code: str) -> str:
    return (code or "").strip().upper()


def save_state(table: str, code: str, state: dict[str, Any]) -> None:
    """Xona holatini JSONB sifatida yozadi yoki mavjudini yangilaydi."""
    store = get_store()
    if not store.enabled:
        return
    normalized = _normalize_code(code)
    if not normalized:
        return
    try:
        safe_upsert(
            store.client,
            table,
            {
                "code": normalized,
                "state": state,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="code",
        )
    except Exception:
        logger.exception(
            "Supabase %s jadvaliga %s xonasini saqlab bo'lmadi",
            table,
            normalized,
        )


def load_state(table: str, code: str) -> dict[str, Any] | None:
    """Kod bo'yicha xona holatini o'qiydi; topilmasa ``None``."""
    store = get_store()
    if not store.enabled:
        return None
    normalized = _normalize_code(code)
    if not normalized:
        return None
    try:
        rows = (
            store.client.table(table)
            .select("state")
            .eq("code", normalized)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        logger.exception(
            "Supabase %s jadvalidan %s xonasini o'qib bo'lmadi",
            table,
            normalized,
        )
        return None
    if not rows:
        return None
    state = rows[0].get("state") if isinstance(rows[0], dict) else None
    return state if isinstance(state, dict) else None


def load_states(table: str, limit: int = LOAD_LIMIT) -> list[dict[str, Any]]:
    """Jadvaldagi so'nggi xona holatlarini qaytaradi."""
    store = get_store()
    if not store.enabled:
        return []
    try:
        rows = (
            store.client.table(table)
            .select("state")
            .limit(max(1, int(limit)))
            .execute()
            .data
            or []
        )
    except Exception:
        logger.exception("Supabase %s jadvalini o'qib bo'lmadi", table)
        return []
    states: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        state = row.get("state")
        if isinstance(state, dict):
            states.append(state)
    return states


def delete_state(table: str, code: str) -> None:
    """Xona yozuvini bazadan o'chiradi (tugagan/tozalangan xonalar uchun)."""
    store = get_store()
    if not store.enabled:
        return
    normalized = _normalize_code(code)
    if not normalized:
        return
    try:
        store.client.table(table).delete().eq("code", normalized).execute()
    except Exception:
        logger.exception(
            "Supabase %s jadvalidan %s xonasini o'chirib bo'lmadi",
            table,
            normalized,
        )


# ----------------------------------------------------------------------
# Bunker: Pydantic modelini JSONB holatga aylantirish
# ----------------------------------------------------------------------
def save_bunker(room: GameRoom, votes: dict[int, int]) -> None:
    """Bunker xonasi va ovozlarini bitta JSONB holatda saqlaydi."""
    save_state(
        BUNKER_ROOMS_TABLE,
        room.code,
        {
            "room": room.model_dump(mode="json"),
            "votes": {str(int(user_id)): int(target) for user_id, target in votes.items()},
        },
    )


def load_bunker(code: str) -> tuple[GameRoom, dict[int, int]] | None:
    """Bunker xonasini JSONB holatdan tiklaydi."""
    state = load_state(BUNKER_ROOMS_TABLE, code)
    if not state:
        return None
    raw_room = state.get("room") if isinstance(state.get("room"), dict) else state
    try:
        room = GameRoom.model_validate(raw_room)
        raw_votes = state.get("votes") or {}
        votes = {
            int(voter): int(target)
            for voter, target in raw_votes.items()
            if str(voter).lstrip("-").isdigit() and str(target).lstrip("-").isdigit()
        }
    except Exception:
        logger.exception(
            "Bunker %s xonasini JSONB holatdan tiklab bo'lmadi", code
        )
        return None
    return room, votes


__all__ = [
    "ALIAS_ROOMS_TABLE",
    "BOMB_ROOMS_TABLE",
    "BUNKER_ROOMS_TABLE",
    "LOAD_LIMIT",
    "MAFIA_ROOMS_TABLE",
    "ROOM_TABLES",
    "SPYFALL_ROOMS_TABLE",
    "delete_state",
    "load_bunker",
    "load_state",
    "load_states",
    "save_bunker",
    "save_state",
]
