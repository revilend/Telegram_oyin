"""Profil, bootstrap, faollik, kunlik bonus va til endpointlari."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.auth import (
    TelegramUser,
    resolve_client_user_id,
    resolve_user_id,
    telegram_user,
)
from api.deps import (
    GAMES,
    LanguageRequest,
    UserRequest,
    _activity_payload_async,
    _profile_payload,
    profile_identity,
    shop_meta,
)
from api.security import enforce_rate_limit, user_lock
from core.daily_quests import record_daily_event
from core.economy import get_economy
from core.tournaments import get_tournament_store
from engine.boosters import boosters_payload


router = APIRouter()


@router.post("/api/profile/language")
@router.post("/api/user/language")
async def save_language(
    payload: LanguageRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Foydalanuvchining afzal tilini Supabase'ga yozadi."""
    from core.i18n import LANGUAGES as SUPPORTED_LANGUAGES

    resolved_id = resolve_client_user_id(user, payload.user_id)
    code = (payload.language_code or "").strip().lower().split("-")[0].split("_")[0]
    if code not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail="language_code uz/ru/en bo'lishi kerak")
    economy = get_economy()
    economy.ensure_user(resolved_id, "", "")
    economy.set_language(resolved_id, code)
    return {"user_id": resolved_id, "language_code": code}


@router.get("/api/me")
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
    # Supabase so'rovlari event loop'ni bloklamaydi.
    return await asyncio.to_thread(
        _profile_payload, resolved_id, resolved_username, resolved_name
    )


@router.get("/api/bonus")
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


@router.post("/api/bonus")
async def bonus_claim(
    payload: UserRequest | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Kunlik bonusni oladi (har 24 soatda bir marta)."""
    resolved_id = resolve_user_id(user, payload.user_id if payload else None)
    enforce_rate_limit("bonus", resolved_id)
    async with user_lock(resolved_id):
        economy = get_economy()
        claim = economy.claim_daily_bonus(resolved_id)
        record_daily_event(economy, resolved_id, "bonus")
        return {
            "ok": True,
            "amount": claim.amount,
            "streak": claim.streak,
            "coins": claim.account.coins,
            "bonus": asdict(economy.daily_bonus_status(resolved_id)),
        }


@router.get("/api/activity")
async def activity_snapshot(
    user_id: int | None = None,
    username: str = "",
    full_name: str = "",
    limit: int = 10,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Profil faolligi: bonus, missiyalar va reyting bir javobda.

    ``/api/me`` kabi, imzolangan initData bo'lmasa ham ``user_id`` bilan
    ishlaydi. Mini App botning pastki klaviaturasidan ochilganda shu sabab
    missiyalar, streak va reyting 401 xatosiz yuklanadi.
    """
    resolved_id, _, _ = profile_identity(user, user_id, username, full_name)
    limit = max(1, min(int(limit), 50))
    return await _activity_payload_async(resolved_id, limit)


@router.get("/api/bootstrap")
async def bootstrap(
    user_id: int | None = None,
    username: str = "",
    full_name: str = "",
    limit: int = 10,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Mini App uchun yagona tezkor bootstrap endpoint.

    Profil, bonus/streak, missiyalar, faol turnir, inventar va o'yinlar
    ro'yxati bitta javobda qaytadi, shuning uchun Mini App birinchi
    ochilishda 5 ta alohida so'rov yubormaydi. Mustaqil so'rovlar
    ``asyncio.gather`` bilan parallel bajariladi.
    """
    resolved_id, resolved_username, resolved_name = profile_identity(
        user, user_id, username, full_name
    )
    limit = max(1, min(int(limit), 50))
    economy = get_economy()
    account = await asyncio.to_thread(
        economy.ensure_user, resolved_id, resolved_username, resolved_name
    )
    account_payload, activity_payload, tournament = await asyncio.gather(
        asyncio.to_thread(
            _profile_payload,
            resolved_id,
            resolved_username,
            resolved_name,
            account,
        ),
        _activity_payload_async(resolved_id, limit, account),
        asyncio.to_thread(
            lambda: get_tournament_store().payload(resolved_id)
        ),
    )
    return {
        "account": account_payload,
        "activity": activity_payload,
        "tournament": tournament,
        "games": GAMES,
        "shop": shop_meta(),
        "boosters": boosters_payload(),
        "generated_at": time.time(),
    }