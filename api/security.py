"""API darajasidagi xavfsizlik yordamchilari.

Routerlar pul bilan bog'liq endpointlarda shu moduldan foydalanadi:

* :func:`enforce_rate_limit` — foydalanuvchi sekundiga 2 tadan ko'p so'rov
  yuborsa ``429 Too Many Requests`` qaytaradi;
* :func:`user_lock` — per-user ``asyncio.Lock``, bir vaqtning o'zida faqat
  bitta xarid/spin/bonus jarayoni bajarilishini ta'minlaydi.

Ikkala qatlam ham **faqat bitta jarayon ichida** ishlaydi: hisoblagichlar va
qulflar ``core/rate_limit.py`` dagi jarayon xotirasida turadi, shuning uchun
``uvicorn --workers N`` yoki bir nechta instansda ular umumiy emas (har bir
worker o'z limitini hisoblaydi, jarayonlararo qulf yo'q). Batafsil:
:mod:`core.rate_limit`.
"""

from __future__ import annotations

import logging
import math

from fastapi import HTTPException

from core.rate_limit import allow_request, retry_after, user_lock

logger = logging.getLogger(__name__)

RATE_LIMIT_DETAIL = (
    "Juda ko'p so'rov yuborildi. Bir soniyadan keyin qayta urinib ko'ring."
)


def enforce_rate_limit(scope: str, user_id: int) -> None:
    """Rate limitdan oshsa ``429`` xatosini ko'taradi.

    ``scope`` — amal nomi (``buy``, ``spin``, ``bonus``, ``promo``).
    Hisoblagich jarayon xotirasida: bir nechta worker/instans bo'lsa har biri
    o'z limitini yuritadi, ya'ni cheklov ular orasida umumiy emas.
    """
    if allow_request(scope, user_id):
        return
    wait = max(1.0, math.ceil(retry_after(scope, user_id) or 1.0))
    logger.warning(
        "Rate limit: scope=%s user=%s — 429 qaytarildi (retry_after=%ss)",
        scope,
        user_id,
        wait,
    )
    raise HTTPException(
        status_code=429,
        detail=RATE_LIMIT_DETAIL,
        headers={"Retry-After": str(int(wait))},
    )


__all__ = ["RATE_LIMIT_DETAIL", "enforce_rate_limit", "user_lock"]
