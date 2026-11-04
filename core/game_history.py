"""Yagona o'yin tarixi: Supabase'da tugagan partiyalarni qayd etish."""
from __future__ import annotations

import logging
from typing import Any, Iterable

from core.db import get_store

logger = logging.getLogger(__name__)
TABLE = "games_history"


def record_game_history(
    game_type: str,
    room_code: str,
    participant_ids: Iterable[int],
    winner_ids: Iterable[int],
    *,
    details: dict[str, Any] | None = None,
) -> bool:
    """O'yin natijasini xona kaliti bo'yicha takrorlanmaydigan tarzda saqlaydi."""
    store = get_store()
    if not store.enabled:
        logger.warning("O'yin tarixi saqlanmadi: Supabase sozlanmagan")
        return False
    participants = sorted({int(value) for value in participant_ids})
    winners = sorted({int(value) for value in winner_ids})
    if not game_type or not room_code or not participants:
        raise ValueError("O'yin turi, xona kodi va qatnashuvchilar talab qilinadi")
    try:
        store.client.table(TABLE).upsert(
            {
                "game_type": str(game_type).lower(),
                "room_code": str(room_code).upper(),
                "participant_ids": participants,
                "winner_ids": winners,
                "details": details or {},
            },
            on_conflict="game_type,room_code",
        ).execute()
        return True
    except Exception:
        logger.exception(
            "O'yin tarixini saqlashda xatolik: %s/%s", game_type, room_code
        )
        return False


def recent_user_games(user_id: int, limit: int = 5) -> list[dict[str, Any]]:
    """Foydalanuvchi qatnashgan so'nggi o'yinlarni qaytaradi."""
    store = get_store()
    if not store.enabled:
        return []
    try:
        return (
            store.client.table(TABLE)
            .select("game_type,room_code,played_at,participant_ids,winner_ids")
            .contains("participant_ids", [int(user_id)])
            .order("played_at", desc=True)
            .limit(max(1, min(int(limit), 20)))
            .execute()
            .data
            or []
        )
    except Exception:
        logger.exception("O'yin tarixini o'qib bo'lmadi: user=%s", user_id)
        return []
