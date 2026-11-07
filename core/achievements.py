"""Doimiy nishonlar (achievements): o'yinchi statistikasidan ochiladi.

Nishonlar yangi o'yin rejimlarini sinash va profilni boyitish uchun.
Har bir nishon bitta statistik ko'rsatkichga bog'langan; ochilgan nishonlar
``user_achievements`` jadvalida saqlanadi. Supabase sozlanmagan bo'lsa
holat jarayon xotirasida qoladi.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.db import safe_upsert

logger = logging.getLogger(__name__)

TABLE = "user_achievements"

_MEMORY: dict[int, set[str]] = {}
_LOCK = threading.Lock()


@dataclass(frozen=True)
class Achievement:
    """Bitta nishon ta'rifi."""

    key: str
    title: str
    emoji: str
    description: str
    metric: str
    target: int


ACHIEVEMENTS: tuple[Achievement, ...] = (
    Achievement(
        key="first_game",
        title="Birinchi qadam",
        emoji="🎲",
        description="Birinchi o'yinda qatnashing",
        metric="games_played",
        target=1,
    ),
    Achievement(
        key="games_10",
        title="Doimiy o'yinchi",
        emoji="🕹",
        description="10 ta o'yinda qatnashing",
        metric="games_played",
        target=10,
    ),
    Achievement(
        key="games_50",
        title="Stol ustasi",
        emoji="🏅",
        description="50 ta o'yinda qatnashing",
        metric="games_played",
        target=50,
    ),
    Achievement(
        key="first_win",
        title="Birinchi g'alaba",
        emoji="🏆",
        description="Bitta o'yinda g'olib bo'ling",
        metric="wins",
        target=1,
    ),
    Achievement(
        key="wins_10",
        title="G'oliblar safida",
        emoji="👑",
        description="10 marta g'olib bo'ling",
        metric="wins",
        target=10,
    ),
    Achievement(
        key="bunker_win",
        title="Bunker qahramoni",
        emoji="🛡",
        description="Bunkerda bir marta g'olib bo'ling",
        metric="bunker_wins",
        target=1,
    ),
    Achievement(
        key="mafia_win",
        title="Qorong'i kuch",
        emoji="🎩",
        description="Mafiyada bir marta g'olib bo'ling",
        metric="mafia_wins",
        target=1,
    ),
    Achievement(
        key="friend_1",
        title="Do'stlar davrasi",
        emoji="🤝",
        description="Bir do'stni taklif qiling",
        metric="referral_count",
        target=1,
    ),
    Achievement(
        key="friends_5",
        title="Elchi",
        emoji="📣",
        description="5 do'stni taklif qiling",
        metric="referral_count",
        target=5,
    ),
    Achievement(
        key="streak_3",
        title="Faol o'yinchi",
        emoji="🔥",
        description="3 kun ketma-ket bonus oling",
        metric="bonus_streak",
        target=3,
    ),
    Achievement(
        key="streak_7",
        title="Seriya ustasi",
        emoji="📅",
        description="7 kun ketma-ket bonus oling",
        metric="bonus_streak",
        target=7,
    ),
)

BY_KEY: dict[str, Achievement] = {item.key: item for item in ACHIEVEMENTS}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(store: Any, user_id: int) -> set[str]:
    """Ochilgan nishonlar kalitlari (Supabase yoki xotira)."""
    uid = int(user_id)
    with _LOCK:
        unlocked = set(_MEMORY.get(uid, set()))
    if not getattr(store, "enabled", False):
        return unlocked
    try:
        rows = (
            store.client.table(TABLE)
            .select("achievement_key")
            .eq("user_id", uid)
            .execute()
            .data
            or []
        )
    except Exception:
        logger.exception("Nishonlarni o'qib bo'lmadi: %s", uid)
        return unlocked
    return unlocked | {
        str(row.get("achievement_key"))
        for row in rows
        if row.get("achievement_key")
    }


def _save(store: Any, user_id: int, keys: set[str]) -> set[str]:
    """Yangi ochilgan nishonlarni saqlaydi."""
    uid = int(user_id)
    with _LOCK:
        current = _MEMORY.setdefault(uid, set())
        new_keys = set(keys) - current
        current.update(keys)
    if new_keys and getattr(store, "enabled", False):
        rows = [
            {
                "user_id": uid,
                "achievement_key": key,
                "unlocked_at": _now(),
            }
            for key in sorted(new_keys)
        ]
        try:
            safe_upsert(
                store.client,
                TABLE,
                rows,
                on_conflict="user_id,achievement_key",
            )
        except Exception:
            logger.exception("Nishonlarni saqlab bo'lmadi: %s", uid)
    return current


def _progress(account: Any, metric: str) -> int:
    value = int(getattr(account, metric, 0) or 0)
    return max(0, value)


def achievements_payload(store: Any, user_id: int) -> list[dict[str, Any]]:
    """Barcha nishonlar holati; yangi ochilganlarni avtomatik saqlaydi."""
    account = store.ensure_user(int(user_id))
    unlocked = _load(store, account.user_id)
    fresh = {
        item.key
        for item in ACHIEVEMENTS
        if _progress(account, item.metric) >= item.target
        and item.key not in unlocked
    }
    if fresh:
        unlocked = _save(store, account.user_id, unlocked | fresh)
    rows: list[dict[str, Any]] = []
    for item in ACHIEVEMENTS:
        progress = min(_progress(account, item.metric), item.target)
        rows.append(
            {
                "key": item.key,
                "title": item.title,
                "emoji": item.emoji,
                "description": item.description,
                "metric": item.metric,
                "target": item.target,
                "progress": progress,
                "percent": min(100, int(round(progress / item.target * 100))),
                "unlocked": item.key in unlocked,
            }
        )
    return rows


def reset_memory() -> None:
    """Testlar uchun xotiradagi nishonlarni tozalaydi."""
    with _LOCK:
        _MEMORY.clear()
