"""Revilend Games Mini App uchun FastAPI serveri.

Server «Bunker» xonalarini mavjud :class:`GameManager` orqali boshqaradi va
Mini App'ga ochiq xona holati, shaxsiy kartalar, harakatlar hamda WebSocket
orqali real-vaqt yangilanishlarni beradi.

Ishga tushirish::

    uvicorn api.server:app --host 0.0.0.0 --port 8000

Bot bilan bir xil xotirani ishlatish uchun ``python run.py`` dan foydalaning —
aks holda bot ochgan xonalar API jarayonida ko'rinmaydi.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine.game_manager import (
    GameError,
    GameManager,
    PlayerNotFoundError,
    RoomNotFoundError,
    get_default_manager,
)
from models.game import GameRoom, Player

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEBAPP_DIR = PROJECT_ROOT / "webapp"

GAME_TYPE = "bunker"

GAMES: list[dict[str, Any]] = [
    {
        "slug": "bunker",
        "name": "Bunker",
        "emoji": "☢️",
        "status": "active",
        "players": "2–12",
        "description": "Falokatdan keyin omon qolish uchun guruh bo'lib kartalaringizni "
        "oching, bahslashing va bunkerga kim tushishini hal qiling.",
    },
    {
        "slug": "mafia",
        "name": "Mafiya",
        "emoji": "🕵️",
        "status": "coming_soon",
        "players": "6–16",
        "description": "Kechki shaharda mafiya va tinch aholi o'rtasidagi sirli "
        "kurash. Tez orada.",
    },
    {
        "slug": "spyfall",
        "name": "Josus",
        "emoji": "🕶️",
        "status": "coming_soon",
        "players": "4–10",
        "description": "Hamma joyni biladi, faqat bitta josus bilmaydi. Savol-javob "
        "orqali uni toping. Tez orada.",
    },
]


# ----------------------------------------------------------------------
# Sxemalar
# ----------------------------------------------------------------------
class ActionRequest(BaseModel):
    """Mini App'dan keladigan umumiy o'yin harakati."""

    user_id: int
    action: Literal["join", "start", "reveal", "vote", "tally"]
    card_type: str | None = None
    target_id: int | None = None
    full_name: str | None = None
    username: str | None = None


# ----------------------------------------------------------------------
# Holatni Mini App uchun proyeksiya qilish
# ----------------------------------------------------------------------
def _card_payload(card: Any) -> dict[str, Any]:
    return {
        "type": card.type.value,
        "title": card.title,
        "description": card.description,
        "is_revealed": card.is_revealed,
    }


def _player_payload(player: Player, viewer_id: int) -> dict[str, Any]:
    return {
        "user_id": player.user_id,
        "full_name": player.full_name or player.username or str(player.user_id),
        "username": player.username,
        "is_alive": player.is_alive,
        "is_host": player.is_host,
        "is_me": player.user_id == viewer_id,
        "votes_against": player.votes_against,
        "hidden_count": len(player.cards) - len(player.revealed_cards()),
        "revealed_cards": {
            key: {
                "type": card.type.value,
                "title": card.title,
                "description": card.description,
            }
            for key, card in player.revealed_cards().items()
        },
    }


def public_state(room: GameRoom, viewer_id: int = 0) -> dict[str, Any]:
    """Xonaning hamma o'yinchilarga ko'rinadigan holati."""
    return {
        "game_type": GAME_TYPE,
        "room_id": room.room_id,
        "code": room.code,
        "status": room.status.value,
        "host_id": room.host_id,
        "max_players": room.max_players,
        "bunker_capacity": room.bunker_capacity,
        "current_round": room.current_round,
        "catastrophe": room.catastrophe,
        "alive_count": len(room.alive_players),
        "eliminated_players": room.eliminated_players,
        "players": [_player_payload(player, viewer_id) for player in room.players.values()],
    }


def private_state(room: GameRoom, user_id: int) -> dict[str, Any]:
    """O'yinchining o'ziga ko'rinadigan yashirin kartalari."""
    player = room.get_player(user_id)
    if player is None:
        raise PlayerNotFoundError(f"Siz {room.code} xonasida emassiz")

    return {
        "game_type": GAME_TYPE,
        "code": room.code,
        "user_id": player.user_id,
        "full_name": player.full_name,
        "is_alive": player.is_alive,
        "is_host": player.is_host,
        "status": room.status.value,
        "cards": {key: _card_payload(card) for key, card in player.cards.items()},
    }


# ----------------------------------------------------------------------
# WebSocket ulanishlari
# ----------------------------------------------------------------------
class RoomHub:
    """Xona kodlari bo'yicha WebSocket ulanishlarini boshqaradi."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, code: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[code].add(websocket)

    async def disconnect(self, code: str, websocket: WebSocket) -> None:
        async with self._lock:
            connections = self._connections.get(code)
            if connections is None:
                return
            connections.discard(websocket)
            if not connections:
                self._connections.pop(code, None)

    async def broadcast(self, code: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._connections.get(code, ()))
        stale: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(payload)
            except Exception:  # uzilgan ulanishni tozalaymiz
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(code, websocket)

    def count(self, code: str) -> int:
        return len(self._connections.get(code, ()))


hub = RoomHub()


def card_type_options() -> list[dict[str, str]]:
    """Mini App'da ko'rsatiladigan karta turlari (tartib bilan)."""
    return [
        {"key": "profession", "label": "Kasb", "emoji": "🧑‍🔧"},
        {"key": "biology", "label": "Biologiya", "emoji": "🧬"},
        {"key": "health", "label": "Salomatlik", "emoji": "❤️"},
        {"key": "hobby", "label": "Xobbi", "emoji": "🎯"},
        {"key": "luggage", "label": "Yuk", "emoji": "🎒"},
        {"key": "fact", "label": "Fakt", "emoji": "📜"},
        {"key": "special", "label": "Maxsus", "emoji": "⭐"},
    ]


# ----------------------------------------------------------------------
# Ilova
# ----------------------------------------------------------------------
app = FastAPI(title="Revilend Games API", version="1.0.0")


@app.exception_handler(RoomNotFoundError)
async def room_not_found_handler(request: Any, exc: RoomNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(PlayerNotFoundError)
async def player_not_found_handler(request: Any, exc: PlayerNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(GameError)
async def game_error_handler(request: Any, exc: GameError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def manager() -> GameManager:
    return get_default_manager()


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "game_type": GAME_TYPE}


@app.get("/api/games")
async def list_games() -> dict[str, Any]:
    """Mavjud o'yinlar ro'yxati."""
    return {"games": GAMES}


@app.get("/api/meta/cards")
async def meta_cards() -> dict[str, Any]:
    """Karta turlarining yorliqlari."""
    return {"card_types": card_type_options()}


@app.get("/api/room/{code}")
async def get_room(code: str, user_id: int = 0) -> dict[str, Any]:
    """Xonaning ochiq holati: falokat, raund, ochilgan kartalar."""
    room = manager().get_room(code)
    return {"state": public_state(room, viewer_id=user_id)}


@app.get("/api/room/{code}/me")
async def get_my_cards(code: str, user_id: int) -> dict[str, Any]:
    """O'yinchining shaxsiy yashirin kartalari."""
    room = manager().get_room(code)
    return {"me": private_state(room, user_id)}


@app.post("/api/room/{code}/action")
async def room_action(code: str, payload: ActionRequest) -> dict[str, Any]:
    """Umumiy o'yin harakatlari: qo'shilish, boshlash, ochish, ovoz, sanash."""
    game_manager = manager()
    result: dict[str, Any] | None = None

    if payload.action == "join":
        if not payload.full_name:
            raise HTTPException(status_code=400, detail="full_name majburiy")
        game_manager.join_room(
            code,
            payload.user_id,
            payload.full_name,
            payload.username or "",
        )
    elif payload.action == "start":
        room = game_manager.get_room(code)
        if room.host_id != payload.user_id:
            raise HTTPException(
                status_code=403,
                detail="O'yinni faqat xona egasi boshlashi mumkin",
            )
        game_manager.start_game(code)
    elif payload.action == "reveal":
        if not payload.card_type:
            raise HTTPException(status_code=400, detail="card_type majburiy")
        game_manager.reveal_card(code, payload.user_id, payload.card_type)
    elif payload.action == "vote":
        if payload.target_id is None:
            raise HTTPException(status_code=400, detail="target_id majburiy")
        game_manager.cast_vote(code, payload.user_id, payload.target_id)
    elif payload.action == "tally":
        room = game_manager.get_room(code)
        if room.host_id != payload.user_id:
            raise HTTPException(
                status_code=403,
                detail="Ovozlarni faqat xona egasi sanaydi",
            )
        eliminated = game_manager.tally_votes(code)
        result = {
            "eliminated": (
                {
                    "user_id": eliminated.user_id,
                    "full_name": eliminated.full_name,
                }
                if eliminated is not None
                else None
            ),
            "tie": eliminated is None,
        }

    room = game_manager.get_room(code)
    state = public_state(room, viewer_id=payload.user_id)
    await hub.broadcast(code, {"type": "state", "state": state})
    return {
        "ok": True,
        "state": state,
        "me": private_state(room, payload.user_id),
        "result": result,
    }


@app.websocket("/ws/{code}")
async def room_socket(websocket: WebSocket, code: str) -> None:
    """Xona uchun real-vaqt kanali: har bir o'zgarishda yangi holat."""
    normalized = (code or "").strip().upper()
    try:
        room = manager().get_room(normalized)
    except GameError:
        await websocket.close(code=4404)
        return

    await hub.connect(normalized, websocket)
    try:
        await websocket.send_json(
            {"type": "state", "state": public_state(room)}
        )
        while True:
            message = await websocket.receive_text()
            if message.strip() == "ping":
                await websocket.send_json({"type": "pong"})
            elif message.strip() == "sync":
                current = manager().get_room(normalized)
                await websocket.send_json(
                    {"type": "state", "state": public_state(current)}
                )
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(normalized, websocket)


# Statik Mini App: API va WebSocket yo'llaridan keyin ulanadi.
if WEBAPP_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEBAPP_DIR, html=True), name="webapp")
