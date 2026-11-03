"""Bot konfiguratsiyasi: qiymatlar `.env` fayldan o'qiladi."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

DEFAULT_BOT_USERNAME = "revilend_gamesbot"
DEFAULT_MINI_APP_URL = "https://revilend.games"

# .env mavjud bo'lsa, uni muhit o'zgaruvchilariga yuklaydi.
load_dotenv(ENV_PATH)


@dataclass(frozen=True)
class Config:
    """Bot ishga tushishi uchun zarur sozlamalar."""

    bot_token: str
    bot_username: str
    mini_app_url: str
    admin_id: int = 0
    card_number: str = ""
    card_holder: str = ""

    def mini_app_link(self, room_code: str | None = None) -> str:
        """Mini App havolasini qaytaradi, kerak bo'lsa xona kodi bilan."""
        if not room_code:
            return self.mini_app_url
        separator = "&" if "?" in self.mini_app_url else "?"
        return f"{self.mini_app_url}{separator}room={room_code}"


@lru_cache(maxsize=1)
def get_config() -> Config:
    """`.env`dagi sozlamalarni o'qib, keshlangan Config qaytaradi.

    Raises:
        RuntimeError: ``BOT_TOKEN`` berilmagan yoki ``MINI_APP_URL`` noto'g'ri.
    """
    token = (os.getenv("BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN topilmadi. Uni .env faylga qo'shing: BOT_TOKEN=123456:ABC..."
        )

    username = (os.getenv("BOT_USERNAME") or DEFAULT_BOT_USERNAME).strip().lstrip("@")
    mini_app_url = (os.getenv("MINI_APP_URL") or DEFAULT_MINI_APP_URL).strip().rstrip("/")
    if not mini_app_url.startswith(("https://", "http://")):
        raise RuntimeError("MINI_APP_URL http:// yoki https:// bilan boshlanishi kerak")

    raw_admin_id = (os.getenv("ADMIN_ID") or "0").strip()
    try:
        admin_id = int(raw_admin_id or 0)
    except ValueError as exc:
        raise RuntimeError("ADMIN_ID butun son bo'lishi kerak") from exc

    return Config(
        bot_token=token,
        bot_username=username,
        mini_app_url=mini_app_url,
        admin_id=admin_id,
        card_number=(os.getenv("CARD_NUMBER") or "").strip(),
        card_holder=(os.getenv("CARD_HOLDER") or "").strip(),
    )
