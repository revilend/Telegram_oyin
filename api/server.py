"""Revilend Games API ilovasi.

Bu modul faqat FastAPI ilovasini yig'adi: `lifespan`, middleware, xatolik
handlerlari va routerlarni ulash. Endpointlar `api/routers/` da, umumiy
yordamchilar `api/deps.py` da.

    uvicorn api.server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from api.deps import (
    ASSETS_DIR,
    WEBAPP_DIR,
    _create_match_room,
    _matchmaking_watch,
    _notify_match,
    bomb_router,
    get_alias_manager,
    get_bomb_manager,
    get_spyfall_manager,
    logger,
    metrics,
    set_bomb_bot,
    set_spyfall_bot,
    setup_persistence,
    spyfall_router,
)
from api.routers import games, misc, profile, shop, tournaments
from bot.config import get_config
from bot.handlers import mafia_group as mafia_bot, tournaments as tournaments_handler
from bot.localized import LocalizedBot
from bot.main import build_dispatcher, set_commands
from core.daily_backup import start_daily_backup, stop_daily_backup
from core.daily_quests import DailyQuestError
from core.db import get_store
from core.economy import EconomyError, InsufficientCoinsError, get_economy
from core.persistence import ensure_admin_profile, ensure_persistence_or_raise
from core.shop import (
    ShopError,
    ShopInsufficientCoinsError,
    SpinUnavailableError,
    UnknownItemError,
    get_shop_store,
)
from core.tournaments import EntryFeeError, TournamentError, TournamentNotFoundError
from engine import test_bots
from engine.boosters import BoosterError
from engine.cleaner import get_cleaner
from engine.game_manager import (
    GameError,
    PlayerNotFoundError,
    RoomNotFoundError,
    get_default_manager,
)
from engine.matchmaking import MatchmakingError, get_matchmaker, get_queue_store
from games.spyfall import SpyfallError, SpyfallNotFoundError


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Server bilan birga aiogram botni ishga tushiradi va to'xtatadi."""
    setup_persistence()
    # Database-first: Supabase sozlanmagan prod server ishga tushmaydi
    # (RAM fallback deployda hamma narsani nol qiladi).
    ensure_persistence_or_raise()
    # Admin profili Supabase bilan sinxronlanadi (recovery).
    ensure_admin_profile(get_economy(), get_shop_store())

    global _runtime_bot
    bot: Bot | None = None
    polling: asyncio.Task[None] | None = None
    reminders: asyncio.Task[None] | None = None
    backup_job: Any | None = None
    token = (os.getenv("BOT_TOKEN") or "").strip()

    if token:
        try:
            bot = LocalizedBot(
                token=token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            _runtime_bot = bot
            set_spyfall_bot(bot)
            set_bomb_bot(bot)
            dispatcher = build_dispatcher()
            await set_commands(bot)
            polling = asyncio.create_task(dispatcher.start_polling(bot))
            reminders = tournaments_handler.start_reminder_loop(bot)
            # Har kuni 00:00 (Toshkent) da baza zaxirasi adminga yuboriladi.
            config = get_config()
            if config.admin_id:
                backup_job = start_daily_backup(bot, config.admin_id)
            logger.info("Aiogram polling fonda ishga tushdi")
        except Exception:  # bot xatosi Mini App'ni to'xtatmasligi kerak
            logger.exception("Botni ishga tushirib bo'lmadi")
            _runtime_bot = None
            set_spyfall_bot(None)
            set_bomb_bot(None)
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
    # Test rejimi (TEST_BOTS=1): ochilgan xonaga botlar qo'shilib, o'yin boshlanadi.
    test_bots.start_watcher()

    try:
        yield
    finally:
        watcher.cancel()
        test_bots.stop_watcher()
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
        set_bomb_bot(None)
        if reminders is not None:
            reminders.cancel()
            await asyncio.gather(reminders, return_exceptions=True)
        stop_daily_backup(backup_job)
        if polling is not None:
            polling.cancel()
            await asyncio.gather(polling, return_exceptions=True)
        get_store().close()
        # Global menejerni yopilgan omborga bog'lab qo'ymaymiz: keyingi ishga
        # tushirish (yoki test) toza holatdan boshlanadi.
        for manager_obj in (
            get_default_manager(),
            mafia_bot.get_default_manager(),
            get_bomb_manager(),
            get_alias_manager(),
            get_spyfall_manager(),
        ):
            setter = getattr(manager_obj, "set_change_handler", None)
            if callable(setter):
                setter(None)
            loader_setter = getattr(manager_obj, "set_room_loader", None)
            if callable(loader_setter):
                loader_setter(None)
        get_default_manager().set_coin_balance_reader(None)


app = FastAPI(title="Revilend Games API", version="1.2.0", lifespan=lifespan)

app.include_router(spyfall_router)
app.include_router(bomb_router)


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


@app.exception_handler(DailyQuestError)
async def daily_quest_error_handler(
    request: Any, exc: DailyQuestError
) -> JSONResponse:
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


# API routerlari (URL yo'llari o'zgarishsiz).
app.include_router(misc.router)
app.include_router(profile.router)
app.include_router(shop.router)
app.include_router(tournaments.router)
app.include_router(games.router)


# Statik Mini App: avval rasm/fontlar, keyin index.html.
if ASSETS_DIR.is_dir():
    app.mount(
        "/assets", StaticFiles(directory=ASSETS_DIR), name="assets"
    )
if WEBAPP_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEBAPP_DIR, html=True), name="webapp")