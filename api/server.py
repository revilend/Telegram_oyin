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
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api.auth import TelegramUser, resolve_user_id, telegram_user
from bot.handlers import mafia_group as mafia_bot
from bot.handlers.boosters import send_shield_offer
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
        "players": "2–12",
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


class PromoCodeRequest(UserRequest):
    """Promo kodni ishlatish so'rovi."""

    code: str = ""


class MafiaBoosterRequest(UserRequest):
    """Mafiya boosterini sotib olish so'rovi."""

    booster: str = ""


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
    token = (os.getenv("BOT_TOKEN") or "").strip()

    if token:
        try:
            bot = Bot(
                token=token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            _runtime_bot = bot
            dispatcher = build_dispatcher()
            await set_commands(bot)
            polling = asyncio.create_task(dispatcher.start_polling(bot))
            logger.info("Aiogram polling fonda ishga tushdi")
        except Exception:  # bot xatosi Mini App'ni to'xtatmasligi kerak
            logger.exception("Botni ishga tushirib bo'lmadi")
            _runtime_bot = None
            if bot is not None:
                await bot.session.close()
            bot = None
            polling = None
    else:
        logger.warning("BOT_TOKEN yo'q — bot polling o'chirilgan")

    try:
        yield
    finally:
        if polling is not None:
            polling.cancel()
            await asyncio.gather(polling, return_exceptions=True)
        _runtime_bot = None
        if bot is not None:
            await bot.session.close()
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
app = FastAPI(title="Revilend Games API", version="1.1.0", lifespan=lifespan)


@app.exception_handler(RoomNotFoundError)
async def room_not_found_handler(request: Any, exc: RoomNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(PlayerNotFoundError)
async def player_not_found_handler(request: Any, exc: PlayerNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


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


@app.exception_handler(GameError)
async def game_error_handler(request: Any, exc: GameError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


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


@app.get("/api/me")
async def my_profile(
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """O'yinchining tanga balansi va statistikasi."""
    resolved_id = resolve_user_id(user, user_id)
    username = (user.username if user is not None else "") or ""
    full_name = (user.full_name if user is not None else "") or ""
    account = get_economy().ensure_user(resolved_id, username, full_name)
    return {
        "user": asdict(account),
        "shop": shop_meta(),
        "boosters": boosters_payload(),
    }


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
    """Kunlik bonus holati: mavjudmi, miqdori va qolgan vaqt."""
    resolved_id = resolve_user_id(user, user_id)
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
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Reyting jadvali va (imkon bo'lsa) o'z o'rni."""
    limit = max(1, min(int(limit), 50))
    economy = get_economy()
    accounts = economy.top_users(limit=1000)
    viewer_id = user.id if user is not None else user_id
    top = [
        leaderboard_row(account, index, viewer_id)
        for index, account in enumerate(accounts[:limit], start=1)
    ]

    me: dict[str, Any] | None = None
    if viewer_id is not None:
        viewer = next(
            (item for item in accounts if item.user_id == int(viewer_id)), None
        )
        if viewer is None:
            viewer = economy.get_user(viewer_id)
        me = leaderboard_row(viewer, account_rank(accounts, viewer), viewer_id)
        me["in_top"] = me["rank"] <= limit

    return {"top": top, "me": me, "total": len(accounts)}


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


@app.get("/api/mafia/{code}/me")
async def get_mafia_role(
    code: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Guruh Mafiya o'yinidagi o'yinchining roli va karta ma'lumoti."""
    resolved_id = resolve_user_id(user, user_id)
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
    resolved_id = resolve_user_id(user, payload.user_id)
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
    resolved_id = resolve_user_id(user, user_id)
    room = manager().get_room(code)
    return {"me": private_state(room, resolved_id)}


@app.post("/api/room/{code}/action")
async def room_action(
    code: str,
    payload: ActionRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Umumiy o'yin harakatlari: qo'shilish, boshlash, ochish, ovoz, sanash."""
    actor_id = resolve_user_id(user, payload.user_id)
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
        game_manager.join_room(code, actor_id, full_name, username)
    elif payload.action == "start":
        room = game_manager.get_room(code)
        if room.host_id != actor_id:
            raise HTTPException(
                status_code=403,
                detail="O'yinni faqat xona egasi boshlashi mumkin",
            )
        game_manager.start_game(code)
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


# Statik Mini App: avval rasm/fontlar, keyin index.html.
if ASSETS_DIR.is_dir():
    app.mount(
        "/assets", StaticFiles(directory=ASSETS_DIR), name="assets"
    )
if WEBAPP_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEBAPP_DIR, html=True), name="webapp")
