"""Doimiy saqlash (Supabase-first) qoidalari.

Turg'un ma'lumotlar (balans, statistika, streak, inventar, turnirlar)
RAM'da emas, Supabase'da yashaydi. RAM faqat jonli o'yin holati uchun.

Agar Supabase sozlanmagan bo'lsa, prod server jim RAM fallback'ida
ishlamaydi — deployda hamma narsa nol bo'lib qolmasligi uchun
lifespan ``RuntimeError`` beradi (test/lokalda
``ALLOW_GUEST_AUTH=true`` yoki ``ALLOW_IN_MEMORY_FALLBACK=true`` bilan
ruxsat etiladi).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

ADMIN_USER_ID = 6418438641
ADMIN_RECOVERY_COINS = 100_000_000
ADMIN_RECOVERY_STREAK = 4
ADMIN_RECOVERY_FRAME = "frame_fire_dragon"


def _env_flag(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def memory_fallback_allowed() -> bool:
    """RAM fallbackga qo'lda ruxsat berilganmi (test/lokal sinov uchun)."""
    return _env_flag("ALLOW_GUEST_AUTH") or _env_flag(
        "ALLOW_IN_MEMORY_FALLBACK"
    )


def persistence_status() -> dict[str, str]:
    """Diagnostika uchun: qaysi do'konlar Supabase'da saqlanadi."""
    from core.economy import get_economy
    from core.shop import get_shop_store

    return {
        "economy": "on" if get_economy().enabled else "off",
        "shop": "on" if get_shop_store().enabled else "off",
    }


def ensure_persistence_or_raise() -> None:
    """Prod'da Supabase yo'q bo'lsa ishga tushishni to'xtatadi.

    Maqsad: Render'ta kalitlarsiz deploy bo'lib, platforma RAM'da nol
    holatga tushishining oldini olish. Test/lokalda (`ALLOW_GUEST_AUTH`
    yoki `ALLOW_IN_MEMORY_FALLBACK` yoqilgan) xotirada ishlashga
    ruxsat beriladi.
    """
    status = persistence_status()
    if status["economy"] == "on" and status["shop"] == "on":
        return
    if memory_fallback_allowed():
        logger.warning(
            "Supabase sozlanmagan (economy=%s shop=%s): sinov rejimida "
            "xotirada ishlatiladi, ma'lumotlar doimiy emas.",
            status["economy"],
            status["shop"],
        )
        return
    raise RuntimeError(
        "Supabase sozlanmagan (SUPABASE_URL/SUPABASE_KEY kerak): "
        "prod server RAM-only ishlay olmaydi — ma'lumotlar deployda "
        "yo'qoladi. Render environment'ga kalitlarni qo'shing yoki "
        "sinov uchun ALLOW_GUEST_AUTH=true / ALLOW_IN_MEMORY_FALLBACK=true "
        "qo'ying."
    )


def ensure_admin_profile(economy: Any, shop: Any) -> bool:
    """Admin profilingni Supabase bilan sinxronlaydi (recovery).

    Qoida: mavjud profil hech qachon nol qilinmaydi. Agar qator
    bo'lmasa yoki tegishli maydon bo'sh/nol bo'lsa, quyidagi doimiy
    minimal holat tiklanadi:
      coins >= 100000000, streak_days == bonus_streak >= 4,
      frame_fire_dragon ramkasi mavjud va taqilgan.
    """
    if not getattr(economy, "enabled", False):
        return False
    uid = ADMIN_USER_ID
    try:
        account = economy.ensure_user(uid)
        if account.coins < ADMIN_RECOVERY_COINS:
            economy.add_coins(uid, ADMIN_RECOVERY_COINS - account.coins)
            account = economy.ensure_user(uid)

        if account.bonus_streak < ADMIN_RECOVERY_STREAK:
            claimed = account.last_bonus_at or (
                datetime.now(timezone.utc) - timedelta(hours=24)
            ).isoformat()
            economy._update_user_row(
                uid,
                {
                    "last_bonus_at": claimed,
                    "last_daily_claim": claimed,
                    "bonus_streak": ADMIN_RECOVERY_STREAK,
                    "streak_days": ADMIN_RECOVERY_STREAK,
                },
            )

        if getattr(shop, "enabled", False):
            from core.shop import InventoryEntry

            entry = shop.entry(uid, ADMIN_RECOVERY_FRAME)
            if entry.quantity < 1:
                shop._save_entry(
                    uid,
                    InventoryEntry(
                        item_slug=ADMIN_RECOVERY_FRAME,
                        quantity=1,
                        is_equipped=True,
                    ),
                    strict=True,
                )
            elif not entry.is_equipped:
                shop._save_entry(
                    uid,
                    InventoryEntry(
                        item_slug=entry.item_slug,
                        quantity=entry.quantity,
                        is_equipped=True,
                    ),
                    strict=True,
                )
            # users.equipped_frame literal qiymat bilan saqlanadi.
            shop._sync_equipped_columns(
                uid, {"frame": ADMIN_RECOVERY_FRAME, "title": ""}
            )
            logger.info(
                "Admin profili Supabase bilan sinxronlandi: user=%s coins>=%s "
                "streak>=%s frame=%s",
                uid,
                ADMIN_RECOVERY_COINS,
                ADMIN_RECOVERY_STREAK,
                ADMIN_RECOVERY_FRAME,
            )
            return True
    except Exception:
        logger.exception("Admin profilini Supabase bilan sinxronlab bo'lmadi")
    return False