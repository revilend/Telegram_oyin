"""Telegram Mini App `initData` imzosini tekshirish.

Telegram tavsiyasiga ko'ra `initData` maydonlari `hash`dan tashqari alifbo
tartibida birlashtiriladi, `WebAppData` kaliti bilan bot tokenidan olingan
maxfiy kalit orqali HMAC-SHA256 hisoblanadi va natija `hash` bilan
solishtiriladi. Imzo to'g'ri bo'lsa, foydalanuvchining haqiqiy `user_id`si
qaytariladi.
"""

from __future__ import annotations

import logging

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qsl

from dotenv import load_dotenv
from fastapi import Header, HTTPException

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_SECONDS = 86400
CLOCK_SKEW_SECONDS = 30


class InitDataError(ValueError):
    """`initData` formati, imzosi yoki muddati noto'g'ri."""


@dataclass(frozen=True)
class TelegramUser:
    """Imzosi tasdiqlangan Telegram foydalanuvchisi."""

    id: int
    first_name: str
    last_name: str = ""
    username: str = ""

    @property
    def full_name(self) -> str:
        return " ".join(
            part for part in (self.first_name, self.last_name) if part
        ).strip()


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int | None = DEFAULT_MAX_AGE_SECONDS,
    now: int | None = None,
) -> TelegramUser:
    """`initData` imzosini tekshiradi va foydalanuvchini qaytaradi.

    Raises:
        InitDataError: imzo noto'g'ri, maydonlar yetishmaydi yoki muddat o'tgan.
    """
    if not init_data:
        raise InitDataError("initData bo'sh")
    if not bot_token:
        raise InitDataError("BOT_TOKEN sozlanmagan")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True)
    except ValueError as exc:
        raise InitDataError("initData formati noto'g'ri") from exc

    data = dict(pairs)
    received_hash = data.pop("hash", "")
    if not received_hash:
        raise InitDataError("initData'da hash maydoni yo'q")

    data_check_string = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
    ).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise InitDataError("initData imzosi noto'g'ri")

    try:
        auth_date = int(data.get("auth_date", ""))
    except (TypeError, ValueError) as exc:
        raise InitDataError("auth_date noto'g'ri") from exc

    current = int(time.time()) if now is None else int(now)
    if auth_date > current + CLOCK_SKEW_SECONDS:
        raise InitDataError("auth_date kelajakda")
    if max_age_seconds is not None and current - auth_date > max_age_seconds:
        raise InitDataError("initData muddati o'tgan")

    raw_user = data.get("user", "")
    if not raw_user:
        raise InitDataError("initData'da user maydoni yo'q")
    try:
        user_payload = json.loads(raw_user)
    except json.JSONDecodeError as exc:
        raise InitDataError("user JSON formati noto'g'ri") from exc

    if not isinstance(user_payload, dict) or user_payload.get("id") is None:
        raise InitDataError("user maydonida id yo'q")
    try:
        user_id = int(user_payload["id"])
    except (TypeError, ValueError) as exc:
        raise InitDataError("user id noto'g'ri") from exc

    return TelegramUser(
        id=user_id,
        first_name=str(user_payload.get("first_name") or "").strip(),
        last_name=str(user_payload.get("last_name") or "").strip(),
        username=str(user_payload.get("username") or "").strip(),
    )


def telegram_user(
    x_telegram_init_data: Annotated[
        str | None, Header(alias="X-Telegram-Init-Data")
    ] = None,
) -> TelegramUser | None:
    """FastAPI dependency: ixtiyoriy `initData`ni tekshiradi.

    Header bo'lmasa ``None`` qaytaradi; mavjud bo'lib, noto'g'ri bo'lsa 401.
    """
    if not x_telegram_init_data:
        return None

    bot_token = (os.getenv("BOT_TOKEN") or "").strip()
    if not bot_token:
        # Token yo'q bo'lsa imzoni tekshirib bo'lmaydi: Mini App'ni bloklamaymiz.
        logger.warning("BOT_TOKEN yo'q — initData tekshirilmaydi")
        return None

    try:
        max_age = int(os.getenv("INIT_DATA_MAX_AGE", str(DEFAULT_MAX_AGE_SECONDS)))
        return validate_init_data(
            x_telegram_init_data, bot_token, max_age_seconds=max_age
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail=f"initData tekshiruvi muvaffaqiyatsiz: {exc}",
        ) from exc


def guest_auth_allowed() -> bool:
    """`ALLOW_GUEST_AUTH` yoqilganmi (lokal sinov uchun)."""
    value = (os.getenv("ALLOW_GUEST_AUTH") or "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def resolve_user_id(
    user: TelegramUser | None,
    fallback_id: int | None,
) -> int:
    """Tasdiqlangan foydalanuvchi yoki (ruxsat bo'lsa) so'rovdagi id.

    Imzo tekshiruvi ustuvor: header mavjud bo'lsa, `user.id` qaytariladi va
    so'rovdagi `user_id` e'tiborga olinmaydi.
    """
    if user is not None:
        return user.id
    if guest_auth_allowed() and fallback_id is not None:
        return int(fallback_id)
    raise HTTPException(
        status_code=401,
        detail="Telegram initData talab qilinadi",
    )


def resolve_room_user_id(
    user: TelegramUser | None,
    fallback_id: int | None,
) -> int:
    """Xona endpointlari uchun foydalanuvchi identifikatori.

    Mini App xonaga kirish uchun ``user_id`` yuborsa yetarli: initData
    yo'qligi sababli kirish to'xtab qolmaydi. initData mavjud bo'lsa,
    imzolangan identifikator ustuvor bo'lib qoladi.
    """
    if user is not None:
        return user.id
    if fallback_id is not None:
        resolved = int(fallback_id)
        if resolved > 0:
            return resolved
    raise HTTPException(
        status_code=401,
        detail="Foydalanuvchi aniqlanmadi: user_id yuboring",
    )
