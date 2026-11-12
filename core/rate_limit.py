"""Foydalanuvchi so'rovlarini cheklash va double-spend himoyasi.

Ikki mustaqil qatlam:

* :class:`RateLimiter` — qisqa oynada (standart 1 soniya) bitta foydalanuvchiga
  ko'pi bilan ``limit`` ta so'rov ruxsat etadi; API buni ``429`` ga aylantiradi.
* :func:`user_lock` — bitta foydalanuvchi uchun bir vaqtning o'zida faqat bitta
  pul amali (xarid, spin, bonus, promo) bajarilishini ta'minlaydigan
  ``asyncio.Lock``. Shu tufayli bir tangaga ikki buyum olinmaydi.

Qulflar hodisa sikli (event loop) bo'yicha ajratiladi: testlar har safar yangi
sikl ochsa ham ``asyncio.Lock`` "boshqa loop" xatosini bermaydi.

MUHIM CHEKLOV — bu qatlam **faqat bitta jarayon (process) ichida** ishlaydi.
Hisoblagichlar (:data:`REQUEST_LIMITER`) va qulflar (:data:`_user_locks`) oddiy
Python xotirasida saqlanadi, ular jarayonlar yoki instanslar o'rtasida
umumiy emas:

* ``uvicorn --workers N`` bilan ishga tushirilsa har bir worker o'z
  hisoblagichini yuritadi — haqiqiy limit **N × limit** bo'lib qoladi va
  ``429`` faqat bitta worker ichida ishlaydi;
* gorizontal masshtablashda (bir nechta instans/konteyner) har bir nusxa
  o'z holatini ko'radi, ya'ni limiter ular orasida **umuman** ta'sir qilmaydi;
* :func:`user_lock` ham faqat shu jarayon ichidagi ``asyncio.Lock``, shuning
  uchun ikki jarayon bitta foydalanuvchining ikki so'rovini parallel
  bajarishi mumkin.

Shu sababli loyiha ``--workers 1`` (bitta jarayon) uchun mo'ljallangan. Ko'p
jarayonli/ko'p instansli deploy kerak bo'lsa, rate limit va pul qulflarini
tashqi umumiy ombor (masalan Redis yoki DB darajasidagi atomar
SELECT/UPDATE) bilan almashtirish shart.
"""

from __future__ import annotations

import asyncio
import threading
import time
import weakref
from typing import Any

#: Bitta foydalanuvchi uchun oynadagi ruxsat etilgan so'rovlar soni.
DEFAULT_LIMIT = 2

#: Oyna davomiyligi (soniya).
DEFAULT_WINDOW = 1.0

#: Xotira chegarasi: undan oshsa eski kalitlar tozalanadi.
MAX_KEYS = 20_000


class RateLimiter:
    """Oyna (sliding window) asosidagi sodda, oqim xavfsiz limiter."""

    def __init__(
        self, limit: int = DEFAULT_LIMIT, window: float = DEFAULT_WINDOW
    ) -> None:
        self.limit = max(1, int(limit))
        self.window = max(0.001, float(window))
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """``key`` uchun so'rovni o'tkazish mumkinmi?"""
        now = time.monotonic()
        with self._lock:
            hits = [
                moment
                for moment in self._hits.get(key, ())
                if now - moment < self.window
            ]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            if len(self._hits) > MAX_KEYS:
                self._prune(now)
            return True

    def retry_after(self, key: str) -> float:
        """Kalit uchun eng qadimgi so'rov oynadan chiqishigacha qolgan vaqt."""
        now = time.monotonic()
        with self._lock:
            hits = [
                moment
                for moment in self._hits.get(key, ())
                if now - moment < self.window
            ]
        if not hits:
            return 0.0
        return max(0.0, self.window - (now - min(hits)))

    def reset(self) -> None:
        """Barcha hisoblagichlarni tozalaydi (testlar uchun)."""
        with self._lock:
            self._hits.clear()

    def _prune(self, now: float) -> None:
        """Muddati o'tgan kalitlarni olib tashlaydi."""
        expired = [
            key
            for key, hits in self._hits.items()
            if not hits or now - hits[-1] >= self.window
        ]
        for key in expired:
            self._hits.pop(key, None)


#: Standart limiter: bitta foydalanuvchi uchun sekundiga 2 ta so'rov.
#: Diqqat: bu jarayon ichidagi xotira — ``--workers N`` yoki bir nechta
#: instansda har bir jarayon o'z hisoblagichini yuritadi (umumiy emas).
REQUEST_LIMITER = RateLimiter()

# Hodisa sikli → (scope:user_id → lock). WeakKeyDictionary sikl yo'qolsa
# qulflarni ham bo'shatadi.
# Diqqat: ``asyncio.Lock`` faqat shu jarayon ichida ko'rinadi — boshqa worker
# yoki instansdagi qulf bu qulfni ko'rmaydi.
_user_locks: "weakref.WeakKeyDictionary[Any, dict[str, asyncio.Lock]]" = (
    weakref.WeakKeyDictionary()
)


def allow_request(scope: str, user_id: int) -> bool:
    """``scope:user_id`` uchun rate limitni tekshiradi."""
    return REQUEST_LIMITER.allow(f"{scope}:{int(user_id)}")


def retry_after(scope: str, user_id: int) -> float:
    """Rate limit tugashigacha qolgan vaqt (soniya)."""
    return REQUEST_LIMITER.retry_after(f"{scope}:{int(user_id)}")


def user_lock(user_id: int, scope: str = "wallet") -> asyncio.Lock:
    """Foydalanuvchi uchun joriy jarayon va hodisa siklidagi qulfni qaytaradi.

    Qulf faqat shu jarayon ichida amal qiladi: boshqa uvicorn worker yoki
    boshqa instans o'z qulfini yaratadi, shuning uchun jarayonlararo
    o'zaro istisno kafolatlanmaydi.
    """
    loop = asyncio.get_running_loop()
    key = f"{scope}:{int(user_id)}"
    locks = _user_locks.get(loop)
    if locks is None:
        locks = {}
        _user_locks[loop] = locks
    lock = locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        locks[key] = lock
    return lock


def reset_rate_limits() -> None:
    """Rate limit hisoblagichlarini tozalaydi (testlar uchun)."""
    REQUEST_LIMITER.reset()


def reset_user_locks() -> None:
    """Barcha foydalanuvchi qulflarini unutadi (testlar uchun)."""
    _user_locks.clear()


__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_WINDOW",
    "RateLimiter",
    "REQUEST_LIMITER",
    "allow_request",
    "reset_rate_limits",
    "reset_user_locks",
    "retry_after",
    "user_lock",
]
