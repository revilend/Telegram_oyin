"""«Josus» (Spyfall) Mini App API'si.

Prefix: ``/api/spy``. Autentifikatsiya boshqa o'yinlardagi kabi Telegram
``initData`` (yoki ``ALLOW_GUEST_AUTH`` yoqilganda ``user_id``) orqali.
Xonalar guruh boti bilan umumiy :class:`SpyfallManager`da saqlanadi.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import TelegramUser, resolve_room_user_id, telegram_user
from bot.handlers import spy_group as spy_bot
from core.economy import get_economy
from games.spyfall.engine import HINT_PRICE, GuessOutcome, SpyfallRoom, VoteOutcome
from games.spyfall.locations import location_choices
from games.spyfall.manager import SpyfallManager, get_default_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/spy", tags=["spyfall"])

# Lifespan ichida yaratilgan bot: guruhga e'lon yuborish uchun.
_runtime_bot: Any | None = None


def set_runtime_bot(bot: Any | None) -> None:
    """Guruh e'lonlari uchun botni ulaydi (api.server lifespan)."""
    global _runtime_bot
    _runtime_bot = bot


class PlayerIn(BaseModel):
    """O'yinchini ko'rsatuvchi so'rov."""

    user_id: int | None = None
    name: str = "O'yinchi"


class VoteIn(PlayerIn):
    """Ovoz berish so'rovi."""

    target_id: int


class GuessIn(PlayerIn):
    """Josusning joy taxmini."""

    location: str = ""


def manager() -> SpyfallManager:
    return get_default_manager()


def _identity(payload: PlayerIn, user: TelegramUser | None) -> tuple[int, str]:
    """Tasdiqlangan Telegram ID va server ishonadigan ism."""
    user_id = resolve_room_user_id(user, payload.user_id)
    name = (user.full_name or user.username) if user is not None else payload.name
    return user_id, (name or "O'yinchi").strip()[:64]


def _coins(user_id: int) -> int:
    try:
        return get_economy().get_user(user_id).coins
    except Exception:
        return 0


def _response(room: SpyfallRoom, viewer_id: int) -> dict[str, Any]:
    """Xona holati + o'ziga ko'rinadigan sir + hamyon."""
    return {
        "state": room.public_state(viewer_id),
        "me": (
            room.player_view(viewer_id)
            if int(viewer_id) in room.players
            else None
        ),
        "locations": location_choices(),
        "coins": _coins(int(viewer_id)),
        "hint_price": HINT_PRICE,
    }


def _announce(room: SpyfallRoom, event: str) -> None:
    """Guruhga e'lon yuborishni fonda rejalashtiradi."""
    bot = _runtime_bot
    if bot is None or not room.chat_id:
        return
    task = asyncio.create_task(spy_bot.announce_room(bot, room, event))
    task.add_done_callback(
        lambda finished: finished.exception() if not finished.cancelled() else None
    )


def _outcome_payload(outcome: GuessOutcome | VoteOutcome | None) -> dict[str, Any] | None:
    if outcome is None:
        return None
    if isinstance(outcome, GuessOutcome):
        return {
            "kind": "guess",
            "correct": outcome.correct,
            "guessed": outcome.guessed_name,
            "winner": outcome.winner.value,
            "reason": outcome.reason,
        }
    return {
        "kind": "vote",
        "winner": outcome.winner.value,
        "accused_id": outcome.accused_id,
        "accused_name": outcome.accused_name,
        "spies": list(outcome.spies),
        "tie": outcome.tie,
        "reason": outcome.reason,
    }


@router.post("/create")
def create(
    payload: PlayerIn, user: TelegramUser | None = Depends(telegram_user)
) -> dict[str, Any]:
    """Yangi Josus xonasi ochadi."""
    user_id, name = _identity(payload, user)
    room = manager().create_room(user_id, name)
    return _response(room, user_id)


@router.post("/{code}/join")
def join(
    code: str, payload: PlayerIn, user: TelegramUser | None = Depends(telegram_user)
) -> dict[str, Any]:
    """Xonaga qo'shiladi."""
    user_id, name = _identity(payload, user)
    room = manager().join(code, user_id, name)
    return _response(room, user_id)


@router.get("/{code}")
def state(
    code: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Xona holati va o'z kartasi."""
    viewer_id = resolve_room_user_id(user, user_id)
    room = manager().get_room(code)
    room.ensure_phase()
    if viewer_id not in room.players:
        raise HTTPException(403, "Avval xonaga qo'shiling")
    return _response(room, viewer_id)


@router.post("/{code}/start")
def start(
    code: str, payload: PlayerIn, user: TelegramUser | None = Depends(telegram_user)
) -> dict[str, Any]:
    """O'yinni boshlaydi (faqat xona egasi)."""
    user_id, _ = _identity(payload, user)
    room = manager().start(code, user_id)
    _announce(room, "start")
    return _response(room, user_id)


@router.post("/{code}/guess")
def guess(
    code: str, payload: GuessIn, user: TelegramUser | None = Depends(telegram_user)
) -> dict[str, Any]:
    """Josus joyni taxmin qiladi."""
    user_id, _ = _identity(payload, user)
    room, outcome = manager().guess(code, user_id, payload.location)
    _announce(room, "finish")
    result = _response(room, user_id)
    result["result"] = _outcome_payload(outcome)
    return result


@router.post("/{code}/vote")
def vote(
    code: str, payload: VoteIn, user: TelegramUser | None = Depends(telegram_user)
) -> dict[str, Any]:
    """Josus deb ovoz beradi; hamma ovoz bersa o'yin yakunlanadi."""
    user_id, _ = _identity(payload, user)
    room, outcome = manager().vote(code, user_id, payload.target_id)
    if outcome is not None:
        _announce(room, "finish")
    result = _response(room, user_id)
    result["result"] = _outcome_payload(outcome)
    return result


@router.post("/{code}/tally")
def tally(
    code: str, payload: PlayerIn, user: TelegramUser | None = Depends(telegram_user)
) -> dict[str, Any]:
    """Ovozlarni muddatidan oldin sanaydi (faqat xona egasi)."""
    user_id, _ = _identity(payload, user)
    room, outcome = manager().tally(code, user_id)
    _announce(room, "finish")
    result = _response(room, user_id)
    result["result"] = _outcome_payload(outcome)
    return result


@router.post("/{code}/hint")
def hint(
    code: str, payload: PlayerIn, user: TelegramUser | None = Depends(telegram_user)
) -> dict[str, Any]:
    """«Josus radari»: 20 tangaga 3 ta noto'g'ri lokatsiya o'chiriladi."""
    user_id, _ = _identity(payload, user)
    room, excluded, coins = manager().buy_hint(code, user_id)
    result = _response(room, user_id)
    result["excluded"] = list(excluded)
    result["coins"] = coins
    return result
