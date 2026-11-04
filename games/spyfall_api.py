"""Josus (Spyfall) API: Telegram autentifikatsiyasi va ixtiyoriy Supabase saqlashi."""
from __future__ import annotations

import logging
import random
import string
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import TelegramUser, resolve_user_id, telegram_user
from core.db import get_store

router = APIRouter(prefix="/api/spy", tags=["spyfall"])
_lock = threading.RLock()
_rooms: dict[str, dict[str, Any]] = {}
logger = logging.getLogger(__name__)
SPYFALL_TABLE = "spyfall_rooms"

LOCATIONS = [
    "Aeroport", "Maktab", "Kasalxona", "Restoran", "Kinoteatr",
    "Plyaj", "Kosmik stansiya", "Muzey", "Mehmonxona", "Poyezd",
    "Supermarket", "Stadion", "Kutubxona", "Politsiya bo'limi",
    "Sirk", "Universitet", "Bank", "Hayvonot bog'i", "Kema", "Teatr",
]


class PlayerIn(BaseModel):
    user_id: int | None = None
    name: str = "O'yinchi"


class VoteIn(PlayerIn):
    target_id: int


def _identity(payload: PlayerIn, user: TelegramUser | None) -> tuple[int, str]:
    """Tasdiqlangan Telegram ID va server ishonadigan ismni qaytaradi."""
    user_id = resolve_user_id(user, payload.user_id)
    name = (user.full_name or user.username) if user is not None else payload.name
    return user_id, (name or "O'yinchi").strip()[:64]


def _persist_room(room: dict[str, Any]) -> None:
    """Xona holatini Supabase'ga yozadi; baza sozlanmagan bo'lsa xotirada qoladi."""
    store = get_store()
    if not store.enabled:
        return
    snapshot = {
        "code": room["code"],
        "host_id": int(room["host_id"]),
        "status": room["status"],
        "players": {str(uid): player for uid, player in room["players"].items()},
        "roles": {str(uid): role for uid, role in room["roles"].items()},
        "location": room["location"],
        "spy_id": room["spy_id"],
        "votes": {str(uid): int(target) for uid, target in room["votes"].items()},
        "winner": room.get("winner"),
    }
    try:
        store.client.table(SPYFALL_TABLE).upsert(
            {
                "code": room["code"],
                "state": snapshot,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="code",
        ).execute()
    except Exception:
        logger.exception("Josus %s xonasini Supabase'ga saqlab bo'lmadi", room["code"])


def _restore_room(code: str) -> dict[str, Any] | None:
    """Xonani Supabase'dan yuklaydi va xotiraga tiklaydi."""
    store = get_store()
    if not store.enabled:
        return None
    try:
        rows = (
            store.client.table(SPYFALL_TABLE)
            .select("state")
            .eq("code", code.upper())
            .limit(1)
            .execute()
            .data
            or []
        )
        if not rows:
            return None
        state = rows[0].get("state") or {}
        players = {
            int(uid): {"user_id": int(player["user_id"]), "name": str(player["name"])}
            for uid, player in (state.get("players") or {}).items()
        }
        room = {
            "code": str(state.get("code") or code.upper()),
            "host_id": int(state["host_id"]),
            "status": str(state["status"]),
            "players": players,
            "roles": {int(uid): role for uid, role in (state.get("roles") or {}).items()},
            "location": str(state.get("location") or ""),
            "spy_id": int(state["spy_id"]) if state.get("spy_id") is not None else None,
            "votes": {
                int(uid): int(target)
                for uid, target in (state.get("votes") or {}).items()
            },
            "winner": state.get("winner"),
        }
        _rooms[room["code"]] = room
        return room
    except Exception:
        logger.exception("Josus %s xonasini Supabase'dan tiklab bo'lmadi", code)
        return None


def _code() -> str:
    for _ in range(1000):
        code = "SPY" + "".join(random.choices(string.digits, k=3))
        if code not in _rooms and _restore_room(code) is None:
            return code
    raise HTTPException(503, "Bo'sh Josus xonasi kodi topilmadi")


def _room(code: str) -> dict[str, Any]:
    normalized = code.upper()
    room = _rooms.get(normalized) or _restore_room(normalized)
    if not room:
        raise HTTPException(404, "Josus xonasi topilmadi")
    return room


def _public(room: dict[str, Any], viewer: int) -> dict[str, Any]:
    return {
        "code": room["code"],
        "status": room["status"],
        "host_id": room["host_id"],
        "players_count": len(room["players"]),
        "players": [
            {
                "user_id": player["user_id"],
                "name": player["name"],
                "is_host": player["user_id"] == room["host_id"],
                "is_me": player["user_id"] == viewer,
                "has_voted": player["user_id"] == viewer and viewer in room["votes"],
                "votes": sum(
                    1 for target in room["votes"].values()
                    if target == player["user_id"]
                ),
            }
            for player in room["players"].values()
        ],
        "votes_count": len(room["votes"]),
        "winner": room.get("winner"),
        "spy_id": room["spy_id"] if room["status"] == "FINISHED" else None,
    }


@router.post("/create")
def create(payload: PlayerIn, user: TelegramUser | None = Depends(telegram_user)):
    user_id, name = _identity(payload, user)
    with _lock:
        code = _code()
        room = {
            "code": code,
            "host_id": user_id,
            "status": "LOBBY",
            "players": {user_id: {"user_id": user_id, "name": name}},
            "roles": {},
            "location": "",
            "spy_id": None,
            "votes": {},
            "winner": None,
        }
        _rooms[code] = room
        _persist_room(room)
        return {"state": _public(room, user_id), "me": {"role": None, "location": None}}


@router.post("/{code}/join")
def join(code: str, payload: PlayerIn, user: TelegramUser | None = Depends(telegram_user)):
    user_id, name = _identity(payload, user)
    with _lock:
        room = _room(code)
        if room["status"] != "LOBBY":
            raise HTTPException(400, "O'yin boshlangan")
        if user_id not in room["players"] and len(room["players"]) >= 10:
            raise HTTPException(400, "Xonada eng ko'pi bilan 10 o'yinchi bo'ladi")
        room["players"][user_id] = {"user_id": user_id, "name": name}
        _persist_room(room)
        return {"state": _public(room, user_id)}


@router.get("/{code}")
def state(
    code: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
):
    viewer_id = resolve_user_id(user, user_id)
    with _lock:
        room = _room(code)
        if viewer_id not in room["players"]:
            raise HTTPException(403, "Avval xonaga qo'shiling")
        role = room["roles"].get(viewer_id)
        return {
            "state": _public(room, viewer_id),
            "me": {
                "role": role,
                "location": room["location"] if role == "player" else None,
            },
        }


@router.post("/{code}/start")
def start(code: str, payload: PlayerIn, user: TelegramUser | None = Depends(telegram_user)):
    user_id, _ = _identity(payload, user)
    with _lock:
        room = _room(code)
        if user_id != room["host_id"]:
            raise HTTPException(403, "Faqat xona egasi boshlaydi")
        if len(room["players"]) < 3:
            raise HTTPException(400, "Boshlash uchun kamida 3 o'yinchi kerak")
        if room["status"] != "LOBBY":
            raise HTTPException(400, "O'yin allaqachon boshlangan")
        ids = list(room["players"])
        spy = random.choice(ids)
        room["location"] = random.choice(LOCATIONS)
        room["spy_id"] = spy
        room["roles"] = {uid: ("spy" if uid == spy else "player") for uid in ids}
        room["status"] = "PLAYING"
        _persist_room(room)
        return {
            "state": _public(room, user_id),
            "me": {
                "role": room["roles"][user_id],
                "location": room["location"] if user_id != spy else None,
            },
        }


@router.post("/{code}/vote")
def vote(code: str, payload: VoteIn, user: TelegramUser | None = Depends(telegram_user)):
    user_id, _ = _identity(payload, user)
    with _lock:
        room = _room(code)
        if room["status"] != "PLAYING":
            raise HTTPException(400, "Ovoz berish vaqti emas")
        if user_id not in room["players"] or payload.target_id not in room["players"]:
            raise HTTPException(400, "O'yinchi topilmadi")
        if payload.target_id == user_id:
            raise HTTPException(400, "O'zingizga ovoz bera olmaysiz")
        if user_id in room["votes"]:
            raise HTTPException(400, "Siz allaqachon ovoz bergansiz")
        room["votes"][user_id] = payload.target_id
        if len(room["votes"]) == len(room["players"]):
            counts: dict[int, int] = {}
            for target in room["votes"].values():
                counts[target] = counts.get(target, 0) + 1
            highest = max(counts.values())
            leaders = [uid for uid, count in counts.items() if count == highest]
            room["winner"] = (
                "players" if len(leaders) == 1 and leaders[0] == room["spy_id"]
                else "spy"
            )
            room["status"] = "FINISHED"
        _persist_room(room)
        return {
            "state": _public(room, user_id),
            "me": {
                "role": room["roles"].get(user_id),
                "location": (
                    room["location"]
                    if room["roles"].get(user_id) == "player"
                    else None
                ),
            },
            "spy_id": room["spy_id"] if room["status"] == "FINISHED" else None,
        }
