"""Revilend Games Mini App va Telegram bot uchun yagona FastAPI serveri.

Server «Bunker» xonalarini :class:`GameManager` orqali boshqaradi, holatni
Supabase'da saqlaydi (sozlangan bo'lsa), Mini App'ga ochiq xona holati,
shaxsiy kartalar, harakatlar va WebSocket yangilanishlarini beradi.

`lifespan` ichida aiogram bot ham fonda ishga tushadi, shuning uchun Render'da
bitta Web Service yetarli::

    uvicorn api.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api.auth import (
    TelegramUser,
    resolve_room_user_id,
    resolve_user_id,
    telegram_user,
)
from games.spyfall.api import router as spyfall_router
from games.spyfall.api import set_runtime_bot as set_spyfall_bot
from games.spyfall.engine import SpyfallError
from games.spyfall.manager import SpyfallNotFoundError, get_default_manager as get_spyfall_manager
from bot.config import get_config
from bot.handlers import mafia_group as mafia_bot
from bot.handlers import matchmaking as matchmaking_bot
from bot.handlers import tournaments as tournaments_handler
from bot.handlers.boosters import send_shield_offer
from bot.localized import LocalizedBot
from bot.main import build_dispatcher, set_commands
from core.billing import buy_booster, decline_shield
from core.db import get_store
from core.economy import (
    COIN_PACKAGES,
    EconomyError,
    InsufficientCoinsError,
    get_economy,
    player_rating,
)
from core.login_codes import verify_login_code
from core.shop import (
    ShopError,
    ShopInsufficientCoinsError,
    SpinUnavailableError,
    UnknownItemError,
    get_shop_store,
)
from core.leaderboard import build_leaderboard, normalize_period
from core.tournaments import (
    AlreadyJoinedError,
    EntryFeeError,
    TournamentClosedError,
    TournamentError,
    TournamentFullError,
    TournamentNotFoundError,
    get_tournament_store,
)
from core.metrics import metrics
from engine.chat import ChatAccess, ChatError, ChatHub
from engine.cleaner import get_cleaner
from engine.matchmaking import (
    MatchmakingError,
    check_and_create_matches,
    get_matchmaker,
    get_queue_store,
    normalize_game_type,
)
from games.alias.engine import get_default_manager as get_alias_manager
from core.missions import claim_mission, mission_statuses, missions_payload
from core.settings import get_settings_store
from engine.boosters import BoosterError, boosters_payload
from engine.game_manager import (
    GameError,
    GameManager,
    PlayerNotFoundError,
    RoomNotFoundError,
    get_default_manager,
)
from games.mafia.engine import (
    GamePhase,
    MafiaError,
    MafiaRole,
    NIGHT_ACTION_BY_ROLE,
    NIGHT_OPTIONS_BY_ROLE,
    resolve_day_vote,
)
from games.mafia.boosters import (
    MafiaBoosterError,
    booster_options,
    purchase_booster,
)
from games.mafia.images import COVER_IMAGE, role_image_url
from games.mafia.roles import Faction, get_role_profile
from models.game import GameRoom, Player, RoomStatus

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEBAPP_DIR = PROJECT_ROOT / "webapp"
ASSETS_DIR = WEBAPP_DIR / "assets"

GAME_TYPE = "bunker"
logger = logging.getLogger(__name__)

# Lifespan ichida yaratilgan bot: qalqon taklifini shaxsiy xabar bilan yuborish uchun.
_runtime_bot: Bot | None = None

GAMES: list[dict[str, Any]] = [
    {
        "slug": "bunker",
        "name": "Bunker",
        "emoji": "☢️",
        "status": "active",
        "players": "4–16",
        "description": "Falokatdan keyin omon qolish uchun guruh bo'lib kartalaringizni "
        "oching, bahslashing va bunkerga kim tushishini hal qiling.",
    },
    {
        "slug": "mafia",
        "name": "Mafiya",
        "emoji": "🕵️",
        "status": "active",
        "players": "4–20",
        "description": "Kechki shaharda mafiya va tinch aholi o'rtasidagi sirli "
        "kurash. Guruhda /mafia bilan boshlang.",
    },
    {
        "slug": "spyfall",
        "name": "Josus",
        "emoji": "🕶️",
        "status": "active",
        "players": "3–12",
        "description": "Hamma joyni biladi, faqat bitta josus bilmaydi. Savol-javob "
        "orqali uni toping.",
    },
    {
        "slug": "alias",
        "name": "Alias / Krokodil",
        "emoji": "🐊",
        "status": "active",
        "players": "2–20",
        "description": "Tezkor so'z tushuntirish va topish poygasi. Guruhda /alias "
        "bilan boshlang.",
    },
]


# ----------------------------------------------------------------------
# Sxemalar
# ----------------------------------------------------------------------
class ActionRequest(BaseModel):
    """Mini App'dan keladigan umumiy o'yin harakati.

    `user_id` ixtiyoriy: initData header mavjud bo'lsa, identifikatsiya
    undan olinadi va bu maydon e'tiborga olinmaydi.
    """

    user_id: int | None = None
    action: Literal[
        "join",
        "start",
        "reveal",
        "vote",
        "tally",
        "booster",
        "shield_decline",
    ]
    card_type: str | None = None
    target_id: int | None = None
    full_name: str | None = None
    username: str | None = None
    booster: str | None = None


class UserRequest(BaseModel):
    """Faqat foydalanuvchini ko'rsatuvchi so'rov (initData ustuvor)."""

    user_id: int | None = None


class JoinRequest(UserRequest):
    """Global qidiruvdan xonaga qo'shilish so'rovi."""

    full_name: str = ""
    username: str = ""


class PromoCodeRequest(UserRequest):
    """Promo kodni ishlatish so'rovi."""

    code: str = ""


class LoginRequest(BaseModel):
    """Mini App kirish so'rovi: bir martalik kod yoki Telegram ID."""

    login: str | None = None
    code: str | None = None
    user_id: int | None = None


class MafiaBoosterRequest(UserRequest):
    """Mafiya boosterini sotib olish so'rovi."""

    booster: str = ""

class MafiaNightActionRequest(UserRequest):
    """Mafiya tungi harakati."""

    target_id: int
    kind: str | None = None


class MafiaVoteRequest(UserRequest):
    """Mafiya kunduzgi ovozi."""

    target_id: int


class MafiaTallyRequest(UserRequest):
    """Mafiya ovozlarini sanash."""

    kamikaze_target_id: int | None = None


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
        "pending_shield": (
            room.pending_shield.model_dump(mode="json")
            if room.pending_shield is not None
            else None
        ),
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
        "shield_used": player.shield_used,
        "double_vote": player.double_vote,
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
# Lifespan: Supabase, bot polling va tozalash
# ----------------------------------------------------------------------
def setup_persistence() -> None:
    """Supabase sozlangan bo'lsa, saqlash/yuklash va hamyonni ulaydi."""
    game_manager = get_default_manager()
    economy = get_economy()
    # Qalqon taklifi faqat tangasi yetadigan o'yinchiga ko'rsatiladi.
    game_manager.set_coin_balance_reader(lambda user_id: economy.get_user(user_id).coins)
    logger.info("Tanga hamyoni o'yin dvigateliga ulandi (Supabase: %s)", economy.enabled)

    store = get_store()
    if not store.enabled:
        return
    game_manager.set_change_handler(store.persist)
    game_manager.set_room_loader(store.load_room)
    logger.info("Supabase saqlash va xona yuklash yoqilgan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Server bilan birga aiogram botni ishga tushiradi va to'xtatadi."""
    setup_persistence()

    global _runtime_bot
    bot: Bot | None = None
    polling: asyncio.Task[None] | None = None
    reminders: asyncio.Task[None] | None = None
    token = (os.getenv("BOT_TOKEN") or "").strip()

    if token:
        try:
            bot = LocalizedBot(
                token=token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            _runtime_bot = bot
            set_spyfall_bot(bot)
            dispatcher = build_dispatcher()
            await set_commands(bot)
            polling = asyncio.create_task(dispatcher.start_polling(bot))
            reminders = tournaments_handler.start_reminder_loop(bot)
            logger.info("Aiogram polling fonda ishga tushdi")
        except Exception:  # bot xatosi Mini App'ni to'xtatmasligi kerak
            logger.exception("Botni ishga tushirib bo'lmadi")
            _runtime_bot = None
            set_spyfall_bot(None)
            if bot is not None:
                await bot.session.close()
            bot = None
            polling = None
    else:
        logger.warning("BOT_TOKEN yo'q — bot polling o'chirilgan")

    matchmaker = get_matchmaker()
    matchmaker.set_room_factory(_create_match_room)
    matchmaker.set_notifier(_notify_match)
    # Navbat Supabase'da saqlanadi: jarayon qayta ishga tushsa ham yo'qolmaydi.
    matchmaker.set_store(get_queue_store())
    cleaner = get_cleaner()
    cleaner.start()
    watcher = asyncio.create_task(_matchmaking_watch())

    try:
        yield
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        await get_cleaner().stop()
        matchmaker.set_room_factory(None)
        matchmaker.set_notifier(None)
        matchmaker.set_store(None)
        matchmaker.reset()
        if bot is not None:
            await bot.session.close()
        _runtime_bot = None
        set_spyfall_bot(None)
        if reminders is not None:
            reminders.cancel()
            await asyncio.gather(reminders, return_exceptions=True)
        if polling is not None:
            polling.cancel()
            await asyncio.gather(polling, return_exceptions=True)
        get_store().close()
        # Global menejerni yopilgan omborga bog'lab qo'ymaymiz: keyingi ishga
        # tushirish (yoki test) toza holatdan boshlanadi.
        game_manager = get_default_manager()
        game_manager.set_coin_balance_reader(None)
        game_manager.set_change_handler(None)
        game_manager.set_room_loader(None)


# ----------------------------------------------------------------------
# Ilova
# ----------------------------------------------------------------------
app = FastAPI(title="Revilend Games API", version="1.2.0", lifespan=lifespan)


@app.middleware("http")
async def count_requests(request: Request, call_next: Any) -> Any:
    """Monitoring uchun so'rovlar va server xatolarini sanaydi.

    Markaziy xatolik tutuvchi: kutilmagan har qanday xatolik to'liq stack-trace
    bilan jurnalga yoziladi, mijoz esa umumiy 500 javobini oladi.
    """
    metrics.request()
    try:
        response = await call_next(request)
    except Exception:
        metrics.error()
        logger.exception(
            "So'rovda kutilmagan xatolik: %s %s",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Serverda ichki xatolik yuz berdi"},
        )
    if int(getattr(response, "status_code", 0)) >= 500:
        metrics.error()
    return response


app.include_router(spyfall_router)


@app.exception_handler(RoomNotFoundError)
async def room_not_found_handler(request: Any, exc: RoomNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(PlayerNotFoundError)
async def player_not_found_handler(request: Any, exc: PlayerNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(SpyfallNotFoundError)
async def spyfall_not_found_handler(
    request: Any, exc: SpyfallNotFoundError
) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(SpyfallError)
async def spyfall_error_handler(request: Any, exc: SpyfallError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(InsufficientCoinsError)
async def insufficient_coins_handler(
    request: Any, exc: InsufficientCoinsError
) -> JSONResponse:
    return JSONResponse(status_code=402, content={"detail": str(exc)})


@app.exception_handler(BoosterError)
async def booster_error_handler(request: Any, exc: BoosterError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(EconomyError)
async def economy_error_handler(request: Any, exc: EconomyError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ShopInsufficientCoinsError)
async def shop_coins_handler(
    request: Any, exc: ShopInsufficientCoinsError
) -> JSONResponse:
    return JSONResponse(status_code=402, content={"detail": str(exc)})


@app.exception_handler(SpinUnavailableError)
async def spin_unavailable_handler(
    request: Any, exc: SpinUnavailableError
) -> JSONResponse:
    return JSONResponse(status_code=402, content={"detail": str(exc)})


@app.exception_handler(UnknownItemError)
async def unknown_item_handler(
    request: Any, exc: UnknownItemError
) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ShopError)
async def shop_error_handler(request: Any, exc: ShopError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(GameError)
async def game_error_handler(request: Any, exc: GameError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(MatchmakingError)
async def matchmaking_error_handler(
    request: Any, exc: MatchmakingError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Any, exc: Exception) -> JSONResponse:
    """Har qanday kutilmagan xatoni stack-trace bilan jurnalga yozadi."""
    metrics.error()
    logger.exception(
        "Ushlay olmagan xatolik: %s %s",
        getattr(request, "method", "?"),
        getattr(getattr(request, "url", None), "path", "?"),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500, content={"detail": "Serverda ichki xatolik yuz berdi"}
    )


def manager() -> GameManager:
    return get_default_manager()


def _record_finished_room(room: GameRoom) -> None:
    """FINISHED xonani statistika uchun bir marta qayd etadi."""
    if room.status is not RoomStatus.FINISHED:
        return
    try:
        get_economy().record_finished_game(
            room.code,
            room.players.keys(),
            [player.user_id for player in room.alive_players],
        )
    except Exception:
        logger.exception("Tugagan o'yin natijasini saqlab bo'lmadi: %s", room.code)


async def _notify_shield_offer(room: GameRoom) -> None:
    bot = _runtime_bot
    if bot is not None and room.pending_shield is not None:
        await send_shield_offer(bot, room)


def _schedule_shield_offer(room: GameRoom) -> None:
    if _runtime_bot is None or room.pending_shield is None:
        return
    task = asyncio.create_task(_notify_shield_offer(room))
    task.add_done_callback(
        lambda finished: finished.exception()
        if not finished.cancelled()
        else None
    )


# ----------------------------------------------------------------------
# Umumiy navbat (matchmaking)
# ----------------------------------------------------------------------
def _bot_username() -> str:
    """Bot username'ini sozlamadan yoki muhitdan oladi.

    ``BOT_TOKEN`` yo'q muhitda (masalan lokal test) sozlama o'qish xato
    beradi, shuning uchun muhit qiymatiga qaytamiz.
    """
    try:
        username = get_config().bot_username
    except Exception:
        username = ""
    return (username or os.getenv("BOT_USERNAME") or "revilend_gamesbot").strip().lstrip("@")


def _startapp_url(game_type: str, code: str) -> str:
    """Bot ichidagi Mini App havolasi."""
    bot_username = _bot_username()
    if game_type == "bunker":
        return f"https://t.me/{bot_username}?startapp={code}"
    return f"https://t.me/{bot_username}?startapp={game_type}_{code}"


def _bunker_room_or_none(code: str) -> Any:
    """Bunker xonasini xavfsiz qaytaradi (boshqa o'yinlar uchun ``None``)."""
    try:
        return manager().get_room(code)
    except Exception:
        return None


def _chat_access(code: str, user_id: int) -> ChatAccess | None:
    """Xona turini aniqlab, chat qoidalari uchun kontekst qaytaradi."""
    normalized = (code or "").strip().upper()
    if not normalized:
        return None
    uid = int(user_id or 0)

    room = _bunker_room_or_none(normalized)
    if room is not None:
        player = room.players.get(uid) if uid else None
        return ChatAccess(
            game_type="bunker",
            name=getattr(player, "full_name", "") if player else "",
            is_member=player is not None,
            is_alive=bool(player is not None and player.is_alive),
            is_host=bool(player is not None and player.is_host),
        )

    try:
        game = mafia_bot.get_default_manager().get_game(normalized)
    except Exception:
        game = None
    if game is not None:
        player = game.room.players.get(uid) if uid else None
        is_mafia = bool(
            player is not None
            and player.role in (MafiaRole.DON, MafiaRole.MAFIA)
        )
        return ChatAccess(
            game_type="mafia",
            name=getattr(player, "name", "") if player else "",
            is_member=player is not None,
            is_alive=bool(player is not None and player.is_alive),
            is_mafia=is_mafia,
            is_night=game.room.phase is GamePhase.NIGHT,
            is_host=game.host_id == uid,
        )

    try:
        spy_room = get_spyfall_manager().get_room(normalized)
    except Exception:
        spy_room = None
    if spy_room is not None:
        player = spy_room.players.get(uid) if uid else None
        name = getattr(player, "name", "") if player else ""
        return ChatAccess(
            game_type="spyfall",
            name=name or "",
            is_member=player is not None,
            is_alive=player is not None,
            is_host=spy_room.host_id == uid,
        )

    try:
        alias_room = get_alias_manager().get_room(normalized)
    except Exception:
        alias_room = None
    if alias_room is not None:
        player = alias_room.players.get(uid) if uid else None
        name = getattr(player, "name", "") if player else ""
        return ChatAccess(
            game_type="alias",
            name=name or "",
            is_member=player is not None,
            is_alive=player is not None,
            is_host=alias_room.host_id == uid,
        )
    return None


chat_hub = ChatHub(_chat_access)


async def _handle_socket_payload(
    websocket: WebSocket, code: str, user_id: int | None, raw: str
) -> None:
    """WebSocket'dan kelgan chat xabarini qayta ishlaydi."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return
    if not isinstance(payload, dict) or payload.get("type") != "chat":
        return
    if user_id is None:
        await websocket.send_json(
            {
                "type": "chat-error",
                "message": "Xabarni yuborish uchun user_id kerak",
                "locked": True,
            }
        )
        return
    try:
        await chat_hub.post(code, int(user_id), str(payload.get("text") or ""))
    except ChatError as exc:
        access = _chat_access(code, int(user_id))
        locked = bool(access is None or chat_hub.locked(code, int(user_id), access))
        await websocket.send_json(
            {"type": "chat-error", "message": str(exc), "locked": locked}
        )


MATCH_CHECK_INTERVAL = 20.0


async def _matchmaking_watch() -> None:
    """Bazadagi navbatni muntazam tekshiradi (qayta ishga tushishdan keyin ham)."""
    while True:
        try:
            await asyncio.to_thread(check_and_create_matches)
        except Exception:
            logger.exception("Navbatni tekshirib bo'lmadi")
        await asyncio.sleep(MATCH_CHECK_INTERVAL)


def _create_match_room(
    game_type: str, players: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Navbatdagi o'yinchilar uchun umumiy xona ochadi."""
    if not players:
        return None
    host = players[0]
    host_id = int(host.get("user_id") or 0)
    host_name = str(host.get("name") or "") or f"ID {host_id}"
    host_username = str(host.get("username") or "")

    if game_type == "bunker":
        room = manager().create_room(host_id, host_name, host_username)
        code = room.code
        for entry in players[1:]:
            try:
                manager().join_room(
                    code,
                    int(entry.get("user_id") or 0),
                    str(entry.get("name") or ""),
                    str(entry.get("username") or ""),
                )
            except Exception:
                logger.exception("Navbat o'yinchisini Bunker xonasiga qo'shib bo'lmadi")
    elif game_type == "mafia":
        lobby = mafia_bot.get_default_manager()
        code = lobby.create_game(0, host_id, host_name, host_username).code
        for entry in players[1:]:
            try:
                lobby.join(
                    code,
                    int(entry.get("user_id") or 0),
                    str(entry.get("name") or ""),
                    str(entry.get("username") or ""),
                )
            except Exception:
                logger.exception("Navbat o'yinchisini Mafiya xonasiga qo'shib bo'lmadi")
    elif game_type == "spyfall":
        lobby = get_spyfall_manager()
        code = lobby.create_room(host_id, host_name).code
        for entry in players[1:]:
            try:
                lobby.join(code, int(entry.get("user_id") or 0), str(entry.get("name") or ""))
            except Exception:
                logger.exception("Navbat o'yinchisini Josus xonasiga qo'shib bo'lmadi")
    elif game_type == "alias":
        lobby = get_alias_manager()
        code = lobby.create_room(0, host_id, host_name, host_username).code
        for entry in players[1:]:
            try:
                lobby.join(
                    code,
                    int(entry.get("user_id") or 0),
                    str(entry.get("name") or ""),
                    str(entry.get("username") or ""),
                )
            except Exception:
                logger.exception("Navbat o'yinchisini Alias xonasiga qo'shib bo'lmadi")
    else:  # pragma: no cover - normalize_game_type buni to'sadi
        raise MatchmakingError(f"Noma'lum o'yin turi: {game_type}")

    return {
        "game_type": game_type,
        "code": code,
        "join_url": _startapp_url(game_type, code),
        "players": len(players),
    }


async def _send_match_messages(
    players: list[dict[str, Any]], match: dict[str, Any]
) -> None:
    """Navbatdagi o'yinchilarga Mini App havolasini shaxsiy xabarda yuboradi."""
    bot = _runtime_bot
    if bot is None:
        return
    await matchmaking_bot.send_match_notices(bot, players, match)


def _notify_match(players: list[dict[str, Any]], match: dict[str, Any]) -> None:
    """Navbat to'lganda bildirishnomani fonda yuboradi."""
    if _runtime_bot is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.info("Navbat bildirishnomasi uchun hodisa sikli yo'q")
        return
    task = loop.create_task(_send_match_messages(players, match))
    task.add_done_callback(
        lambda finished: None if finished.cancelled() else finished.exception()
    )


MATCH_TITLES = {
    "bunker": "Bunker",
    "mafia": "Mafiya",
    "spyfall": "Josus",
    "alias": "Alias",
}


@app.exception_handler(TournamentError)
async def tournament_error_handler(
    request: Any, exc: TournamentError
) -> JSONResponse:
    """Turnir xatolarini tegishli HTTP statusga aylantiradi."""
    if isinstance(exc, TournamentNotFoundError):
        status = 404
    elif isinstance(exc, EntryFeeError):
        status = 402
    else:
        status = 400
    return JSONResponse(status_code=status, content={"detail": str(exc)})


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "game_type": GAME_TYPE,
        "supabase": "on" if get_store().enabled else "off",
    }


@app.get("/api/games")
async def list_games() -> dict[str, Any]:
    """Mavjud o'yinlar ro'yxati."""
    return {"games": GAMES}


def shop_meta() -> dict[str, Any]:
    """Mini App do'koni uchun paketlar, karta va bot havolasi.

    Karta raqami admin panel orqali saqlanadigan ``system_settings``dan olinadi.
    """
    card_number, card_holder = get_settings_store().payment_card()
    return {
        "packages": [
            {"coins": coins, "price": price}
            for coins, price in COIN_PACKAGES.items()
        ],
        "card_number": card_number,
        "card_holder": card_holder,
        "bot_username": (os.getenv("BOT_USERNAME") or "revilend_gamesbot")
        .strip()
        .lstrip("@"),
    }


@app.get("/api/shop")
async def get_shop() -> dict[str, Any]:
    """Tanga paketlari va to'lov kartasi (ochiq ma'lumot)."""
    return {"shop": shop_meta(), "boosters": boosters_payload()}


class ShopBuyRequest(BaseModel):
    """Do'kondan buyum sotib olish so'rovi."""

    item_slug: str
    quantity: int = 1
    user_id: int | None = None


class SpinRequest(BaseModel):
    """Omad ğildiragini aylantiriş so'rovi."""

    user_id: int | None = None


class EquipRequest(BaseModel):
    """Ramka yoki unvonni taqiş/yeçiş so'rovi."""

    item_slug: str
    equip: bool = True
    user_id: int | None = None


@app.get("/api/shop/items")
async def shop_items(
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Bölumlar bo'yicha buyumlar, inventar va ğildirak sektorlari."""
    viewer_id = user.id if user is not None else user_id
    payload = get_shop_store().items_payload(viewer_id)
    payload["shop"] = shop_meta()
    payload["boosters"] = boosters_payload()
    return payload


@app.post("/api/shop/buy")
async def shop_buy(
    payload: ShopBuyRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Buyumni tangalarga sotib oladi va inventarga qo'shadi."""
    resolved_id = resolve_user_id(user, payload.user_id)
    metrics.user(resolved_id)
    result = get_shop_store().buy(resolved_id, payload.item_slug, payload.quantity)
    data = result.as_dict()
    data["inventory"] = [entry.as_dict() for entry in get_shop_store().inventory(resolved_id)]
    data["equipped"] = get_shop_store().equipped(resolved_id)
    return data


@app.post("/api/spin/wheel")
async def spin_wheel(
    payload: SpinRequest | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Omad ğildiragini aylantiradi (kuniga bir bepul)."""
    resolved_id = resolve_user_id(user, payload.user_id if payload else None)
    metrics.user(resolved_id)
    store = get_shop_store()
    result = store.spin(resolved_id)
    data = result.as_dict()
    data["spin"] = store.spin_status(resolved_id)
    data["inventory"] = [entry.as_dict() for entry in store.inventory(resolved_id)]
    return data


@app.post("/api/profile/equip")
async def equip_item(
    payload: EquipRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Sotib olingan ramka yoki unvonni profilga taqadi yoki yeçadi."""
    resolved_id = resolve_user_id(user, payload.user_id)
    result = get_shop_store().equip(resolved_id, payload.item_slug, payload.equip)
    result["inventory"] = [
        entry.as_dict() for entry in get_shop_store().inventory(resolved_id)
    ]
    return result


class TournamentJoinRequest(BaseModel):
    """Turnirga yozilish so'rovi."""

    tournament_id: str
    user_id: int | None = None


@app.get("/api/tournaments/active")
async def tournaments_active(
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Ro'yxatga olish ochiq turnirlar: sovrin, vaqt va qatnaşçilar."""
    viewer_id = user.id if user is not None else user_id
    return get_tournament_store().payload(viewer_id)


@app.post("/api/tournaments/join")
async def tournaments_join(
    payload: TournamentJoinRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Turnirga yoziladi: 50 tanga yoki turnir çiptasi."""
    resolved_id = resolve_user_id(user, payload.user_id)
    metrics.user(resolved_id)
    account = get_economy().ensure_user(
        resolved_id,
        user.username if user is not None else "",
        user.full_name if user is not None else "",
    )
    result = get_tournament_store().join(
        resolved_id,
        payload.tournament_id,
        account.username,
        account.full_name,
    )
    data = result.as_dict()
    data["coins"] = result.account.coins
    data["tickets"] = get_shop_store().entry(
        resolved_id, "tournament_ticket"
    ).quantity
    return data


class AdminBalanceRequest(BaseModel):
    """Admin tomonidan balansni töğrilash so'rovi."""

    user_id: int
    coins: int
    reason: str = ""
    admin_id: int | None = None


class AdminTournamentRequest(BaseModel):
    """Admin tomonidan yangi turnir oçiş so'rovi."""

    game: str = "mixed"
    starts_at: str
    entry_fee: int = 50
    prize_pool: int = 2_000
    title: str = ""
    admin_id: int | None = None


def require_admin(user: TelegramUser | None, admin_id: int | None) -> int:
    """Admin endpointlari uchun identifikatsiya va ruxsatni tekşiradi."""
    from bot.handlers.admin import is_admin

    identifier = user.id if user is not None else admin_id
    if identifier is None:
        raise HTTPException(
            status_code=401, detail="Admin identifikatsiyasi talab qilinadi"
        )
    if not is_admin(int(identifier)):
        raise HTTPException(
            status_code=403, detail="Bu amal faqat administrator uçun"
        )
    return int(identifier)


@app.get("/api/admin/payments/pending")
async def admin_pending_payments(
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Tasdiqlashni kutayotgan tölov çeklari."""
    require_admin(user, user_id)
    payments = get_economy().list_pending_payments()
    return {"payments": [asdict(payment) for payment in payments]}


@app.post("/api/admin/payments/{request_id}/approve")
async def admin_approve_payment(
    request_id: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Çekni tasdiqlaydi va tangalarni hisobga qöşadi."""
    admin = require_admin(user, user_id)
    payment = get_economy().approve_payment(request_id, admin)
    return {"ok": True, "payment": asdict(payment)}


@app.post("/api/admin/payments/{request_id}/reject")
async def admin_reject_payment(
    request_id: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Çekni rad etadi."""
    admin = require_admin(user, user_id)
    payment = get_economy().reject_payment(request_id, admin)
    return {"ok": True, "payment": asdict(payment)}


@app.post("/api/admin/balance")
async def admin_balance(
    payload: AdminBalanceRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Balansni qölda töğrilaydi (musbat — qöşiş, manfiy — yeçiş)."""
    require_admin(user, payload.admin_id)
    economy = get_economy()
    if payload.coins >= 0:
        account = economy.add_coins(payload.user_id, int(payload.coins))
    else:
        account = economy.spend_coins(payload.user_id, abs(int(payload.coins)))
    return {"ok": True, "user": asdict(account), "reason": payload.reason}


@app.post("/api/admin/tournaments")
async def admin_create_tournament(
    payload: AdminTournamentRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Yangi haftalik turnir oçadi."""
    admin = require_admin(user, payload.admin_id)
    tournament = get_tournament_store().create(
        payload.game,
        payload.starts_at,
        entry_fee=payload.entry_fee,
        prize_pool=payload.prize_pool,
        title=payload.title,
        created_by=admin,
    )
    return {"ok": True, "tournament": tournament.as_dict()}


def profile_identity(
    user: TelegramUser | None,
    user_id: int | None,
    username: str = "",
    full_name: str = "",
) -> tuple[int, str, str]:
    """Profil uchun foydalanuvchini aniqlaydi.

    Imzolangan ``initData`` ustuvor; u bo'lmasa (masalan botning pastki
    klaviaturasidan ochilganda) ``user_id`` query parametri ishlatiladi.
    Ikkisi ham bo'lmasa 401 qaytaradi.
    """
    if user is not None:
        return user.id, user.username, user.full_name
    if user_id is not None:
        return int(user_id), (username or "").strip(), (full_name or "").strip()
    raise HTTPException(
        status_code=401,
        detail="Telegram initData yoki user_id talab qilinadi",
    )


@app.get("/api/me")
async def my_profile(
    user_id: int | None = None,
    username: str = "",
    full_name: str = "",
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Profil: tangalar va statistika.

    ``initData`` bo'lmasa ham ``user_id`` bilan ishlaydi, shuning uchun
    botning pastki klaviaturasidan kirilganda ham haqiqiy balans ko'rinadi.
    """
    resolved_id, resolved_username, resolved_name = profile_identity(
        user, user_id, username, full_name
    )
    economy = get_economy()
    account = economy.ensure_user(
        resolved_id, resolved_username, resolved_name
    )
    metrics.user(resolved_id)
    shop_store = get_shop_store()
    return {
        "user": asdict(account),
        "shop": shop_meta(),
        "boosters": boosters_payload(),
        # Mega Store: taqilgan ramka/unvon, inventar va ğildirak holati.
        "equipped": shop_store.equipped(resolved_id),
        "inventory": [
            entry.as_dict() for entry in shop_store.inventory(resolved_id)
        ],
        "spin": shop_store.spin_status(resolved_id),
        # Profilda oxirgi 5 o'yin natijasi ko'rsatiladi.
        "history": economy.history_for_user(resolved_id, 5),
    }
    


def _login_user_id(payload: LoginRequest) -> int | None:
    """So'rovdan foydalanuvchi id'sini ajratadi (kod ustuvor)."""
    if payload.code:
        return verify_login_code(payload.code)
    if payload.user_id is not None:
        return int(payload.user_id)
    raw = (payload.login or "").strip()
    if not raw.isdigit():
        return None
    # 6 xonali qiymat avval kod sifatida sinaladi, keyin Telegram ID.
    if len(raw) == 6:
        resolved = verify_login_code(raw)
        if resolved is not None:
            return resolved
    return int(raw)


@app.post("/api/auth/login")
async def login(payload: LoginRequest) -> dict[str, Any]:
    """6 xonali kod yoki Telegram ID orqali Mini App profilini qaytaradi."""
    resolved_id = _login_user_id(payload)
    if resolved_id is None or resolved_id <= 0:
        raise HTTPException(
            status_code=401,
            detail="Kirish kodi noto'g'ri yoki muddati tugagan",
        )
    economy = get_economy()
    if not economy.has_user(resolved_id):
        raise HTTPException(
            status_code=404,
            detail="Foydalanuvchi topilmadi. Avval botda /start bosing.",
        )
    account = economy.ensure_user(resolved_id)
    return {"ok": True, "user": asdict(account)}


def account_display_name(account: Any) -> str:
    """Reyting jadvalida ko'rsatiladigan ism."""
    name = (account.full_name or "").strip()
    if name:
        return name
    username = (account.username or "").strip()
    if username:
        return username
    return f"ID {account.user_id}"


def account_rank(accounts: list[Any], account: Any) -> int:
    """Reyting qoidasi bo'yicha o'yinchining o'rnini hisoblaydi."""
    target = (player_rating(account), account.coins)
    better = sum(
        1 for item in accounts if (player_rating(item), item.coins) > target
    )
    return better + 1


def leaderboard_row(
    account: Any, rank: int, viewer_id: int | None
) -> dict[str, Any]:
    return {
        "rank": rank,
        "user_id": account.user_id,
        "name": account_display_name(account),
        "username": account.username,
        "rating": player_rating(account),
        "coins": account.coins,
        "wins": account.wins,
        "games_played": account.games_played,
        "is_me": viewer_id is not None and account.user_id == int(viewer_id),
    }


@app.get("/api/bonus")
async def bonus_status(
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Kunlik bonus holati: mavjudmi, miqdori va qolgan vaqt.

    O'qish endpointi bo'lgani uchun ``user_id`` initData'siz ham qabul
    qilinadi (bonusni olish — POST — esa imzo talab qiladi).
    """
    resolved_id, _, _ = profile_identity(user, user_id)
    economy = get_economy()
    return {
        "bonus": asdict(economy.daily_bonus_status(resolved_id)),
        "coins": economy.get_user(resolved_id).coins,
    }


@app.post("/api/bonus")
async def bonus_claim(
    payload: UserRequest | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Kunlik bonusni oladi (har 24 soatda bir marta)."""
    resolved_id = resolve_user_id(user, payload.user_id if payload else None)
    economy = get_economy()
    claim = economy.claim_daily_bonus(resolved_id)
    return {
        "ok": True,
        "amount": claim.amount,
        "streak": claim.streak,
        "coins": claim.account.coins,
        "bonus": asdict(economy.daily_bonus_status(resolved_id)),
    }


@app.get("/api/missions")
async def my_missions(
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Foydalanuvchining missiyalari va taraqqiyoti."""
    resolved_id = resolve_user_id(user, user_id)
    economy = get_economy()
    statuses = mission_statuses(economy, resolved_id)
    return {
        "missions": missions_payload(statuses),
        "coins": economy.get_user(resolved_id).coins,
    }


@app.post("/api/missions/{mission_key}/claim")
async def claim_my_mission(
    mission_key: str,
    payload: UserRequest | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Bajarilgan missiya mukofotini beradi."""
    resolved_id = resolve_user_id(user, payload.user_id if payload else None)
    economy = get_economy()
    status, account = claim_mission(economy, resolved_id, mission_key)
    return {
        "ok": True,
        "mission": missions_payload([status])[0],
        "coins": account.coins,
    }


@app.post("/api/promo")
async def redeem_promo_code(
    payload: PromoCodeRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Promo kodni ishlatib, tanga oladi."""
    resolved_id = resolve_user_id(user, payload.user_id)
    result = get_economy().redeem_promo_code(resolved_id, payload.code)
    return {
        "ok": True,
        "code": result.code,
        "amount": result.coins,
        "coins": result.account.coins,
    }


@app.get("/api/top")
async def top_players(
    limit: int = 10,
    period: str = "all",
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Reyting jadvali: barcha davrlar yoki joriy haftalik liga."""
    limit = max(1, min(int(limit), 50))
    viewer_id = user.id if user is not None else user_id
    board = build_leaderboard(
        period, limit, viewer_id, economy=get_economy()
    )
    board["period"] = normalize_period(period)
    if board.get("me") is not None:
        board["me"]["in_top"] = int(board["me"].get("rank") or 0) <= limit
    return board


@app.get("/api/league")
async def weekly_league(
    limit: int = 10,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Joriy haftalik liga: o'yin va g'alaba ballari."""
    limit = max(1, min(int(limit), 50))
    viewer_id = user.id if user is not None else user_id
    return {"league": get_economy().weekly_league(limit=limit, viewer_id=viewer_id)}


@app.get("/api/history")
async def game_history(
    limit: int = 10,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Foydalanuvchining oxirgi o'yinlari."""
    resolved_id = resolve_user_id(user, user_id)
    metrics.user(resolved_id)
    return {"history": get_economy().history_for_user(resolved_id, limit)}


class MatchmakingJoinRequest(BaseModel):
    """Navbatga qo'shilish so'rovi."""

    game_type: str
    user_id: int | None = None
    name: str = ""
    username: str = ""


class MatchmakingLeaveRequest(BaseModel):
    """Navbatdan chiqish so'rovi."""

    game_type: str | None = None
    user_id: int | None = None


@app.get("/api/matchmaking")
async def matchmaking_status(
    game_type: str | None = None,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Navbat holati: nechta kishi qidirilmoqda va qancha kerak."""
    kind = normalize_game_type(game_type) if game_type else None
    payload = get_matchmaker().status(kind)
    viewer_id = user.id if user is not None else user_id
    if viewer_id is not None:
        if kind is not None:
            payload["position"] = get_matchmaker().position(int(viewer_id), kind)
        # Navbat to'lganini boshqa ishtirokchilar ham polling orqali biladi.
        payload["match"] = get_matchmaker().recent_match(int(viewer_id), kind)
    return payload


@app.post("/api/matchmaking/join")
async def matchmaking_join(
    payload: MatchmakingJoinRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """O'yinchini global navbatga qo'shadi."""
    resolved_id = resolve_user_id(user, payload.user_id)
    metrics.user(resolved_id)
    name = payload.name
    username = payload.username
    if user is not None:
        name = name or user.full_name
        username = username or user.username
    result = get_matchmaker().join(
        resolved_id, payload.game_type, name=name, username=username
    )
    return {"ok": True, **result}


@app.post("/api/matchmaking/leave")
async def matchmaking_leave(
    payload: MatchmakingLeaveRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """O'yinchini navbatdan chiqaradi."""
    resolved_id = resolve_user_id(user, payload.user_id)
    result = get_matchmaker().leave(resolved_id, payload.game_type)
    return {"ok": True, **result}


@app.get("/api/lobbies")
async def open_lobbies(limit: int = 20, q: str = "") -> dict[str, Any]:
    """Barcha o'yinlar bo'yicha global ochiq lobby qidiruvi."""
    limit = max(1, min(int(limit), 50))
    needle = (q or "").strip().lower()
    bot_username = _bot_username()
    rows: list[dict[str, Any]] = []

    for room in manager().open_rooms(limit):
        host = room.players.get(room.host_id)
        rows.append(
            {
                "game_type": "bunker",
                "game_name": "Bunker",
                "code": room.code,
                "host_name": (host.full_name or host.username) if host else "",
                "players": len(room.players),
                "max_players": room.max_players,
                "need": max(0, 2 - len(room.players)),
                "join_url": f"https://t.me/{bot_username}?startapp={room.code}",
            }
        )

    for game in mafia_bot.get_default_manager().open_games(limit):
        host = game.room.players.get(game.host_id)
        rows.append(
            {
                "game_type": "mafia",
                "game_name": "Mafiya",
                "code": game.code,
                "host_name": host.name if host else "",
                "players": len(game.room.players),
                "max_players": mafia_bot.MAX_PLAYERS,
                "need": max(0, mafia_bot.MIN_PLAYERS - len(game.room.players)),
                "join_url": f"https://t.me/{bot_username}?startapp=mafia_{game.code}",
            }
        )

    for room in get_spyfall_manager().open_rooms(limit):
        host = room.players.get(room.host_id)
        rows.append(
            {
                "game_type": "spyfall",
                "game_name": "Josus",
                "code": room.code,
                "host_name": host.display_name() if host else "",
                "players": len(room.players),
                "max_players": 12,
                "need": max(0, 3 - len(room.players)),
                "join_url": f"https://t.me/{bot_username}?startapp=spy_{room.code}",
            }
        )

    if needle:
        rows = [
            row
            for row in rows
            if needle in row["code"].lower()
            or needle in row["game_name"].lower()
            or needle in row["host_name"].lower()
        ]
    return {"lobbies": rows[:limit], "total": len(rows)}


@app.get("/api/metrics")
async def monitoring_metrics(
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Admin uchun monitoring ko'rsatkichlari."""
    economy = get_economy()
    if user is None or not (
        (get_config().admin_id and user.id == get_config().admin_id)
        or economy.is_admin_user(user.id)
    ):
        raise HTTPException(status_code=403, detail="Faqat administrator uchun")
    return {
        "metrics": asdict(metrics.snapshot()),
        "matchmaking": get_matchmaker().stats(),
        "cleanup": get_cleaner().stats(),
    }


@app.get("/api/meta/cards")
async def meta_cards() -> dict[str, Any]:
    """Karta turlarining yorliqlari."""
    return {"card_types": card_type_options()}


def mafia_me_payload(
    game: mafia_bot.MafiaGame,
    player: Any,
    *,
    economy: Any | None = None,
) -> dict[str, Any]:
    """Mini App uchun Mafiya o'yinchisi holati."""
    economy = economy or get_economy()
    profile = (
        get_role_profile(player.role) if player.role is not None else None
    )

    teammates: list[dict[str, Any]] = []
    if profile is not None and profile.faction is Faction.MAFIA:
        for other in game.room.players.values():
            if other.user_id == player.user_id or other.role is None:
                continue
            other_profile = get_role_profile(other.role)
            if other_profile.faction is not Faction.MAFIA:
                continue
            teammates.append(
                {
                    "user_id": other.user_id,
                    "full_name": other.name or f"ID {other.user_id}",
                    "role": other_profile.role.value,
                    "role_name": other_profile.name_uz,
                    "is_alive": other.is_alive,
                }
            )

    options = booster_options(
        game.room, game.code, economy, player.user_id
    )
    deadline = game.phase_deadline
    try:
        coins = economy.get_user(player.user_id).coins
    except Exception:
        coins = 0
    return {
        "code": game.code,
        "user_id": player.user_id,
        "full_name": player.name,
        "is_alive": player.is_alive,
        "is_host": player.user_id == game.host_id,
        "role": profile.role.value if profile else None,
        "role_name": (
            profile.name_uz if profile else "Rol hali tarqatilmagan"
        ),
        "description": (
            profile.description
            if profile
            else "O'yin boshlangach, rolingiz shu yerda ochiladi."
        ),
        "faction": profile.faction.value if profile else None,
        "has_night_action": (
            profile.has_night_action if profile else False
        ),
        "photo": (
            role_image_url(profile.role)
            if profile
            else f"/assets/images/mafia/{COVER_IMAGE}"
        ),
        "phase": game.room.phase.value,
        "round": game.room.round,
        "players_count": len(game.room.players),
        "phase_deadline": deadline,
        "phase_duration": game.phase_duration,
        "phase_seconds_left": (
            max(0, int(round(deadline - time.time())))
            if deadline is not None
            else 0
        ),
        "server_time": time.time(),
        "coins": coins,
        "teammates": teammates,
        "boosters": [
            {
                "key": option.booster.key,
                "name": option.booster.name,
                "emoji": option.booster.emoji,
                "price": option.booster.price,
                "description": option.booster.description,
                "used": option.used,
                "active": option.active,
                "available": option.available,
                "reason": option.reason,
            }
            for option in options
        ],
        "winner": (
            game.room.winner.value
            if game.room.winner is not None
            else None
        ),
    }


def _mafia_game_for(code: str) -> mafia_bot.MafiaGame:
    """Kod bo'yicha xonani qaytaradi yoki 404 beradi."""
    try:
        return mafia_bot.get_default_manager().get_game(code)
    except mafia_bot.MafiaGameError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/mafia/{code}/join")
async def join_mafia_lobby(
    code: str,
    payload: JoinRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Global qidiruvdan Mafiya lobby'siga qo'shilish."""
    resolved_id = resolve_room_user_id(user, payload.user_id)
    full_name = (
        (user.full_name if user is not None else "") or payload.full_name or ""
    ).strip()
    username = (
        (user.username if user is not None else "") or payload.username or ""
    ).strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="full_name majburiy")
    economy = get_economy()
    economy.ensure_user(resolved_id, username, full_name)
    try:
        player = mafia_bot.get_default_manager().join(
            code, resolved_id, full_name, username
        )
        game = mafia_bot.get_default_manager().get_game(code)
    except mafia_bot.MafiaGameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metrics.user(resolved_id)
    await chat_hub.system(code, f"{full_name} xonaga qo'shildi")
    return {"ok": True, "me": mafia_me_payload(game, player, economy=economy)}


@app.get("/api/mafia/{code}/me")
async def get_mafia_role(
    code: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Guruh Mafiya o'yinidagi o'yinchining roli va karta ma'lumoti."""
    resolved_id = resolve_room_user_id(user, user_id)
    game = _mafia_game_for(code)
    player = game.room.players.get(resolved_id)
    if player is None:
        raise HTTPException(
            status_code=404, detail="Siz bu Mafiya xonasida emassiz"
        )
    return {"me": mafia_me_payload(game, player)}


@app.post("/api/mafia/{code}/booster")
async def buy_mafia_booster(
    code: str,
    payload: MafiaBoosterRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Mafiya boosterini sotib oladi (Kevlar, Reroll yoki 2x ovoz)."""
    resolved_id = resolve_room_user_id(user, payload.user_id)
    game = _mafia_game_for(code)
    player = game.room.players.get(resolved_id)
    if player is None:
        raise HTTPException(
            status_code=404, detail="Siz bu Mafiya xonasida emassiz"
        )

    economy = get_economy()
    try:
        purchase = purchase_booster(
            economy,
            game.room,
            game.code,
            resolved_id,
            payload.booster,
        )
    except MafiaBoosterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "ok": True,
        "booster": purchase.booster.key,
        "message": purchase.message,
        "coins": purchase.account.coins,
        "me": mafia_me_payload(game, player, economy=economy),
    }



@app.get("/api/mafia/{code}/state")
async def get_mafia_public_state(
    code: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Mafiya Mini App uchun maxfiy rollarsiz umumiy holat."""
    resolved_id = resolve_room_user_id(user, user_id)
    game = _mafia_game_for(code)
    room = game.room
    viewer = room.players.get(resolved_id)
    if viewer is None:
        raise HTTPException(status_code=403, detail="Siz bu Mafiya xonasida emassiz")

    night_options = ()
    if viewer.role is not None:
        night_options = NIGHT_OPTIONS_BY_ROLE.get(
            viewer.role,
            (NIGHT_ACTION_BY_ROLE[viewer.role],)
            if viewer.role in NIGHT_ACTION_BY_ROLE
            else (),
        )
    action_labels = {
        "kill": "Nishonni tanlash",
        "heal": "Davolash",
        "protect": "Himoya qilish",
        "block": "Harakatini bloklash",
        "snipe": "Nishonga olish",
        "investigate": "Tekshirish",
        "frame": "Tekshiruvdan yashirish",
        "witch_kill": "O'ldirish",
        "witch_heal": "Tiriltirish",
        "silence": "Ovozini bloklash",
        "copy": "Rolini egallash",
    }
    report = room.last_report
    private_result = (
        report.sheriff_results.get(resolved_id)
        if report is not None
        else None
    )
    return {
        "state": {
            "code": game.code,
            "phase": room.phase.value,
            "round": room.round,
            "is_host": resolved_id == game.host_id,
            "is_alive": viewer.is_alive,
            "players": [
                {
                    "user_id": player.user_id,
                    "name": room.display_name(player),
                    "is_alive": player.is_alive,
                    "is_me": player.user_id == resolved_id,
                }
                for player in room.players.values()
            ],
            "night_actions": [
                {"key": action.value, "label": action_labels.get(action.value, action.value)}
                for action in night_options
            ],
            "has_submitted_night_action": resolved_id in room.night_actions,
            "has_voted": resolved_id in room.votes,
            "my_vote_target": room.votes.get(resolved_id),
            "is_silenced": resolved_id in room.silenced,
            "vote_counts": [
                {"user_id": player.user_id, "count": room.vote_counts().get(player.user_id, 0)}
                for player in room.alive_players
            ],
            "can_begin_voting": (
                resolved_id == game.host_id
                and room.phase is GamePhase.DAY_REPORT
            ),
            "can_tally": (
                resolved_id == game.host_id
                and room.phase is GamePhase.VOTING
            ),
            "private_result": private_result,
            "phase_deadline": game.phase_deadline,
            "phase_seconds_left": game.phase_seconds_left(),
            "winner": room.winner.value if room.winner is not None else None,
        }
    }


@app.post("/api/mafia/{code}/night-action")
async def submit_mafia_night_action(
    code: str,
    payload: MafiaNightActionRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Tungi harakatni dvigatel qoidalari orqali yuboradi."""
    resolved_id = resolve_user_id(user, payload.user_id)
    game = _mafia_game_for(code)
    if resolved_id not in game.room.players:
        raise HTTPException(status_code=403, detail="Siz bu Mafiya xonasida emassiz")
    try:
        game.room.submit_night_action(
            resolved_id, payload.target_id, kind=payload.kind
        )
    except MafiaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/mafia/{code}/begin-voting")
async def begin_mafia_voting(
    code: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Tonggi hisobotdan keyin ovoz berishni xona egasi boshlaydi."""
    resolved_id = resolve_room_user_id(user, user_id)
    game = _mafia_game_for(code)
    if resolved_id != game.host_id:
        raise HTTPException(status_code=403, detail="Ovoz berishni faqat xona egasi boshlaydi")
    try:
        game.room.begin_voting()
    except MafiaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game.start_phase_timer()
    return {"ok": True}


@app.post("/api/mafia/{code}/vote")
async def cast_mafia_vote(
    code: str,
    payload: MafiaVoteRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Kunduzgi ovozni yuboradi; qoidalarni dvigatel tekshiradi."""
    resolved_id = resolve_room_user_id(user, payload.user_id)
    game = _mafia_game_for(code)
    try:
        game.room.cast_vote(resolved_id, payload.target_id)
    except MafiaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/mafia/{code}/tally")
async def tally_mafia_votes(
    code: str,
    payload: MafiaTallyRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Ovozlarni xona egasi sanaydi va dvigatel keyingi fazani boshlaydi."""
    resolved_id = resolve_room_user_id(user, payload.user_id)
    game = _mafia_game_for(code)
    if resolved_id != game.host_id:
        raise HTTPException(status_code=403, detail="Ovozlarni faqat xona egasi sanaydi")
    try:
        eliminated_id = game.room.tally_votes()
        if (
            eliminated_id is not None
            and game.room.players[eliminated_id].role is MafiaRole.KAMIKAZE
            and payload.kamikaze_target_id is None
        ):
            raise HTTPException(
                status_code=400,
                detail="Kamikadze haydaldi. U bilan birga ketadigan o'yinchini tanlang.",
            )
        winner = resolve_day_vote(
            game.room,
            eliminated_id,
            kamikaze_target_id=payload.kamikaze_target_id,
        )
    except MafiaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if game.room.phase is GamePhase.FINISHED:
        game.clear_phase_timer()
        if _runtime_bot is not None:
            await mafia_bot.announce_finish(_runtime_bot, game)
    else:
        game.start_phase_timer()
        if _runtime_bot is not None:
            if eliminated_id is not None:
                await mafia_bot.announce_execution(
                    _runtime_bot, game, game.room.players[eliminated_id]
                )
            await mafia_bot.announce_night(_runtime_bot, game)

    return {
        "ok": True,
        "eliminated_id": eliminated_id,
        "winner": winner.value if winner is not None else None,
    }


@app.get("/api/room/{code}")
async def get_room(
    code: str,
    user_id: int = 0,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Xonaning ochiq holati: falokat, raund, ochilgan kartalar."""
    room = manager().get_room(code)
    viewer_id = user.id if user is not None else user_id
    return {"state": public_state(room, viewer_id=viewer_id)}


@app.get("/api/room/{code}/me")
async def get_my_cards(
    code: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """O'yinchining shaxsiy yashirin kartalari."""
    resolved_id = resolve_room_user_id(user, user_id)
    room = manager().get_room(code)
    return {"me": private_state(room, resolved_id)}


@app.post("/api/room/{code}/action")
async def room_action(
    code: str,
    payload: ActionRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Umumiy o'yin harakatlari: qo'shilish, boshlash, ochish, ovoz, sanash."""
    actor_id = resolve_room_user_id(user, payload.user_id)
    full_name = (
        (user.full_name if user is not None else "")
        or payload.full_name
        or ""
    ).strip()
    username = (
        (user.username if user is not None else "")
        or payload.username
        or ""
    ).strip()

    game_manager = manager()
    result: dict[str, Any] | None = None

    if payload.action == "join":
        if not full_name:
            raise HTTPException(status_code=400, detail="full_name majburiy")
        get_economy().ensure_user(actor_id, username, full_name)
        already_inside = actor_id in game_manager.get_room(code).players
        game_manager.join_room(code, actor_id, full_name, username)
        if not already_inside:
            await chat_hub.system(code, f"{full_name} xonaga qo'shildi")
    elif payload.action == "start":
        room = game_manager.get_room(code)
        if room.host_id != actor_id:
            raise HTTPException(
                status_code=403,
                detail="O'yinni faqat xona egasi boshlashi mumkin",
            )
        game_manager.start_game(code)
        await chat_hub.system(code, "O'yin boshlandi. Omad!")
    elif payload.action == "reveal":
        if not payload.card_type:
            raise HTTPException(status_code=400, detail="card_type majburiy")
        game_manager.reveal_card(code, actor_id, payload.card_type)
    elif payload.action == "vote":
        if payload.target_id is None:
            raise HTTPException(status_code=400, detail="target_id majburiy")
        game_manager.cast_vote(code, actor_id, payload.target_id)
    elif payload.action == "tally":
        room = game_manager.get_room(code)
        if room.host_id != actor_id:
            raise HTTPException(
                status_code=403,
                detail="Ovozlarni faqat xona egasi sanaydi",
            )
        eliminated = game_manager.tally_votes(code)
        current = game_manager.get_room(code)
        if eliminated is not None:
            await chat_hub.system(
                code, f"{eliminated.full_name} o'yindan chiqarildi"
            )
        result = {
            "eliminated": (
                {
                    "user_id": eliminated.user_id,
                    "full_name": eliminated.full_name,
                }
                if eliminated is not None
                else None
            ),
            "tie": eliminated is None and current.pending_shield is None,
            "shield_offer": (
                current.pending_shield.model_dump(mode="json")
                if current.pending_shield is not None
                else None
            ),
        }
        _schedule_shield_offer(current)
    elif payload.action == "booster":
        if not payload.booster:
            raise HTTPException(status_code=400, detail="booster majburiy")
        try:
            purchase = buy_booster(
                game_manager,
                get_economy(),
                code,
                actor_id,
                payload.booster,
                payload.card_type,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result = {
            "booster": purchase.booster.key,
            "price": purchase.booster.price,
            "coins": purchase.account_coins,
            "eliminated": (
                {
                    "user_id": purchase.eliminated.user_id,
                    "full_name": purchase.eliminated.full_name,
                }
                if purchase.eliminated is not None
                else None
            ),
            "card": _card_payload(purchase.card) if purchase.card is not None else None,
        }
    elif payload.action == "shield_decline":
        room = game_manager.get_room(code)
        offer = room.pending_shield
        if offer is None or offer.user_id != actor_id:
            raise HTTPException(
                status_code=400,
                detail="Sizda faol qalqon taklifi yo'q",
            )
        _, eliminated = decline_shield(game_manager, code, actor_id)
        result = {
            "eliminated": {
                "user_id": eliminated.user_id,
                "full_name": eliminated.full_name,
            }
        }

    room = game_manager.get_room(code)
    _record_finished_room(room)
    state = public_state(room, viewer_id=actor_id)
    await hub.broadcast(code, {"type": "state", "state": state})
    return {
        "ok": True,
        "state": state,
        "me": private_state(room, actor_id),
        "result": result,
        "coins": get_economy().get_user(actor_id).coins,
    }


@app.websocket("/ws/{code}")
async def room_socket(
    websocket: WebSocket,
    code: str,
    user_id: int | None = None,
) -> None:
    """Xona uchun real-vaqt kanali: holat va jonli chat."""
    normalized = (code or "").strip().upper()
    bunker_room = _bunker_room_or_none(normalized)
    if bunker_room is None and _chat_access(normalized, 0) is None:
        await websocket.close(code=4404)
        return

    bunker_connected = bunker_room is not None
    if bunker_connected:
        await hub.connect(normalized, websocket)
    if user_id is not None:
        await chat_hub.connect(normalized, websocket, int(user_id))
    try:
        if bunker_connected:
            await websocket.send_json(
                {"type": "state", "state": public_state(bunker_room)}
            )
        while True:
            message = await websocket.receive_text()
            stripped = message.strip()
            if stripped == "ping":
                await websocket.send_json({"type": "pong"})
            elif stripped == "sync":
                current = _bunker_room_or_none(normalized)
                if current is not None:
                    await websocket.send_json(
                        {"type": "state", "state": public_state(current)}
                    )
            else:
                await _handle_socket_payload(
                    websocket, normalized, user_id, stripped
                )
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(normalized, websocket)
        await chat_hub.disconnect(normalized, websocket)


# Statik Mini App: avval rasm/fontlar, keyin index.html.
if ASSETS_DIR.is_dir():
    app.mount(
        "/assets", StaticFiles(directory=ASSETS_DIR), name="assets"
    )
if WEBAPP_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEBAPP_DIR, html=True), name="webapp")
