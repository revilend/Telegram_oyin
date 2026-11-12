"""API uchun umumiy sozlamalar, sxemalar va yordamchi funksiyalar.

`api/server.py` faqat ilovani yaratadi; barcha endpointlar `api/routers/`
modullarida. Ular shu moduldan umumiy holat, Pydantic sxemalari va
yordamchilarni oladi (aylanma import bo'lmasligi uchun).
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
    resolve_client_user_id,
    resolve_room_user_id,
    resolve_user_id,
    telegram_user,
)
from games.bomb.api import router as bomb_router
from games.bomb.api import set_runtime_bot as set_bomb_bot
from games.bomb.engine import BombRoom
from games.bomb.manager import get_default_manager as get_bomb_manager
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
from core.daily_backup import start_daily_backup, stop_daily_backup
from core.achievements import achievements_payload
from core.daily_quests import (
    DailyQuestError,
    claim_daily_quest,
    claim_weekly_chest,
    daily_quests_payload,
    record_daily_event,
    reroll_daily_quests,
)
from core.db import get_store
from core.economy import (
    COIN_PACKAGES,
    EconomyError,
    InsufficientCoinsError,
    get_economy,
    player_rating,
)
from core.persistence import (
    ensure_admin_profile,
    ensure_persistence_or_raise,
    persistence_status,
)
from core.login_codes import verify_login_code
from core.shop import (
    CATALOG_BY_SLUG,
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
from games.alias.engine import AliasRoom, get_default_manager as get_alias_manager
from core import room_store
from core.missions import claim_mission, mission_statuses, missions_payload
from core.settings import get_settings_store
from engine.boosters import BoosterError, boosters_payload
from engine import test_bots
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
        "image": "bunkergame.png",
    },
    {
        "slug": "mafia",
        "name": "Mafiya",
        "emoji": "🕵️",
        "status": "active",
        "players": "4–20",
        "description": "Kechki shaharda mafiya va tinch aholi o'rtasidagi sirli "
        "kurash. Guruhda /mafia bilan boshlang.",
        "image": "mafiagame.png",
    },
    {
        "slug": "spyfall",
        "name": "Josus",
        "emoji": "🕶️",
        "status": "active",
        "players": "3–12",
        "description": "Hamma joyni biladi, faqat bitta josus bilmaydi. Savol-javob "
        "orqali uni toping.",
        "image": "spygame.png",
    },
    {
        "slug": "alias",
        "name": "Alias / Krokodil",
        "emoji": "🐊",
        "status": "active",
        "players": "2–20",
        "description": "Tezkor so'z tushuntirish va topish poygasi. Guruhda /alias "
        "bilan boshlang.",
        "image": "aliasgame.png",
    },
    {
        "slug": "bomb",
        "name": "Portlovçi Bomba",
        "emoji": "💣",
        "status": "active",
        "players": "2–8",
        "description": "Karta öyini: bombani zararsizlantir, raqiblarga hujum qil "
        "va oxirgi tirik qol. Guruhda /bomb bilan boshlang.",
        "image": "bombgame.png",
    },
]


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
        "epilogue": list(room.epilogue),
        "epilogue_outcome": room.epilogue_outcome,
        "epilogue_survived": room.epilogue_survived,
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
    # Bunker: yangi JSONB jadvali. Eski rooms/room_players saqlanib qoladi.
    game_manager.set_change_handler(room_store.save_bunker)
    game_manager.set_room_loader(room_store.load_bunker)

    mafia_manager = mafia_bot.get_default_manager()
    mafia_manager.set_change_handler(
        lambda game: room_store.save_state(
            room_store.MAFIA_ROOMS_TABLE, game.code, game.to_state()
        )
    )

    def _load_mafia(code: str) -> mafia_bot.MafiaGame | None:
        state = room_store.load_state(room_store.MAFIA_ROOMS_TABLE, code)
        return mafia_bot.MafiaGame.from_state(state) if state else None

    mafia_manager.set_room_loader(_load_mafia)

    bomb_manager = get_bomb_manager()
    bomb_manager.set_change_handler(
        lambda room: room_store.save_state(
            room_store.BOMB_ROOMS_TABLE, room.code, room.to_state()
        )
    )

    def _load_bomb(code: str) -> BombRoom | None:
        state = room_store.load_state(room_store.BOMB_ROOMS_TABLE, code)
        return BombRoom.from_state(state) if state else None

    bomb_manager.set_room_loader(_load_bomb)

    alias_manager = get_alias_manager()
    alias_manager.set_change_handler(
        lambda room: room_store.save_state(
            room_store.ALIAS_ROOMS_TABLE, room.code, room.to_state()
        )
    )

    def _load_alias(code: str) -> AliasRoom | None:
        state = room_store.load_state(room_store.ALIAS_ROOMS_TABLE, code)
        return AliasRoom.from_state(state) if state else None

    alias_manager.set_room_loader(_load_alias)
    spyfall_manager = get_spyfall_manager()

    for manager_obj in (
        game_manager,
        mafia_manager,
        bomb_manager,
        alias_manager,
        spyfall_manager,
    ):
        sync = getattr(manager_obj, "sync_from_store", None)
        if callable(sync):
            sync()

    logger.info("Supabase saqlash va barcha o'yin xonalarini yuklash yoqilgan")


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
    if not isinstance(payload, dict) or payload.get("type") not in {
        "chat",
        "reaction",
    }:
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
        if payload.get("type") == "reaction":
            await chat_hub.react(code, int(user_id), str(payload.get("emoji") or ""))
        else:
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
    elif game_type == "bomb":
        lobby = get_bomb_manager()
        code = lobby.create_room(host_id, host_name).code
        for entry in players[1:]:
            try:
                lobby.join(code, int(entry.get("user_id") or 0), str(entry.get("name") or ""))
            except Exception:
                logger.exception("Navbat o'yinchisini Bomba xonasiga qo'shib bo'lmadi")
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


class ShopBuyRequest(BaseModel):
    """Do'kondan buyum sotib olish so'rovi.

    Narx faqat backend katalogidan olinadi — mijoz yuborgan ``price``
    ishonchsiz hisoblanib e'tiborsiz qoldiriladi. ``item_id`` ham
    qabul qilinadi (``item_slug`` alias'i).
    """

    item_slug: str = ""
    item_id: str | None = None
    price: int | None = None
    quantity: int = 1
    user_id: int | None = None


class SpinRequest(BaseModel):
    """Omad ğildiragini aylantiriş so'rovi."""

    user_id: int | None = None
    stop_angle: int | None = None


class EquipRequest(BaseModel):
    """Ramka yoki unvonni taqiş/yeçiş so'rovi.

    Mini App ``item_slug`` yuboradi; eski mijozlar uchun ``item_id`` va
    ``item_type`` ham qabul qilinadi.
    """

    item_slug: str = ""
    item_id: str | None = None
    item_type: str | None = None
    equip: bool = True
    user_id: int | None = None


class LanguageRequest(BaseModel):
    """Mini App tilini saqlash so'rovi (``users.language_code``)."""

    language_code: str = ""
    user_id: int | None = None


class TournamentJoinRequest(BaseModel):
    """Turnirga yozilish so'rovi."""

    tournament_id: str
    user_id: int | None = None


class AdminBalanceRequest(BaseModel):
    """Admin tomonidan balansni töğrilash so'rovi."""

    user_id: int
    coins: int
    reason: str = ""
    admin_id: int | None = None


class AdminTournamentRequest(BaseModel):
    """Admin tomonidan yangi turnir oçiş so'rovi."""

    game: str = "mixed"
    game_type: str | None = None
    starts_at: str = ""
    start_time: str | None = None
    entry_fee: int = 50
    prize_pool: int = 2_000
    title: str = ""
    max_participants: int | None = None
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


def _profile_payload(
    resolved_id: int,
    username: str = "",
    full_name: str = "",
    account=None,
) -> dict[str, Any]:
    """/api/me javobi: profil, tangalar, do'kon, inventar va tarix."""
    economy = get_economy()
    if account is None:
        account = economy.ensure_user(resolved_id, username, full_name)
    metrics.user(resolved_id)
    shop_store = get_shop_store()
    return {
        "user": asdict(account),
        "shop": shop_meta(),
        "boosters": boosters_payload(),
        # Mega Store: taqilgan ramka/unvon, inventar va g'ildirak holati.
        "equipped": shop_store.equipped(resolved_id),
        "inventory": [
            entry.as_dict() for entry in shop_store.inventory(resolved_id)
        ],
        "spin": shop_store.spin_status(resolved_id),
        # Profilda oxirgi 5 o'yin natijasi ko'rsatiladi.
        "history": economy.history_for_user(resolved_id, 5),
    }


def _activity_response(
    account,
    statuses,
    all_board: dict[str, Any],
    week_board: dict[str, Any],
    bonus,
    quests: dict[str, Any],
    achievements: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    """/api/activity javobini qo'shimcha so'rovsiz yig'adi."""
    all_board = dict(all_board)
    all_board["period"] = normalize_period("all")
    if all_board.get("me") is not None:
        all_board["me"]["in_top"] = int(all_board["me"].get("rank") or 0) <= limit
    week_board = dict(week_board)
    week_board["period"] = normalize_period("week")
    return {
        "bonus": asdict(bonus),
        "missions": missions_payload(statuses),
        "quests": quests,
        "achievements": achievements,
        "top": all_board.get("top", []),
        "me": all_board.get("me"),
        "week": week_board,
        "coins": account.coins,
    }


def _activity_payload(
    resolved_id: int, limit: int = 10, account=None
) -> dict[str, Any]:
    """/api/activity javobi: bonus, missiyalar, questlar va reyting."""
    economy = get_economy()
    if account is None:
        account = economy.ensure_user(resolved_id)
    return _activity_response(
        account,
        mission_statuses(economy, resolved_id, account=account),
        build_leaderboard("all", limit, resolved_id, economy=economy),
        build_leaderboard("week", limit, resolved_id, economy=economy),
        economy.daily_bonus_status(resolved_id),
        daily_quests_payload(economy, resolved_id),
        achievements_payload(economy, resolved_id),
        limit,
    )


async def _activity_payload_async(
    resolved_id: int, limit: int = 10, account=None
) -> dict[str, Any]:
    """``_activity_payload`` bilan bir xil javob, lekin o'qishlar parallel.

    Bonus, missiyalar, questlar, yutuqlar va ikkala reyting bir-biriga bog'liq
    emas, shuning uchun ular ``asyncio.gather`` bilan birga yuboriladi:
    Supabase 100-150 ms kechikishda bu ~6 ketma-ket so'rov o'rniga 2-3 round.
    """
    economy = get_economy()
    if account is None:
        account = await asyncio.to_thread(economy.ensure_user, resolved_id)
    (
        statuses,
        all_board,
        week_board,
        bonus,
        quests,
        achievements,
    ) = await asyncio.gather(
        asyncio.to_thread(
            mission_statuses, economy, resolved_id, account=account
        ),
        asyncio.to_thread(
            build_leaderboard, "all", limit, resolved_id, economy=economy
        ),
        asyncio.to_thread(
            build_leaderboard, "week", limit, resolved_id, economy=economy
        ),
        asyncio.to_thread(economy.daily_bonus_status, resolved_id),
        asyncio.to_thread(daily_quests_payload, economy, resolved_id),
        asyncio.to_thread(achievements_payload, economy, resolved_id),
    )
    return _activity_response(
        account,
        statuses,
        all_board,
        week_board,
        bonus,
        quests,
        achievements,
        limit,
    )


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


class TestBotsFillRequest(BaseModel):
    """Test rejimida xonani botlar bilan to'ldirish so'rovi."""

    game_type: str
    code: str


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


# Routerlar ``from api.deps import *`` bilan barcha nomlarni oladi;
# pastki chiziqli yordamchilar ham ko'rinishi uchun ro'yxat dinamik.
__all__ = sorted(name for name in globals() if not name.startswith("__"))
