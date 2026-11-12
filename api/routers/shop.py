"""Do'kon, omad g'ildiragi va jihozlash endpointlari."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.auth import (
    TelegramUser,
    resolve_client_user_id,
    resolve_room_user_id,
    resolve_user_id,
    telegram_user,
)
from api.deps import (
    CATALOG_BY_SLUG,
    EquipRequest,
    ShopBuyRequest,
    SpinRequest,
    metrics,
    shop_meta,
)
from api.security import enforce_rate_limit, user_lock
from core.daily_quests import record_daily_event
from core.economy import get_economy
from core.shop import get_shop_store
from engine.boosters import boosters_payload


router = APIRouter()


@router.get("/api/shop")
async def get_shop() -> dict[str, Any]:
    """Tanga paketlari va to'lov kartasi (ochiq ma'lumot)."""
    return {"shop": shop_meta(), "boosters": boosters_payload()}


@router.get("/api/shop/items")
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


@router.post("/api/shop/buy")
async def shop_buy(
    payload: ShopBuyRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Buyumni tangalarga sotib oladi va inventarga qo'shadi.

    Frontend brauzerdan Supabase'ga yozmaydi: barcha yozuv backend
    ``service_role`` kaliti bilan ``user_inventory`` va
    ``shop_transactions`` ga amalga oshiriladi.
    """
    slug = (payload.item_slug or payload.item_id or "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="Item tanlanmagan")
    resolved_id = resolve_client_user_id(user, payload.user_id)
    enforce_rate_limit("buy", resolved_id)
    # Per-user lock: bir vaqtning o'zida faqat bitta xarid (double-spend yo'q).
    async with user_lock(resolved_id):
        metrics.user(resolved_id)
        result = get_shop_store().buy(resolved_id, slug, payload.quantity)
        record_daily_event(get_economy(), resolved_id, "shop")
        data = result.as_dict()
        data["inventory"] = [
            entry.as_dict() for entry in get_shop_store().inventory(resolved_id)
        ]
        data["equipped"] = get_shop_store().equipped(resolved_id)
        return data


@router.get("/api/shop/history")
async def shop_history(
    limit: int = 10,
    offset: int = 0,
    from_date: str | None = None,
    to_date: str | None = None,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Foydalanuvchining oxirgi xaridlari: nima, qachon va qancha tanga."""
    resolved_id = resolve_user_id(user, user_id)
    store = get_shop_store()
    cap = max(1, min(int(limit), 30))
    offset = max(0, int(offset or 0))
    rows, has_more = store.transactions_page(
        int(resolved_id or 0), cap, offset, from_date, to_date
    )
    history: list[dict[str, Any]] = []
    for row in rows:
        slug = str(row.get("item_slug") or "")
        item = CATALOG_BY_SLUG.get(slug)
        history.append(
            {
                "item_slug": slug,
                "title": (
                    item.title
                    if item is not None
                    else str(row.get("item_title") or slug)
                ),
                "emoji": item.emoji if item is not None else "\U0001f6cd",
                "kind": item.kind if item is not None else "",
                "quantity": int(row.get("quantity") or 1),
                "unit_price": int(row.get("unit_price") or 0),
                "total_price": int(row.get("total_price") or 0),
                "created_at": row.get("created_at") or "",
            }
        )
    return {
        "history": history,
        "has_more": has_more,
        "offset": offset,
        "limit": cap,
    }


@router.post("/api/spin/wheel")
async def spin_wheel(
    payload: SpinRequest | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Omad ğildiragini aylantiradi (kuniga bir bepul)."""
    # Omad g'ildiragi bitta bosishda ishlashi kerak: initData bo'lmasa ham
    # ijobiy user_id yetarli (xona amallari baribir qat'iy tekshiriladi).
    resolved_id = resolve_room_user_id(user, payload.user_id if payload else None)
    stop_angle = payload.stop_angle if payload else None
    if stop_angle is not None and not (0 <= int(stop_angle) < 360):
        raise HTTPException(status_code=422, detail="stop_angle 0..359 oralig'ida bo'lishi kerak")
    enforce_rate_limit("spin", resolved_id)
    # Bitta foydalanuvchi uchun bitta aylantiriş: bepul spin ikki marta ketmaydi.
    async with user_lock(resolved_id):
        metrics.user(resolved_id)
        store = get_shop_store()
        result = store.spin(resolved_id, stop_angle=stop_angle)
        record_daily_event(get_economy(), resolved_id, "spin")
        data = result.as_dict()
        data["spin"] = store.spin_status(resolved_id)
        data["inventory"] = [
            entry.as_dict() for entry in store.inventory(resolved_id)
        ]
        return data


@router.post("/api/profile/equip")
@router.post("/api/user/equip")
async def equip_item(
    payload: EquipRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Sotib olingan ramka yoki unvonni profilga taqadi yoki yeçadi."""
    resolved_id = resolve_client_user_id(user, payload.user_id)
    slug = (payload.item_slug or payload.item_id or "").strip()
    if not slug:
        raise HTTPException(
            status_code=422, detail="item_slug yoki item_id talab qilinadi"
        )
    result = get_shop_store().equip(resolved_id, slug, payload.equip)
    result["inventory"] = [
        entry.as_dict() for entry in get_shop_store().inventory(resolved_id)
    ]
    result["equipped_slugs"] = dict(result.get("equipped") or {})
    return result