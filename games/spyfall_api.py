"""Josus (Spyfall) uchun yengil xotira ichidagi xona API."""
from __future__ import annotations

import random
import string
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import TelegramUser, resolve_user_id, telegram_user

router = APIRouter(prefix="/api/spy", tags=["spyfall"])
_lock = threading.RLock()
_rooms: dict[str, dict[str, Any]] = {}

LOCATIONS = [
    "Aeroport", "Maktab", "Kasalxona", "Restoran", "Kinoteatr",
    "Plyaj", "Kosmik stansiya", "Muzey", "Mehmonxona", "Poyezd",
    "Supermarket", "Stadion", "Kutubxona", "Politsiya bo'limi",
    "Sirk", "Universitet", "Bank", "Hayvonot bog'i", "Kema", "Teatr"
]

class PlayerIn(BaseModel):
    user_id: int | None = None
    name: str = "O'yinchi"

class VoteIn(PlayerIn):
    target_id: int


def _identity(payload: PlayerIn, user: TelegramUser | None) -> tuple[int, str]:
    """Tasdiqlangan Telegram ID va server ishonadigan ismni qaytaradi."""
    user_id = resolve_user_id(user, payload.user_id)
    name = user.full_name if user is not None else payload.name
    return user_id, (name or "O'yinchi").strip()[:64]

def _code() -> str:
    while True:
        code = "SPY" + "".join(random.choices(string.digits, k=3))
        if code not in _rooms:
            return code

def _room(code: str) -> dict[str, Any]:
    room = _rooms.get(code.upper())
    if not room:
        raise HTTPException(404, "Josus xonasi topilmadi")
    return room

def _public(room: dict[str, Any], viewer: int) -> dict[str, Any]:
    return {
        "code": room["code"], "status": room["status"],
        "host_id": room["host_id"], "players_count": len(room["players"]),
        "players": [{"user_id": p["user_id"], "name": p["name"],
                     "is_host": p["user_id"] == room["host_id"],
                     "is_me": p["user_id"] == viewer,
                     "votes": sum(1 for v in room["votes"].values() if v == p["user_id"])}
                    for p in room["players"].values()],
        "votes_count": len(room["votes"]),
        "winner": room.get("winner"),
        "spy_id": room["spy_id"] if room["status"] == "FINISHED" else None,
    }

@router.post("/create")
def create(payload: PlayerIn, user: TelegramUser | None = Depends(telegram_user)):
    user_id, name = _identity(payload, user)
    with _lock:
        code = _code()
        room = {"code": code, "host_id": user_id, "status": "LOBBY",
                "players": {user_id: {"user_id": user_id, "name": name}},
                "roles": {}, "location": "", "spy_id": None, "votes": {}, "winner": None}
        _rooms[code] = room
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
        return {"state": _public(room, user_id)}

@router.get("/{code}")
def state(code: str, user_id: int | None = None, user: TelegramUser | None = Depends(telegram_user)):
    viewer_id = resolve_user_id(user, user_id)
    with _lock:
        room = _room(code)
        if viewer_id not in room["players"]:
            raise HTTPException(403, "Avval xonaga qo'shiling")
        role = room["roles"].get(viewer_id)
        return {"state": _public(room, viewer_id),
                "me": {"role": role, "location": room["location"] if role == "player" else None}}

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
        return {"state": _public(room, user_id),
                "me": {"role": room["roles"][user_id],
                       "location": room["location"] if user_id != spy else None}}

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
            if len(leaders) == 1 and leaders[0] == room["spy_id"]:
                room["winner"] = "players"
            elif len(leaders) == 1:
                room["winner"] = "spy"
            else:
                room["winner"] = "spy"
            room["status"] = "FINISHED"
        return {"state": _public(room, user_id),
                "me": {"role": room["roles"].get(user_id),
                       "location": room["location"] if room["roles"].get(user_id) == "player" else None},
                "spy_id": room["spy_id"] if room["status"] == "FINISHED" else None}
