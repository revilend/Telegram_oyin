"""Reyting jadvali: barcha davrlar va joriy haftalik liga.

Mini App va bot bir xil raqamlarni ko'rsatishi uchun hisoblash shu modulda
bajariladi.  Haftalik liga dushanba kuni 00:00 da nolga tushadi.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from core.economy import EconomyStore, get_economy, player_rating

logger = logging.getLogger(__name__)

PERIOD_ALL = "all"
PERIOD_WEEK = "week"
PERIODS = (PERIOD_ALL, PERIOD_WEEK)

# Hafta dushanba (0) kunidan boshlanadi.
WEEK_RESET_WEEKDAY = 0

# Top-3 uchun nishonlar.  Emoji o'rniga nom qaytaramiz: Mini App uni
# vektor nishon sifatida chizadi.
MEDALS = {1: "gold", 2: "silver", 3: "bronze"}


def normalize_period(period: str | None) -> str:
    """Davr nomini tekshiradi."""
    value = str(period or PERIOD_ALL).strip().lower()
    if value in ("week", "weekly", "hafta", "haftalik"):
        return PERIOD_WEEK
    return PERIOD_ALL


def week_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Joriy haftaning boshlanishi va tugashini qaytaradi (dushanba 00:00)."""
    moment = now or datetime.now()
    start = (moment - timedelta(days=moment.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start, start + timedelta(days=7)


def medal_for(rank: int) -> str | None:
    """O'rin uchun nishon nomi (top-3 bo'lmasa ``None``)."""
    return MEDALS.get(int(rank or 0))


def display_name(account: Any) -> str:
    """Hisob yozuvidan ko'rinadigan ism."""
    full_name = str(getattr(account, "full_name", "") or "").strip()
    if full_name:
        return full_name
    username = str(getattr(account, "username", "") or "").strip()
    if username:
        return username
    return f"ID {getattr(account, 'user_id', 0)}"


FRAME_KEYS = {
    "frame_gold": "gold",
    "frame_neon": "neon",
    "frame_cyber": "cyber",
    "frame_fire": "fire",
    "frame_diamond": "diamond",
    "clan_emblem": "clan",
}


def _cosmetics(user_id: int) -> dict[str, str]:
    """Taqilgan ramka va unvon.

    Mini App ham qisqa kalitni (``gold``), ham aniq slugni (``frame_gold``)
    ishlatadi; shuning uchun ikkalasi ham qaytariladi.
    """
    empty = {
        "frame": "",
        "frame_slug": "",
        "title": "",
        "title_slug": "",
    }
    try:
        from core.shop import CATALOG_BY_SLUG, get_shop_store

        equipped = get_shop_store().equipped(int(user_id))
        frame_slug = str(equipped.get("frame") or "")
        frame = FRAME_KEYS.get(frame_slug, "")
        title_slug = str(equipped.get("title") or "")
        item = CATALOG_BY_SLUG.get(title_slug)
        return {
            "frame": frame,
            "frame_slug": frame_slug,
            "title": str(item.payload) if item is not None else "",
            "title_slug": title_slug,
        }
    except Exception:
        logger.exception("Bezaklarni o'qib bo'lmadi: %s", user_id)
        return empty


def _all_time(economy: EconomyStore, limit: int, viewer_id: int | None) -> dict[str, Any]:
    """Umumiy reyting: reyting va tangalar bo'yicha."""
    accounts = economy.top_users(limit=1000)
    rows: list[dict[str, Any]] = []
    for index, account in enumerate(accounts, start=1):
        rows.append(
            {
                "rank": index,
                "user_id": account.user_id,
                "name": display_name(account),
                "username": account.username,
                "rating": player_rating(account),
                "points": player_rating(account),
                "coins": account.coins,
                "wins": account.wins,
                "games": account.games_played,
                "medal": medal_for(index),
                "is_me": viewer_id is not None and account.user_id == int(viewer_id),
            }
        )

    me: dict[str, Any] | None = None
    if viewer_id is not None:
        uid = int(viewer_id)
        me = next((row for row in rows if row["user_id"] == uid), None)
        if me is None:
            account = economy.get_user(uid)
            target = (player_rating(account), account.coins)
            better = sum(
                1
                for item in accounts
                if (player_rating(item), item.coins) > target
            )
            me = {
                "rank": better + 1,
                "user_id": uid,
                "name": display_name(account),
                "username": account.username,
                "rating": player_rating(account),
                "points": player_rating(account),
                "coins": account.coins,
                "wins": account.wins,
                "games": account.games_played,
                "medal": medal_for(better + 1),
                "is_me": True,
            }

    top = rows[:limit]
    for row in top:
        row.update(_cosmetics(int(row["user_id"])))
    if me is not None:
        me.update(_cosmetics(int(me["user_id"])))

    return {
        "period": PERIOD_ALL,
        "top": top,
        "me": me,
        "total": len(rows),
        "week_start": None,
        "week_end": None,
    }


def _weekly(
    economy: EconomyStore, limit: int, viewer_id: int | None
) -> dict[str, Any]:
    """Joriy haftalik liga (dushanba 00:00 dan boshlab)."""
    league = economy.weekly_league(limit=limit, viewer_id=viewer_id)
    top: list[dict[str, Any]] = []
    for row in league.get("top") or []:
        rank = int(row.get("rank") or 0)
        top.append(
            {
                **row,
                "rating": int(row.get("points") or 0),
                "medal": medal_for(rank),
                "is_me": viewer_id is not None
                and int(row.get("user_id") or 0) == int(viewer_id),
            }
        )
    me = league.get("me")
    if me:
        me = {
            **me,
            "rating": int(me.get("points") or 0),
            "medal": medal_for(int(me.get("rank") or 0)),
            "is_me": True,
        }
    for row in top:
        row.update(_cosmetics(int(row.get("user_id") or 0)))
    if me is not None:
        me.update(_cosmetics(int(me.get("user_id") or 0)))
    start, end = week_bounds()
    return {
        "period": PERIOD_WEEK,
        "top": top,
        "me": me,
        "total": int(league.get("total") or 0),
        "week_start": league.get("week_start") or start.isoformat(),
        "week_end": league.get("week_end") or end.isoformat(),
    }


def build_leaderboard(
    period: str | None = None,
    limit: int = 10,
    viewer_id: int | None = None,
    *,
    economy: EconomyStore | None = None,
) -> dict[str, Any]:
    """Tanlangan davr uchun reyting jadvalini qaytaradi."""
    kind = normalize_period(period)
    size = max(1, min(int(limit), 50))
    store = economy or get_economy()
    if kind == PERIOD_WEEK:
        return _weekly(store, size, viewer_id)
    return _all_time(store, size, viewer_id)
