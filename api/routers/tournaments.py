"""Turnirlar, reyting va o'yin tarixi endpointlari."""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import *  # noqa: F401,F403 - umumiy yordamchi va sxemalar

router = APIRouter()


@router.get("/api/tournaments/active")
async def tournaments_active(
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Ro'yxatga olish ochiq turnirlar: sovrin, vaqt va qatnaşçilar."""
    viewer_id = user.id if user is not None else user_id
    return get_tournament_store().payload(viewer_id)


@router.post("/api/tournaments/join")
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


@router.get("/api/top")
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


@router.get("/api/league")
async def weekly_league(
    limit: int = 10,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Joriy haftalik liga: o'yin va g'alaba ballari."""
    limit = max(1, min(int(limit), 50))
    viewer_id = user.id if user is not None else user_id
    return {"league": get_economy().weekly_league(limit=limit, viewer_id=viewer_id)}


@router.get("/api/history")
async def game_history(
    limit: int = 10,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Foydalanuvchining oxirgi o'yinlari."""
    resolved_id = resolve_user_id(user, user_id)
    metrics.user(resolved_id)
    return {"history": get_economy().history_for_user(resolved_id, limit)}
