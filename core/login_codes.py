"""Mini App uchun bir martalik 6 xonali kirish kodlari.

Bot kod yaratadi, ``POST /api/auth/login`` esa kodni tekshirib, foydalanuvchi
profilini qaytaradi. Kodlar jarayon xotirasida saqlanadi va bir marta
ishlatilgandan yoki muddati tugagandan keyin o'chiriladi.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

LOGIN_CODE_LENGTH = 6
LOGIN_CODE_TTL_SECONDS = 10 * 60


@dataclass(frozen=True)
class _LoginCode:
    user_id: int
    expires_at: float


_lock = threading.Lock()
_codes: dict[str, _LoginCode] = {}


def _cleanup(now: float) -> None:
    """Muddati o'tgan kodlarni xotiradan olib tashlaydi."""
    for code, item in list(_codes.items()):
        if item.expires_at <= now:
            _codes.pop(code, None)


def issue_login_code(user_id: int, *, now: float | None = None) -> str:
    """Foydalanuvchi uchun yangi bir martalik kod yaratadi.

    Avvalgi kodlar bekor qilinadi, shuning uchun faqat oxirgi yuborilgan kod
    ishlaydi.
    """
    uid = int(user_id)
    moment = time.time() if now is None else float(now)
    with _lock:
        _cleanup(moment)
        for code, item in list(_codes.items()):
            if item.user_id == uid:
                _codes.pop(code, None)
        while True:
            code = f"{secrets.randbelow(10**LOGIN_CODE_LENGTH):0{LOGIN_CODE_LENGTH}d}"
            if code not in _codes:
                break
        _codes[code] = _LoginCode(
            user_id=uid, expires_at=moment + LOGIN_CODE_TTL_SECONDS
        )
    return code


def verify_login_code(code: str, *, now: float | None = None) -> int | None:
    """Kodni bir marta tekshiradi va foydalanuvchi id'sini qaytaradi."""
    normalized = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(normalized) != LOGIN_CODE_LENGTH:
        return None
    moment = time.time() if now is None else float(now)
    with _lock:
        item = _codes.pop(normalized, None)
    if item is None or item.expires_at <= moment:
        return None
    return item.user_id


def reset_login_codes() -> None:
    """Barcha kodlarni tozalaydi (testlar va qayta ishga tushirish uchun)."""
    with _lock:
        _codes.clear()


__all__ = [
    "LOGIN_CODE_LENGTH",
    "LOGIN_CODE_TTL_SECONDS",
    "issue_login_code",
    "reset_login_codes",
    "verify_login_code",
]
