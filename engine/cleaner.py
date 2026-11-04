"""Har 5 daqiqada faol bo'lmagan o'yin xonalarini tozalash."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from bot.handlers import mafia_group
from engine.game_manager import get_default_manager
from games.spyfall.manager import get_default_manager as get_spyfall_manager
from core.db import get_store

logger = logging.getLogger(__name__)

CLEAN_INTERVAL_SECONDS = 300
LOBBY_TIMEOUT_SECONDS = 15 * 60
ACTIVE_TIMEOUT_SECONDS = 30 * 60


def _parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def clean_persisted_rooms() -> dict[str, list[str]]:
    """Xotiraga yuklanmagan Supabase xonalarini ham muddati bo'yicha tozalaydi."""
    store = get_store()
    result: dict[str, list[str]] = {"bunker_db": [], "spyfall_db": []}
    if not store.enabled:
        return result
    now = datetime.now(timezone.utc)
    try:
        rows = (
            store.client.table("rooms")
            .select("code,status,updated_at")
            .in_("status", ["LOBBY", "PLAYING", "VOTING", "SHIELD_OFFER"])
            .execute()
            .data or []
        )
        for row in rows:
            updated = _parse_timestamp(row.get("updated_at"))
            if updated is None:
                continue
            status = str(row.get("status") or "")
            timeout = LOBBY_TIMEOUT_SECONDS if status == "LOBBY" else ACTIVE_TIMEOUT_SECONDS
            if (now - updated).total_seconds() < timeout:
                continue
            target = "EXPIRED" if status == "LOBBY" else "FINISHED"
            store.client.table("rooms").update({
                "status": target,
                "updated_at": now.isoformat(),
            }).eq("code", row["code"]).execute()
            result["bunker_db"].append(str(row["code"]))

        spy_rows = (
            store.client.table("spyfall_rooms")
            .select("code,state,updated_at")
            .execute()
            .data or []
        )
        for row in spy_rows:
            updated = _parse_timestamp(row.get("updated_at"))
            state = row.get("state") or {}
            phase = str(state.get("phase") or "LOBBY").upper()
            timeout = LOBBY_TIMEOUT_SECONDS if phase == "LOBBY" else ACTIVE_TIMEOUT_SECONDS
            if updated is None or phase == "FINISHED" or (now - updated).total_seconds() < timeout:
                continue
            code = str(row.get("code") or "")
            if phase == "LOBBY":
                store.client.table("spyfall_rooms").delete().eq("code", code).execute()
            else:
                state["phase"] = "FINISHED"
                state["finish_reason"] = "Faolsizlik sababli o'yin yakunlandi."
                store.client.table("spyfall_rooms").update({
                    "state": state,
                    "updated_at": now.isoformat(),
                }).eq("code", code).execute()
            result["spyfall_db"].append(code)
    except Exception:
        logger.exception("Supabase'dagi faol bo'lmagan xonalarni tozalashda xatolik")
    return result


def clean_once() -> dict[str, list[str]]:
    """Barcha o'yin menejerlarida muddati o'tgan xonalarni tekshiradi."""
    removed = {
        "bunker": get_default_manager().expire_inactive(
            lobby_seconds=LOBBY_TIMEOUT_SECONDS,
            active_seconds=ACTIVE_TIMEOUT_SECONDS,
        ),
        "mafia": mafia_group.get_default_manager().expire_inactive(
            lobby_seconds=LOBBY_TIMEOUT_SECONDS,
            active_seconds=ACTIVE_TIMEOUT_SECONDS,
        ),
        "spyfall": get_spyfall_manager().expire_inactive(
            lobby_seconds=LOBBY_TIMEOUT_SECONDS,
            active_seconds=ACTIVE_TIMEOUT_SECONDS,
        ),
    }
    removed.update(clean_persisted_rooms())
    total = sum(len(codes) for codes in removed.values())
    if total:
        logger.info("Faolsiz xonalar yopildi: %s", removed)
    return removed


async def cleaner_loop() -> None:
    """Server ishlayotgan paytda har 5 daqiqada tozalashni bajaradi."""
    while True:
        try:
            await asyncio.to_thread(clean_once)
        except Exception:
            logger.exception("Avtomatik xona tozalashda xatolik")
        await asyncio.sleep(CLEAN_INTERVAL_SECONDS)
