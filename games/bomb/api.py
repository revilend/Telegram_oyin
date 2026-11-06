"""«Xavfli Bomba» Mini App API'si.

Prefix: ``/api/bomb``. Guruh boti va Mini App umumiy
:class:`~games.bomb.manager.BombManager` orqali bir xil xonalarni ko'radi.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import TelegramUser, resolve_room_user_id, telegram_user
from bot.handlers import bomb_group as bomb_bot
from core.economy import get_economy
from games.bomb.cards import CardType, card_payload
from games.bomb.engine import ActionResult, BombError, BombRoom, DrawResult
from games.bomb.manager import BombNotFoundError, get_default_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bomb", tags=["bomb"])

_runtime_bot: Any | None = None


def set_runtime_bot(bot: Any | None) -> None:
    """Guruh e'lonlari uchun botni ulaydi."""
    global _runtime_bot
    _runtime_bot = bot


class BombPlayerIn(BaseModel):
    """O'yinchini ko'rsatuvchi so'rov."""

    user_id: int | None = None
    name: str = "Öyinçi"


class BombPlayIn(BombPlayerIn):
    """Karta o'ynash so'rovi."""

    card_type: str
    target_id: int | None = None


def _identity(payload: BombPlayerIn, user: TelegramUser | None) -> tuple[int, str]:
    user_id = resolve_room_user_id(user, payload.user_id)
    name = (user.full_name or user.username) if user is not None else payload.name
    return user_id, (name or "Öyinçi").strip()[:64]


def _room(code: str) -> BombRoom:
    try:
        return get_default_manager().get_room(code)
    except BombNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _coins(user_id: int) -> int:
    try:
        return get_economy().get_user(user_id).coins
    except Exception:
        return 0


def _response(room: BombRoom, viewer_id: int) -> dict[str, Any]:
    return {
        "state": room.public_state(),
        "me": room.player_view(viewer_id),
        "coins": _coins(viewer_id),
    }


def _action_payload(result: DrawResult | ActionResult) -> dict[str, Any]:
    if isinstance(result, DrawResult):
        return {
            "kind": "draw",
            "card": card_payload(result.card) if result.card else None,
            "exploded": result.exploded,
            "defused": result.defused,
            "eliminated_id": result.eliminated_id,
            "next_player_id": result.next_player_id,
            "winner_id": result.winner_id,
            "game_over": result.game_over,
        }
    return {
        "kind": "play",
        "card": card_payload(result.card),
        "target_id": result.target_id,
        "stolen_card": (
            card_payload(result.stolen_card) if result.stolen_card else None
        ),
        "future_cards": [card.value for card in result.future_cards],
        "next_player_id": result.next_player_id,
        "winner_id": result.winner_id,
        "game_over": result.game_over,
    }


def _announce(room: BombRoom, result: DrawResult | ActionResult) -> None:
    bot = _runtime_bot
    if bot is None or not room.chat_id:
        return
    task = asyncio.create_task(bomb_bot.announce_action(bot, room, result))
    task.add_done_callback(
        lambda finished: finished.exception() if not finished.cancelled() else None
    )


def _announce_start(room: BombRoom) -> None:
    bot = _runtime_bot
    if bot is None or not room.chat_id:
        return
    task = asyncio.create_task(bomb_bot.announce_room(bot, room, "start"))
    task.add_done_callback(
        lambda finished: finished.exception() if not finished.cancelled() else None
    )


@router.post("/create")
async def create(
    payload: BombPlayerIn,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Yangi Bomb xonasini ochadi."""
    user_id, name = _identity(payload, user)
    room = get_default_manager().create_room(user_id, name)
    return _response(room, user_id)


@router.post("/{code}/join")
async def join(
    code: str,
    payload: BombPlayerIn,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Lobbiga qo'shiladi."""
    user_id, name = _identity(payload, user)
    try:
        room = get_default_manager().join(code, user_id, name)
    except BombError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _response(room, user_id)


@router.get("/{code}")
async def state(
    code: str,
    user_id: int | None = None,
    name: str = "",
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Xona holati va o'z qo'lingiz.

    Guruh havolasidan kirgan foydalanuvchi hali lobbida bo'lmasa, lobbi
    ochiq bo'lsa avtomatik qo'shiladi.
    """
    viewer_id = resolve_room_user_id(user, user_id)
    room = _room(code)
    if viewer_id not in room.players:
        if room.status.value == "LOBBY":
            try:
                room.add_player(viewer_id, name or "Öyinçi")
            except BombError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        else:
            raise HTTPException(403, "Avval xonaga qo'shiling")
    return _response(room, viewer_id)


@router.post("/{code}/start")
async def start(
    code: str,
    payload: BombPlayerIn,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """O'yinni boshlaydi (faqat xona egasi)."""
    user_id, _ = _identity(payload, user)
    try:
        room = get_default_manager().start(code, user_id)
    except BombError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _announce_start(room)
    return _response(room, user_id)


@router.post("/{code}/draw")
async def draw(
    code: str,
    payload: BombPlayerIn,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Navbatdagi karta tortish."""
    user_id, _ = _identity(payload, user)
    room = _room(code)
    try:
        result = room.draw_card(user_id)
    except BombError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _announce(room, result)
    response = _response(room, user_id)
    response["action"] = _action_payload(result)
    return response


@router.post("/{code}/play")
async def play(
    code: str,
    payload: BombPlayIn,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Harakat kartasini o'ynash."""
    user_id, _ = _identity(payload, user)
    room = _room(code)
    try:
        result = room.play_action_card(
            user_id,
            payload.card_type,
            target_id=payload.target_id,
        )
    except BombError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _announce(room, result)
    response = _response(room, user_id)
    response["action"] = _action_payload(result)
    return response


__all__ = [
    "BombPlayIn",
    "BombPlayerIn",
    "router",
    "set_runtime_bot",
]
