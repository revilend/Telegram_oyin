"""Admin panel orqali o'zgartiriladigan sozlamalar (``system_settings``).

Karta raqami va uning egasi endi ``.env``dan emas, shu jadvaldan olinadi.
Supabase sozlanmagan bo'lsa qiymatlar jarayon xotirasida saqlanadi, shuning
uchun lokal test va preview rejimida ham admin panel ishlaydi.

Jadval SQL'i ``core/schema.sql`` faylida:

.. code-block:: sql

    create table if not exists public.system_settings (
        key         text primary key,
        value       text not null default '',
        updated_at  timestamptz not null default now()
    );
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

SYSTEM_SETTINGS_TABLE = "system_settings"
CARD_NUMBER_KEY = "card_number"
CARD_HOLDER_KEY = "card_holder"


class SettingsError(Exception):
    """Sozlama qiymati noto'g'ri bo'lganda ko'tariladi."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_card_number(raw: str) -> str:
    """Karta raqamidan faqat raqamlarni qoldiradi va uzunligini tekshiradi."""
    digits = "".join(char for char in str(raw or "") if char.isdigit())
    if not 16 <= len(digits) <= 19:
        raise SettingsError(
            "Karta raqami 16-19 xonali bo'lishi kerak. "
            "Masalan: 9860123456789012 Ali Valiyev"
        )
    return digits


def parse_card_line(text: str) -> tuple[str, str]:
    """``9860123456789012 Ali Valiyev`` matnini karta raqami va egasiga ajratadi."""
    raw = (text or "").strip()
    if not raw:
        raise SettingsError(
            "Karta raqami va egasining ismini yuboring. "
            "Masalan: 9860123456789012 Ali Valiyev"
        )
    tokens = raw.split()
    # Karta raqami bo'shliq yoki chiziqcha bilan yozilgan bo'lishi mumkin:
    # "9860 1234 5678 9012 Ali Valiyev".
    index = 0
    number_parts: list[str] = []
    while index < len(tokens) and all(
        char.isdigit() or char == "-" for char in tokens[index]
    ):
        number_parts.append(tokens[index])
        index += 1
    number = normalize_card_number("".join(number_parts))
    holder = " ".join(tokens[index:])
    if not holder:
        raise SettingsError(
            "Karta egasining ismini ham yozing. "
            "Masalan: 9860123456789012 Ali Valiyev"
        )
    return number, holder


def format_card_number(number: str) -> str:
    """``9860123456789012`` -> ``9860 1234 5678 9012``."""
    digits = "".join(char for char in str(number or "") if char.isdigit())
    return " ".join(digits[index : index + 4] for index in range(0, len(digits), 4))


class SettingsStore:
    """``system_settings`` jadvali bilan ishlaydigan kalit-qiymat ombori."""

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.url = (url if url is not None else os.getenv("SUPABASE_URL") or "").strip()
        self.key = (key if key is not None else os.getenv("SUPABASE_KEY") or "").strip()
        self._client = client
        self._lock = threading.RLock()
        self._values: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return self._client is not None or bool(self.url and self.key)

    @property
    def client(self) -> Any:
        if self._client is None:
            from supabase import create_client

            self._client = create_client(self.url, self.key)
        return self._client

    def get_all(self) -> dict[str, str]:
        """Barcha sozlamalarni qaytaradi."""
        with self._lock:
            if not self.enabled:
                return dict(self._values)
            rows = (
                self.client.table(SYSTEM_SETTINGS_TABLE)
                .select("key, value")
                .execute()
                .data
                or []
            )
        return {str(row["key"]): str(row.get("value") or "") for row in rows}

    def get(self, key: str, default: str = "") -> str:
        """Bitta sozlama qiymatini qaytaradi."""
        with self._lock:
            if not self.enabled:
                return self._values.get(key, default)
            rows = (
                self.client.table(SYSTEM_SETTINGS_TABLE)
                .select("value")
                .eq("key", key)
                .limit(1)
                .execute()
                .data
                or []
            )
        if not rows:
            return default
        return str(rows[0].get("value") or default)

    def set(self, key: str, value: str) -> None:
        """Sozlamani saqlaydi (mavjud bo'lsa yangilaydi)."""
        text = str(value).strip()
        with self._lock:
            if not self.enabled:
                self._values[key] = text
                return
            self.client.table(SYSTEM_SETTINGS_TABLE).upsert(
                {"key": key, "value": text, "updated_at": _now()},
                on_conflict="key",
            ).execute()

    def payment_card(self) -> tuple[str, str]:
        """To'lov kartasi: ``(raqam, egasi)``."""
        values = self.get_all()
        return (
            values.get(CARD_NUMBER_KEY, "").strip(),
            values.get(CARD_HOLDER_KEY, "").strip(),
        )

    def set_payment_card(self, number: str, holder: str) -> tuple[str, str]:
        """Karta raqami va egasini saqlab, normallashtirilgan qiymatni qaytaradi."""
        card = normalize_card_number(number)
        owner = " ".join(str(holder or "").split())
        if not owner:
            raise SettingsError(
                "Karta egasining ismini ham yozing. "
                "Masalan: 9860123456789012 Ali Valiyev"
            )
        self.set(CARD_NUMBER_KEY, card)
        self.set(CARD_HOLDER_KEY, owner)
        return card, owner


_settings: SettingsStore | None = None
_settings_lock = threading.Lock()


def get_settings_store() -> SettingsStore:
    """Jarayon bo'ylab umumiy sozlamalar omborini qaytaradi."""
    global _settings
    if _settings is None:
        with _settings_lock:
            if _settings is None:
                _settings = SettingsStore()
    return _settings
