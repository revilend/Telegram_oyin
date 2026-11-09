"""Kunlik topshiriqlar, reroll va haftalik sandiq.

Kunlik 3 ta topshiriq har kuni foydalanuvchi uchun deterministik tarzda
tanlanadi. Progress ikki manbadan olinadi:

* o'yin statistikasi (``games_played``, ``wins``, ``referral_count``) —
  kun boshidagi holatga nisbatan farq;
* amallar (bonus, g'ildirak, do'kon, matchmaking) — kunning eventlari.

Holat ``daily_quest_state`` jadvalida, haftalik sandiq esa
``daily_quest_profile`` jadvalida saqlanadi. Supabase bo'lmasa hammasi
jarayon xotirasida ishlaydi.
"""

from __future__ import annotations

import logging
import random
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from core.db import safe_upsert

logger = logging.getLogger(__name__)

STATE_TABLE = "daily_quest_state"
PROFILE_TABLE = "daily_quest_profile"

TASHKENT = timezone(timedelta(hours=5))
DAILY_SLOTS = 3
CHEST_TARGET = 5
CHEST_REWARD = 150

EVENT_METRICS = ("bonus", "spin", "shop", "match")

_MEMORY_STATES: dict[tuple[int, str], dict[str, Any]] = {}
_MEMORY_PROFILES: dict[int, dict[str, Any]] = {}
_LOCK = threading.Lock()


class DailyQuestError(Exception):
    """Kunlik topshiriq amali bajarilmadi."""


@dataclass(frozen=True)
class Quest:
    """Bitta kunlik topshiriq ta'rifi."""

    key: str
    title: str
    emoji: str
    description: str
    metric: str
    target: int
    reward: int


QUESTS: tuple[Quest, ...] = (
    Quest(
        key="play_2",
        title="Ikki o'yin",
        emoji="🎲",
        description="Bugun 2 ta o'yinda qatnashing",
        metric="games_played",
        target=2,
        reward=40,
    ),
    Quest(
        key="play_4",
        title="To'rt o'yin",
        emoji="🕹",
        description="Bugun 4 ta o'yinda qatnashing",
        metric="games_played",
        target=4,
        reward=70,
    ),
    Quest(
        key="win_1",
        title="Bitta g'alaba",
        emoji="🏆",
        description="Bugun 1 marta g'olib bo'ling",
        metric="wins",
        target=1,
        reward=60,
    ),
    Quest(
        key="win_2",
        title="Ikki g'alaba",
        emoji="👑",
        description="Bugun 2 marta g'olib bo'ling",
        metric="wins",
        target=2,
        reward=110,
    ),
    Quest(
        key="bonus",
        title="Bonusingizni oling",
        emoji="🎁",
        description="Bugungi kunlik bonusni oling",
        metric="bonus",
        target=1,
        reward=30,
    ),
    Quest(
        key="spin",
        title="Omadni sinang",
        emoji="🎰",
        description="Bugun omad g'ildiragini aylantiring",
        metric="spin",
        target=1,
        reward=35,
    ),
    Quest(
        key="shop",
        title="Do'konga tashrif",
        emoji="🛍",
        description="Bugun do'kondan bitta buyum oling",
        metric="shop",
        target=1,
        reward=40,
    ),
    Quest(
        key="match",
        title="Jamoani toping",
        emoji="🤝",
        description="Bugun matchmaking navbatiga qo'shiling",
        metric="match",
        target=1,
        reward=30,
    ),
)

BY_KEY: dict[str, Quest] = {item.key: item for item in QUESTS}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_key(now: datetime | None = None) -> str:
    """Toshkent vaqti bo'yicha kun kaliti."""
    return (now or _now()).astimezone(TASHKENT).date().isoformat()


def _week_key(now: datetime | None = None) -> str:
    """Toshkent vaqti bo'yicha ISO hafta kaliti."""
    local = (now or _now()).astimezone(TASHKENT).date()
    iso = local.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _pick_keys(user_id: int, day: str, nonce: int = 0) -> list[str]:
    rng = random.Random(f"{int(user_id)}:{day}:{nonce}")
    return rng.sample([item.key for item in QUESTS], DAILY_SLOTS)


def _new_state(account: Any, day: str, nonce: int = 0) -> dict[str, Any]:
    return {
        "day": day,
        "keys": _pick_keys(account.user_id, day, nonce),
        "nonce": int(nonce),
        "baseline": {
            "games_played": int(account.games_played or 0),
            "wins": int(account.wins or 0),
            "referral_count": int(account.referral_count or 0),
        },
        "events": {},
        "claimed": [],
        "rerolled": False,
    }


def _load_state(store: Any, user_id: int) -> tuple[dict[str, Any], Any]:
    uid = int(user_id)
    account = store.ensure_user(uid)
    day = _day_key()
    key = (uid, day)
    state: dict[str, Any] | None = None
    # Supabase ustuvor: baza yoqilgan bo'lsa, fakt faqat bazadan olinadi
    # (RAM cache eski holatni bosib ketmasligi uchun).
    if getattr(store, "enabled", False):
        try:
            rows = (
                store.client.table(STATE_TABLE)
                .select("state")
                .eq("user_id", uid)
                .eq("day", day)
                .limit(1)
                .execute()
                .data
                or []
            )
            if rows:
                raw = rows[0].get("state")
                if isinstance(raw, dict):
                    state = dict(raw)
        except Exception:
            logger.exception("Kunlik topshiriq holatini o'qib bo'lmadi: %s", uid)
    if state is None:
        with _LOCK:
            cached = _MEMORY_STATES.get(key)
            if cached:
                state = dict(cached)
    if not state or state.get("day") != day:
        state = _new_state(account, day)
    state.setdefault("baseline", {})
    state.setdefault("events", {})
    state.setdefault("claimed", [])
    state.setdefault("keys", _pick_keys(uid, day))
    return state, account


def _save_state(store: Any, user_id: int, state: dict[str, Any]) -> None:
    uid = int(user_id)
    with _LOCK:
        _MEMORY_STATES[(uid, state["day"])] = dict(state)
    if not getattr(store, "enabled", False):
        return
    try:
        safe_upsert(
            store.client,
            STATE_TABLE,
            {"user_id": uid, "day": state["day"], "state": state},
            on_conflict="user_id,day",
        )
    except Exception:
        logger.exception("Kunlik topshiriq holatini saqlab bo'lmadi: %s", uid)


def _load_profile(store: Any, user_id: int) -> dict[str, Any]:
    uid = int(user_id)
    week = _week_key()
    profile: dict[str, Any] | None = None
    if getattr(store, "enabled", False):
        try:
            rows = (
                store.client.table(PROFILE_TABLE)
                .select("state")
                .eq("user_id", uid)
                .limit(1)
                .execute()
                .data
                or []
            )
            if rows:
                raw = rows[0].get("state")
                if isinstance(raw, dict):
                    profile = dict(raw)
        except Exception:
            logger.exception("Haftalik sandiq holatini o'qib bo'lmadi: %s", uid)
    if profile is None:
        with _LOCK:
            cached = _MEMORY_PROFILES.get(uid)
            if cached:
                profile = dict(cached)
    if not profile or profile.get("week") != week:
        profile = {"week": week, "claims": 0, "chest_claimed": False}
    return profile


def _save_profile(store: Any, user_id: int, profile: dict[str, Any]) -> None:
    uid = int(user_id)
    with _LOCK:
        _MEMORY_PROFILES[uid] = dict(profile)
    if not getattr(store, "enabled", False):
        return
    try:
        safe_upsert(
            store.client,
            PROFILE_TABLE,
            {"user_id": uid, "state": profile},
            on_conflict="user_id",
        )
    except Exception:
        logger.exception("Haftalik sandiq holatini saqlab bo'lmadi: %s", uid)


def _progress(account: Any, state: dict[str, Any], quest: Quest) -> int:
    if quest.metric in ("games_played", "wins", "referral_count"):
        baseline = int(state.get("baseline", {}).get(quest.metric, 0) or 0)
        current = int(getattr(account, quest.metric, 0) or 0)
        return max(0, min(current - baseline, quest.target))
    return max(0, min(int(state.get("events", {}).get(quest.metric, 0) or 0), quest.target))


def _quest_payload(account: Any, state: dict[str, Any], quest: Quest) -> dict[str, Any]:
    progress = _progress(account, state, quest)
    claimed = quest.key in state.get("claimed", [])
    return {
        "key": quest.key,
        "title": quest.title,
        "emoji": quest.emoji,
        "description": quest.description,
        "target": quest.target,
        "progress": progress,
        "percent": min(100, int(round(progress / quest.target * 100))),
        "reward": quest.reward,
        "claimed": claimed,
        "claimable": progress >= quest.target and not claimed,
    }


def daily_quests_payload(store: Any, user_id: int) -> dict[str, Any]:
    """Bugungi topshiriqlar, reroll va haftalik sandiq holati."""
    state, account = _load_state(store, user_id)
    profile = _load_profile(store, user_id)
    quests = [
        _quest_payload(account, state, BY_KEY[key])
        for key in state.get("keys", [])
        if key in BY_KEY
    ]
    claims = int(profile.get("claims", 0) or 0)
    claimed_chest = bool(profile.get("chest_claimed"))
    return {
        "day": state.get("day", _day_key()),
        "quests": quests,
        "rerolled": bool(state.get("rerolled")),
        "week": profile.get("week", _week_key()),
        "week_claims": min(claims, CHEST_TARGET),
        "chest_target": CHEST_TARGET,
        "chest_reward": CHEST_REWARD,
        "chest_ready": claims >= CHEST_TARGET and not claimed_chest,
        "chest_claimed": claimed_chest,
    }


def record_daily_event(store: Any, user_id: int, event: str, amount: int = 1) -> None:
    """Kunlik amal hisoblagichini oshiradi (bonus, spin, shop, match)."""
    name = str(event or "").strip().lower()
    if name not in EVENT_METRICS or int(amount) <= 0:
        return
    state, _ = _load_state(store, user_id)
    events = state.setdefault("events", {})
    events[name] = int(events.get(name, 0) or 0) + int(amount)
    _save_state(store, user_id, state)


def claim_daily_quest(store: Any, user_id: int, quest_key: str) -> dict[str, Any]:
    """Bajarilgan topshiriq mukofotini beradi."""
    key = str(quest_key or "").strip().lower()
    quest = BY_KEY.get(key)
    if quest is None:
        raise DailyQuestError("Noma'lum kunlik topshiriq")
    state, account = _load_state(store, user_id)
    if key not in state.get("keys", []):
        raise DailyQuestError("Bu topshiriq bugun sizga berilmagan")
    if key in state.get("claimed", []):
        raise DailyQuestError("Bu topshiriq mukofoti allaqachon olingan")
    payload = _quest_payload(account, state, quest)
    if not payload["claimable"]:
        raise DailyQuestError(
            f"Topshiriq hali bajarilmagan: {payload['progress']}/{quest.target}"
        )
    updated = store.add_coins(int(user_id), quest.reward)
    state.setdefault("claimed", []).append(key)
    _save_state(store, user_id, state)
    profile = _load_profile(store, user_id)
    profile["claims"] = int(profile.get("claims", 0) or 0) + 1
    _save_profile(store, user_id, profile)
    return {
        "quest": _quest_payload(updated, state, quest),
        "coins": updated.coins,
        "daily": daily_quests_payload(store, user_id),
    }


def reroll_daily_quests(store: Any, user_id: int) -> dict[str, Any]:
    """Kuniga bir marta topshiriqlarni almashtiradi."""
    state, account = _load_state(store, user_id)
    if state.get("rerolled"):
        raise DailyQuestError("Bugun allaqachon almashtirilgan")
    if state.get("claimed"):
        raise DailyQuestError("Mukofot olingandan keyin almashtirib bo'lmaydi")
    nonce = int(state.get("nonce", 0) or 0) + 1
    state["nonce"] = nonce
    state["keys"] = _pick_keys(int(user_id), state["day"], nonce)
    state["rerolled"] = True
    _save_state(store, user_id, state)
    return daily_quests_payload(store, user_id)


def claim_weekly_chest(store: Any, user_id: int) -> dict[str, Any]:
    """Haftada 5 ta topshiriq olingach sandiqni beradi."""
    profile = _load_profile(store, user_id)
    if profile.get("chest_claimed"):
        raise DailyQuestError("Haftalik sandiq allaqachon olingan")
    if int(profile.get("claims", 0) or 0) < CHEST_TARGET:
        raise DailyQuestError(
            f"Haftalik sandiq uchun yana {CHEST_TARGET - int(profile.get('claims', 0) or 0)} ta topshiriq kerak"
        )
    updated = store.add_coins(int(user_id), CHEST_REWARD)
    profile["chest_claimed"] = True
    _save_profile(store, user_id, profile)
    return {
        "amount": CHEST_REWARD,
        "coins": updated.coins,
        "daily": daily_quests_payload(store, user_id),
    }


def reset_memory() -> None:
    """Testlar uchun xotiradagi holatni tozalaydi."""
    with _LOCK:
        _MEMORY_STATES.clear()
        _MEMORY_PROFILES.clear()
