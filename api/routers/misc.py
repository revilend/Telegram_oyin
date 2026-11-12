"""Qolgan endpointlar: health, admin, missiyalar, matchmaking."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.auth import TelegramUser, resolve_user_id, telegram_user
from api.deps import (
    AdminBalanceRequest,
    AdminTournamentRequest,
    GAMES,
    GAME_TYPE,
    LoginRequest,
    MatchmakingJoinRequest,
    MatchmakingLeaveRequest,
    PromoCodeRequest,
    TestBotsFillRequest,
    UserRequest,
    _bot_username,
    _login_user_id,
    card_type_options,
    get_spyfall_manager,
    manager,
    metrics,
    profile_identity,
    require_admin,
)
from api.security import enforce_rate_limit, user_lock
from bot.config import get_config
from bot.handlers import mafia_group as mafia_bot
from core.achievements import achievements_payload
from core.daily_quests import (
    claim_daily_quest,
    claim_weekly_chest,
    daily_quests_payload,
    record_daily_event,
    reroll_daily_quests,
)
from core.db import get_store
from core.economy import get_economy
from core.missions import claim_mission, mission_statuses, missions_payload
from core.persistence import persistence_status
from core.tournaments import get_tournament_store
from engine import test_bots
from engine.cleaner import get_cleaner
from engine.matchmaking import get_matchmaker, normalize_game_type


router = APIRouter()


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "game_type": GAME_TYPE,
        "supabase": "on" if get_store().enabled else "off",
        **persistence_status(),
    }


@router.get("/api/games")
async def list_games() -> dict[str, Any]:
    """Mavjud o'yinlar ro'yxati."""
    return {"games": GAMES}


@router.get("/api/admin/payments/pending")
async def admin_pending_payments(
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Tasdiqlashni kutayotgan tölov çeklari."""
    require_admin(user, user_id)
    payments = get_economy().list_pending_payments()
    return {"payments": [asdict(payment) for payment in payments]}


@router.post("/api/admin/payments/{request_id}/approve")
async def admin_approve_payment(
    request_id: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Çekni tasdiqlaydi va tangalarni hisobga qöşadi."""
    admin = require_admin(user, user_id)
    payment = get_economy().approve_payment(request_id, admin)
    return {"ok": True, "payment": asdict(payment)}


@router.post("/api/admin/payments/{request_id}/reject")
async def admin_reject_payment(
    request_id: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Çekni rad etadi."""
    admin = require_admin(user, user_id)
    payment = get_economy().reject_payment(request_id, admin)
    return {"ok": True, "payment": asdict(payment)}


@router.post("/api/admin/balance")
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


@router.post("/api/admin/tournaments")
async def admin_create_tournament(
    payload: AdminTournamentRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Yangi haftalik turnir oçadi."""
    admin = require_admin(user, payload.admin_id)
    start = (payload.start_time or payload.starts_at or "").strip()
    if not start:
        raise HTTPException(status_code=422, detail="start_time yoki starts_at kerak")
    tournament = get_tournament_store().create(
        payload.game_type or payload.game,
        start,
        entry_fee=payload.entry_fee,
        prize_pool=payload.prize_pool,
        title=payload.title,
        created_by=admin,
        max_players=payload.max_participants or 64,
    )
    return {"ok": True, "tournament": tournament.as_dict()}


@router.post("/api/auth/login")
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


@router.get("/api/missions")
async def my_missions(
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Foydalanuvchining missiyalari va taraqqiyoti.

    ``/api/me`` kabi: imzolangan initData bo'lmasa ham ``user_id`` bilan
    ishlaydi, shuning uchun bot klaviaturasidan ochilganda 401 bo'lmaydi.
    """
    resolved_id, _, _ = profile_identity(user, user_id)
    economy = get_economy()
    economy.ensure_user(resolved_id)
    statuses = mission_statuses(economy, resolved_id)
    return {
        "missions": missions_payload(statuses),
        "coins": economy.get_user(resolved_id).coins,
    }


@router.post("/api/missions/{mission_key}/claim")
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


@router.get("/api/quests")
async def my_daily_quests(
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Bugungi 3 ta topshiriq, reroll va haftalik sandiq holati."""
    resolved_id, _, _ = profile_identity(user, user_id)
    economy = get_economy()
    economy.ensure_user(resolved_id)
    return {
        "daily": daily_quests_payload(economy, resolved_id),
        "coins": economy.get_user(resolved_id).coins,
    }


@router.post("/api/quests/{quest_key}/claim")
async def claim_my_daily_quest(
    quest_key: str,
    payload: UserRequest | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Bajarilgan kunlik topshiriq mukofotini beradi."""
    resolved_id = resolve_user_id(user, payload.user_id if payload else None)
    result = claim_daily_quest(get_economy(), resolved_id, quest_key)
    return {"ok": True, **result}


@router.post("/api/quests/reroll")
async def reroll_my_daily_quests(
    payload: UserRequest | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Kuniga bir marta topshiriqlarni almashtiradi."""
    resolved_id = resolve_user_id(user, payload.user_id if payload else None)
    daily = reroll_daily_quests(get_economy(), resolved_id)
    return {
        "ok": True,
        "daily": daily,
        "coins": get_economy().get_user(resolved_id).coins,
    }


@router.post("/api/quests/chest")
async def claim_my_weekly_chest(
    payload: UserRequest | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Haftalik 5 ta topshiriq sandiqini ochadi."""
    resolved_id = resolve_user_id(user, payload.user_id if payload else None)
    result = claim_weekly_chest(get_economy(), resolved_id)
    return {"ok": True, **result}


@router.get("/api/achievements")
async def my_achievements(
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Profil nishonlari: ochilganlar va progress."""
    resolved_id, _, _ = profile_identity(user, user_id)
    rows = achievements_payload(get_economy(), resolved_id)
    return {
        "achievements": rows,
        "unlocked": sum(1 for row in rows if row["unlocked"]),
        "total": len(rows),
    }


@router.post("/api/promo")
async def redeem_promo_code(
    payload: PromoCodeRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Promo kodni ishlatib, tanga oladi."""
    resolved_id = resolve_user_id(user, payload.user_id)
    enforce_rate_limit("promo", resolved_id)
    async with user_lock(resolved_id):
        result = get_economy().redeem_promo_code(resolved_id, payload.code)
        return {
            "ok": True,
            "code": result.code,
            "amount": result.coins,
            "coins": result.account.coins,
        }


@router.get("/api/matchmaking")
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


@router.get("/api/test/bots")
async def test_bots_status() -> dict[str, Any]:
    """Test rejimi holati: yoqilganmi, qaysi xonalar kuzatilmoqda va oxirgi loglar."""
    return test_bots.status()


@router.post("/api/test/bots/fill")
async def test_bots_fill(payload: TestBotsFillRequest) -> dict[str, Any]:
    """Xonaga uchta virtual bot qo'shib, o'yinni avtomatik boshlaydi."""
    if not test_bots.test_mode_enabled():
        raise HTTPException(
            status_code=400,
            detail=f"Test rejimi o'chirilgan: serverni {test_bots.TEST_MODE_ENV}=1 bilan ishga tushiring",
        )
    return test_bots.fill_room(payload.game_type, payload.code)


@router.post("/api/matchmaking/join")
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
    record_daily_event(get_economy(), resolved_id, "match")
    return {"ok": True, **result}


@router.post("/api/matchmaking/leave")
async def matchmaking_leave(
    payload: MatchmakingLeaveRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """O'yinchini navbatdan chiqaradi."""
    resolved_id = resolve_user_id(user, payload.user_id)
    result = get_matchmaker().leave(resolved_id, payload.game_type)
    return {"ok": True, **result}


@router.get("/api/lobbies")
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


@router.get("/api/metrics")
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


@router.get("/api/meta/cards")
async def meta_cards() -> dict[str, Any]:
    """Karta turlarining yorliqlari."""
    return {"card_types": card_type_options()}