"""Tangalar, to'lov so'rovlari va boosterlar uchun iqtisod qatlami.

Supabase sozlangan bo'lsa ma'lumotlar ``users``, ``payment_requests``,
``player_boosters`` va ``game_results`` jadvallarida saqlanadi. Supabase
bo'lmasa (lokal test yoki preview) hammasi jarayon xotirasida ishlaydi.
"""

from __future__ import annotations

import logging
import math
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

from core.db import safe_insert, safe_update
from core.metrics import metrics

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

USERS_TABLE = "users"
# Supabase'dagi `users` jadvalida asosiy ustun `telegram_id` deb nomlangan.
USERS_ID_COLUMN = "telegram_id"
PAYMENTS_TABLE = "payment_requests"
BOOSTERS_TABLE = "player_boosters"
RESULTS_TABLE = "game_results"
HISTORY_TABLE = "game_history"
REFERRALS_TABLE = "referrals"
WEEKLY_WIN_POINTS = 3
WEEKLY_PLAY_POINTS = 1

# Virtual /test_game botlari 900 bilan boshlanadigan ID larda yaratiladi
# (9_000_000_000 ...). Faqat `id < 9000000000` bo'lgan haqiqiy Telegram
# foydalanuvchilari reytingga kiritiladi.
TEST_BOT_ID_THRESHOLD = 9_000_000_000

# Foydalanuvchi profili keshi: /start va menyu tugmalari bazaga har safar
# so'rov yubormasligi uchun qisqa muddatli xotira keshi (sekundlarda).
PROFILE_CACHE_TTL = 30.0
# Jami foydalanuvchilar soni (admin bildirishnomasi uchun) keshi.
USER_COUNT_TTL = 30.0

PENDING = "PENDING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"

# Tanga paketlari: tanga -> so'mdagi narx.
COIN_PACKAGES: dict[int, int] = {
    500: 10_000,
    1_500: 25_000,
    4_000: 60_000,
}

# Yangi o'yinchiga sovg'a qilinadigan boshlang'ich tangalar.
START_COINS = 100
# Reyting: har bir g'alaba shu qadar ball qo'shadi.
RATING_BASE = 1_000
RATING_WIN_BONUS = 50
# Har bir muvaffaqiyatli taklif uchun taklif qiluvchiga beriladigan tanga.
REFERRAL_BONUS = 75
# Mafiya o'yinida g'olib bo'lgan har bir tirik o'yinchi uchun mukofot.
MAFIA_WIN_REWARD = 25

# Kunlik bonus jadvali: 1-kundan 7-kungacha (7-kun — katta mukofot).
DAILY_BONUS_TABLE: tuple[int, ...] = (25, 35, 50, 70, 100, 150, 250)
DAILY_BONUS_BASE = DAILY_BONUS_TABLE[0]
DAILY_BONUS_MAX_STREAK = len(DAILY_BONUS_TABLE)
DAILY_BONUS_INTERVAL_SECONDS = 24 * 60 * 60
# Ikki kunlik tanaffusdan keyin seriya qaytadan boshlanadi.
DAILY_BONUS_STREAK_WINDOW_SECONDS = 48 * 60 * 60

PROMO_CODES_TABLE = "promo_codes"
PROMO_REDEMPTIONS_TABLE = "promo_redemptions"
MISSIONS_TABLE = "player_missions"
PROMO_CODE_PATTERN = re.compile(r"^[A-Z0-9]{4,24}$")


class EconomyError(Exception):
    """Iqtisod amali bajarilmaydigan holat."""


class InsufficientCoinsError(EconomyError):
    """Balansda yetarli tanga yo'q."""


@dataclass(frozen=True)
class UserAccount:
    """O'yinchining hamyon va statistika ma'lumotlari."""

    user_id: int
    username: str = ""
    full_name: str = ""
    coins: int = 0
    total_purchased: int = 0
    games_played: int = 0
    wins: int = 0
    bunker_wins: int = 0
    mafia_wins: int = 0
    spy_wins: int = 0
    alias_wins: int = 0
    bomb_wins: int = 0
    referral_count: int = 0
    last_bonus_at: str = ""
    last_daily_claim: str = ""
    bonus_streak: int = 0
    streak_days: int = 0
    is_blocked: bool = False
    block_reason: str = ""
    role: str = "user"
    is_bot: bool = False
    language_code: str = ""


@dataclass(frozen=True)
class PaymentRequest:
    """Admin tasdiqlashini kutayotgan chek."""

    id: str
    user_id: int
    username: str
    full_name: str
    package_coins: int
    price_uzs: int
    receipt_file_id: str
    status: str = PENDING
    reviewed_by: int | None = None
    created_at: str = ""


@dataclass(frozen=True)
class DailyBonusStatus:
    """Kunlik bonus holati (Mini App va bot uchun)."""

    available: bool
    amount: int
    streak: int
    seconds_left: int
    next_amount: int = 0
    streak_days: int = 0
    last_daily_claim: str = ""


@dataclass(frozen=True)
class DailyBonusClaim:
    """Muvaffaqiyatli kunlik bonus natijasi."""

    amount: int
    streak: int
    account: UserAccount
    next_amount: int = 0
    streak_days: int = 0
    last_daily_claim: str = ""


@dataclass(frozen=True)
class PromoCode:
    """Admin yaratgan promo kod."""

    code: str
    coins: int
    max_uses: int = 1
    used_count: int = 0
    created_at: str = ""


@dataclass(frozen=True)
class PromoRedemption:
    """Promo kod ishlatilgandagi natija."""

    code: str
    coins: int
    account: UserAccount


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_moment() -> datetime:
    return datetime.now(timezone.utc)


def _parse_moment(value: Any) -> datetime | None:
    """Supabase'dan kelgan vaqtni vaqt mintaqasi bilan datetime'ga aylantiradi."""
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _format_wait(seconds: int) -> str:
    """``90000`` -> ``25 soat 0 daqiqadan keyin`` ko'rinishida."""
    minutes = max(1, int(math.ceil(int(seconds) / 60)))
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} soat {minutes} daqiqadan keyin"
    return f"{minutes} daqiqadan keyin"


def normalize_promo_code(raw: Any) -> str:
    """Promo kodni katta harflarga keltiradi va formatini tekshiradi."""
    code = "".join(str(raw or "").split()).upper()
    if not PROMO_CODE_PATTERN.match(code):
        raise EconomyError(
            "Promo kod 4–24 ta harf va raqamdan iborat bo'lishi kerak"
        )
    return code


def daily_bonus_amount(streak: int) -> int:
    """Berilgan seriya kuni uchun bonus miqdori (1–7)."""
    index = min(max(1, int(streak)), DAILY_BONUS_MAX_STREAK) - 1
    return DAILY_BONUS_TABLE[index]


def next_daily_bonus_amount(streak: int) -> int:
    """Bugungi bonusdan keyingi kun uchun kutilayotgan mukofot."""
    return daily_bonus_amount(int(streak) + 1)


def _daily_bonus_plan(
    account: UserAccount, now: datetime
) -> tuple[bool, int, int, int]:
    """Bonus mavjudligi, mukofot, seriya va qolgan soniyalarni hisoblaydi."""
    last = _parse_moment(account.last_bonus_at)
    if last is None:
        available, streak, seconds_left = True, 1, 0
    else:
        elapsed = (now - last).total_seconds()
        available = elapsed >= DAILY_BONUS_INTERVAL_SECONDS
        if available:
            streak = (
                account.bonus_streak + 1
                if elapsed <= DAILY_BONUS_STREAK_WINDOW_SECONDS
                else 1
            )
            seconds_left = 0
        else:
            streak = max(1, account.bonus_streak)
            seconds_left = int(math.ceil(DAILY_BONUS_INTERVAL_SECONDS - elapsed))
    streak = min(max(1, streak), DAILY_BONUS_MAX_STREAK)
    amount = daily_bonus_amount(streak)
    return available, amount, streak, max(0, seconds_left)


def _bonus_streak(row: dict[str, Any]) -> int:
    """Seriyani ikki ustun nomidan ham oldi (``bonus_streak``/``streak_days``)."""
    try:
        old = int(row.get("bonus_streak") or 0)
    except (TypeError, ValueError):
        old = 0
    try:
        new = int(row.get("streak_days") or 0)
    except (TypeError, ValueError):
        new = 0
    return max(old, new)


def _bonus_last(row: dict[str, Any]) -> str:
    """Oxirgi bonus vaqti: ikki ustun nomidan eng so'nggisini beradi."""
    candidates = [
        str(row.get("last_bonus_at") or "").strip(),
        str(row.get("last_daily_claim") or "").strip(),
    ]
    picked = ""
    picked_moment = None
    for value in candidates:
        if not value:
            continue
        parsed = _parse_moment(value)
        if parsed is not None and (picked_moment is None or parsed > picked_moment):
            picked, picked_moment = value, parsed
    return picked or (candidates[0] or candidates[1] or "")


def _row_to_account(row: dict[str, Any]) -> UserAccount:
    raw_id = row.get(USERS_ID_COLUMN)
    if raw_id is None:
        raw_id = row["user_id"]
    return UserAccount(
        user_id=int(raw_id),
        username=str(row.get("username") or ""),
        full_name=str(row.get("full_name") or ""),
        coins=int(row.get("coins") or 0),
        total_purchased=int(row.get("total_purchased") or 0),
        games_played=int(row.get("games_played") or 0),
        wins=int(row.get("wins") or 0),
        bunker_wins=int(row.get("bunker_wins") or 0),
        mafia_wins=int(row.get("mafia_wins") or 0),
        spy_wins=int(row.get("spy_wins") or 0),
        alias_wins=int(row.get("alias_wins") or 0),
        bomb_wins=int(row.get("bomb_wins") or 0),
        referral_count=int(row.get("referral_count") or 0),
        last_bonus_at=_bonus_last(row),
        last_daily_claim=_bonus_last(row),
        bonus_streak=_bonus_streak(row),
        streak_days=_bonus_streak(row),
        is_blocked=bool(row.get("is_blocked")),
        block_reason=str(row.get("block_reason") or ""),
        role=str(row.get("role") or "user").strip().lower(),
        is_bot=bool(row.get("is_bot")),
        language_code=str(row.get("language_code") or "").strip(),
    )


GAME_WIN_COLUMNS: dict[str, str] = {
    "bunker": "bunker_wins",
    "mafia": "mafia_wins",
    "spy": "spy_wins",
    "spyfall": "spy_wins",
    "josus": "spy_wins",
    "alias": "alias_wins",
    "krokodil": "alias_wins",
    "bomb": "bomb_wins",
    "bomba": "bomb_wins",
}


def game_win_column(game_type: str) -> str:
    """O'yin turiga mos g'alaba ustunini qaytaradi."""
    key = str(game_type or "").strip().lower()
    return GAME_WIN_COLUMNS.get(key, "bunker_wins")


def _row_to_payment(row: dict[str, Any]) -> PaymentRequest:
    reviewed_by = row.get("reviewed_by")
    return PaymentRequest(
        id=str(row["id"]),
        user_id=int(row["user_id"]),
        username=str(row.get("username") or ""),
        full_name=str(row.get("full_name") or ""),
        package_coins=int(row.get("package_coins") or 0),
        price_uzs=int(row.get("price_uzs") or 0),
        receipt_file_id=str(row.get("receipt_file_id") or ""),
        status=str(row.get("status") or PENDING),
        reviewed_by=int(reviewed_by) if reviewed_by is not None else None,
        created_at=str(row.get("created_at") or ""),
    )


def _row_to_promo(row: dict[str, Any]) -> PromoCode:
    """Promo kod satrini o'qiydi; ustun nomlari sxemaga qarab farq qilishi mumkin."""
    return PromoCode(
        code=str(row.get("code") or row.get("promo_code") or ""),
        coins=int(
            row.get("coins")
            or row.get("reward_coins")
            or row.get("amount")
            or 0
        ),
        max_uses=int(row.get("max_uses") or row.get("uses") or 1),
        used_count=int(
            row.get("used_count")
            or row.get("current_uses")
            or row.get("uses_count")
            or 0
        ),
        created_at=str(row.get("created_at") or ""),
    )


def package_price(coins: int) -> int:
    """Paket narxini qaytaradi yoki xato beradi."""
    try:
        return COIN_PACKAGES[int(coins)]
    except (KeyError, TypeError, ValueError) as exc:
        raise EconomyError(f"Noma'lum tanga paketi: {coins!r}") from exc


def format_price(amount: int) -> str:
    """10000 -> ``10 000`` ko'rinishida formatlaydi."""
    return f"{int(amount):,}".replace(",", " ")


def player_rating(account: UserAccount) -> int:
    """O'yinchi reytingi: 1000 ball + har bir g'alaba uchun 50 ball."""
    return RATING_BASE + int(account.wins) * RATING_WIN_BONUS


def is_test_bot_id(user_id: Any) -> bool:
    """``/test_game`` virtual boti ID simi (``id >= 9000000000``)."""
    try:
        return int(user_id) >= TEST_BOT_ID_THRESHOLD
    except (TypeError, ValueError):
        return False


def is_rating_bot(account: Any) -> bool:
    """Reytingdan chiqariladigan hisob: soxta ID, ``is_bot`` yoki ``*bot*``.

    Faqat haqiqiy Telegram foydalanuvchilari reyting jadvaliga kiritiladi.
    """
    user_id = getattr(account, "user_id", 0)
    if is_test_bot_id(user_id):
        return True
    if bool(getattr(account, "is_bot", False)):
        return True
    username = str(getattr(account, "username", "") or "").lower()
    if "bot" in username:
        return True
    full_name = str(getattr(account, "full_name", "") or "").lower()
    if "bot" in full_name:
        return True
    return False


def referral_earnings(account: UserAccount) -> int:
    """Takliflar hisobiga ishlangan tangalar."""
    return int(account.referral_count) * REFERRAL_BONUS


@dataclass(frozen=True)
class ReferralResult:
    """Muvaffaqiyatli taklif natijasi."""

    inviter_id: int
    invited_id: int
    bonus: int


class EconomyStore:
    """Foydalanuvchi balansi, cheklar va boosterlarni boshqaradi."""

    def __init__(
        self,
        url: str | None = None,
        key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.url = (url if url is not None else os.getenv("SUPABASE_URL") or "").strip()
        # Backend yozuvlari admin huquqi bilan: service_role ustuvor —
        # anon kalit RLS'da `user_inventory` ga yozolmaydi.
        self.key = (
            key
            if key is not None
            else os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_KEY")
            or ""
        ).strip()
        self._client = client
        self._lock = threading.RLock()
        # user_id -> (monotonic vaqt, hisob). Faqat Supabase rejimida ishlaydi.
        self._profile_cache: dict[int, tuple[float, UserAccount]] = {}
        # (monotonic vaqt, jami foydalanuvchilar soni).
        self._count_cache: tuple[float, int] | None = None
        self._users: dict[int, dict[str, Any]] = {}
        self._payments: dict[str, dict[str, Any]] = {}
        self._boosters: set[tuple[str, int, str]] = set()
        self._finished_rooms: set[str] = set()
        self._history: list[dict[str, Any]] = []
        # taklif qilingan id -> taklif qilgan id
        self._referrals: dict[int, int] = {}
        self._promo_codes: dict[str, dict[str, Any]] = {}
        self._promo_redemptions: set[tuple[str, int]] = set()
        self._mission_claims: dict[int, set[str]] = {}

    @property
    def enabled(self) -> bool:
        return self._client is not None or bool(self.url and self.key)

    # ------------------------------------------------------------------
    # Profil keshi
    # ------------------------------------------------------------------
    def _cache_drop(self, user_id: int) -> None:
        """Keshdagi yozuvni o'chiradi (har qanday yozuvdan keyin)."""
        self._profile_cache.pop(int(user_id), None)

    def _cache_clear(self) -> None:
        self._profile_cache.clear()

    def _cached_account(self, user_id: int) -> UserAccount | None:
        """Keshdagi yangi (TTL ichidagi) hisobni qaytaradi yoki ``None``."""
        if not self.enabled:
            return None
        entry = self._profile_cache.get(int(user_id))
        if entry is None:
            return None
        stamp, account = entry
        if time.monotonic() - stamp > PROFILE_CACHE_TTL:
            self._profile_cache.pop(int(user_id), None)
            return None
        return account

    def _store_cached(self, account: UserAccount) -> None:
        if not self.enabled:
            return
        self._profile_cache[int(account.user_id)] = (
            time.monotonic(),
            account,
        )

    def peek_account(self, user_id: int) -> UserAccount | None:
        """Faqat keshdan o'qiydi — bazaga so'rov yubormaydi."""
        with self._lock:
            return self._cached_account(int(user_id))

    def invalidate_user(self, user_id: int | None = None) -> None:
        """Keshni tozalaydi (bitta foydalanuvchi yoki butunlay)."""
        with self._lock:
            if user_id is None:
                self._cache_clear()
            else:
                self._cache_drop(user_id)

    @property
    def client(self) -> Any:
        if self._client is None:
            from supabase import create_client

            self._client = create_client(self.url, self.key)
        return self._client

    # ------------------------------------------------------------------
    # Pastki darajadagi o'qish/yozish
    # ------------------------------------------------------------------
    def _select_one(self, table: str, **filters: Any) -> dict[str, Any] | None:
        query = self.client.table(table).select("*")
        for column, value in filters.items():
            query = query.eq(column, value)
        rows = query.limit(1).execute().data or []
        return dict(rows[0]) if rows else None

    def _update_user_row(self, user_id: int, changes: dict[str, Any]) -> None:
        self._cache_drop(user_id)
        # ``updated_at`` ataylab qo'shilmaydi: Supabase sxemasida bu ustun
        # bo'lmasa PGRST204 xatosi chiqadi. Qolgan ustunlar ham xavfsiz
        # yoziladi — yetishmayotganlari so'rovdan avtomatik olib tashlanadi.
        safe_update(
            self.client,
            USERS_TABLE,
            dict(changes),
            {USERS_ID_COLUMN: int(user_id)},
        )

    # ------------------------------------------------------------------
    # Foydalanuvchilar
    # ------------------------------------------------------------------
    def ensure_user(
        self,
        user_id: int,
        username: str = "",
        full_name: str = "",
        *,
        is_bot: bool = False,
        known_missing: bool = False,
    ) -> UserAccount:
        """Foydalanuvchini yaratadi yoki ismini yangilab, hisobni qaytaradi.

        ``is_bot=True`` bo'lsa hisob ``is_bot`` belgisi bilan yoziladi va
        reytingga kiritilmaydi (``/test_game`` virtual botlari uchun).

        ``known_missing=True`` — chaqiruvchi bu foydalanuvchi bazada yo'qligini
        allaqachon biladi (masalan, ``/start`` oldidan ``find_user`` ishlagan):
        SELECT o'tkazib yuboriladi va darhol INSERT qilinadi. Shu bilan yangi
        o'yinchiga javob bitta so'rov tezroq ketadi.
        """
        uid = int(user_id)
        if uid <= 0:
            raise EconomyError("Foydalanuvchi id musbat bo'lishi kerak")
        username = (username or "").strip()
        full_name = (full_name or "").strip()
        # Test ID simiga kirgan har qanday hisob avtomatik bot hisoblanadi.
        is_bot = bool(is_bot) or is_test_bot_id(uid)

        with self._lock:
            if not self.enabled:
                row = self._users.get(uid)
                if row is None:
                    row = {
                        USERS_ID_COLUMN: uid,
                        "username": username,
                        "full_name": full_name,
                        "coins": START_COINS,
                        "total_purchased": 0,
                        "games_played": 0,
                        "wins": 0,
                        "bunker_wins": 0,
                        "mafia_wins": 0,
                        "spy_wins": 0,
                        "alias_wins": 0,
                        "bomb_wins": 0,
                        "referral_count": 0,
                        "last_bonus_at": "",
                        "last_daily_claim": "",
                        "bonus_streak": 0,
                        "streak_days": 0,
                        "role": "user",
                        "is_blocked": False,
                        "block_reason": "",
                        "is_bot": is_bot,
                        "language_code": "",
                        "created_at": _now(),
                    }
                    self._users[uid] = row
                else:
                    if username:
                        row["username"] = username
                    if full_name:
                        row["full_name"] = full_name
                    if is_bot:
                        row["is_bot"] = True
                return _row_to_account(row)

            row = None if known_missing else self._select_one(
                USERS_TABLE, **{USERS_ID_COLUMN: uid}
            )
            if row is None:
                row = {
                    USERS_ID_COLUMN: uid,
                    "username": username,
                    "full_name": full_name,
                    "coins": START_COINS,
                    "total_purchased": 0,
                    "games_played": 0,
                    "wins": 0,
                    "bunker_wins": 0,
                    "mafia_wins": 0,
                    "spy_wins": 0,
                    "alias_wins": 0,
                    "bomb_wins": 0,
                    "referral_count": 0,
                    "last_bonus_at": "",
                    "last_daily_claim": "",
                    "bonus_streak": 0,
                    "streak_days": 0,
                    "role": "user",
                    "is_blocked": False,
                    "is_bot": is_bot,
                    "language_code": "",
                    "created_at": _now(),
                }
                try:
                    safe_insert(self.client, USERS_TABLE, row)
                except Exception:
                    # Parallel yaratilgan bo'lsa, mavjud yozuvni qayta o'qiymiz.
                    row = self._select_one(USERS_TABLE, **{USERS_ID_COLUMN: uid})
                    if row is None:
                        raise
                self._cache_drop(uid)
                self._count_cache = None
            else:
                changes: dict[str, Any] = {}
                if username and username != row.get("username"):
                    changes["username"] = username
                if full_name and full_name != row.get("full_name"):
                    changes["full_name"] = full_name
                if is_bot and not bool(row.get("is_bot")):
                    changes["is_bot"] = True
                if changes:
                    self._update_user_row(uid, changes)
                    row.update(changes)
            return _row_to_account(row)

    def get_user(self, user_id: int) -> UserAccount:
        """Hisobni qaytaradi; yo'q bo'lsa nol balans bilan yaratadi."""
        return self.ensure_user(user_id)

    def has_user(self, user_id: int) -> bool:
        """Foydalanuvchi bazada allaqachon bormi (yangi yozuv yaratmasdan)."""
        uid = int(user_id)
        with self._lock:
            if not self.enabled:
                return uid in self._users
            if self._cached_account(uid) is not None:
                return True
            row = self._select_one(USERS_TABLE, **{USERS_ID_COLUMN: uid})
            if row is None:
                return False
            self._store_cached(_row_to_account(row))
            return True

    def get_role(self, user_id: int) -> str:
        """Foydalanuvchi rolini qaytaradi (``admin`` yoki ``user``).

        Rol profil keshidan olinadi, shuning uchun ``/start`` dagi
        ``is_admin`` tekshiruvi har safar Supabase'ga so'rov yubormaydi.
        Rol o'zgartirilsa yozuv keshni darhol tozalaydi; rol boshqa jarayonda
        o'zgartirilsa, kechikish ``PROFILE_CACHE_TTL`` dan oshmaydi.
        """
        uid = int(user_id)
        if not self.enabled:
            with self._lock:
                row = self._users.get(uid)
            return str((row or {}).get("role") or "user").strip().lower()
        account = self.find_user(uid)
        if account is None:
            return "user"
        return str(account.role or "user").strip().lower()

    def is_admin_user(self, user_id: int) -> bool:
        """Bloklanmagan adminni tekshiradi."""
        return self.get_role(user_id) == "admin" and not self.is_blocked(user_id)

    def is_blocked(self, user_id: int) -> bool:
        """Foydalanuvchi bloklanganmi (yangi yozuv yaratmasdan)."""
        account = self.find_user(user_id)
        return bool(account is not None and account.is_blocked)

    def set_blocked(
        self, user_id: int, blocked: bool, reason: str = ""
    ) -> UserAccount:
        """Foydalanuvchini sabab bilan bloklaydi yoki blokdan çiqaradi."""
        account = self.find_user(user_id)
        if account is None:
            raise EconomyError("Foydalanuvçi topilmadi")
        uid = account.user_id
        reason_text = str(reason or "").strip()[:500] if blocked else ""
        changes = {"is_blocked": bool(blocked), "block_reason": reason_text}
        with self._lock:
            if not self.enabled:
                self._users[uid].update(changes)
                return _row_to_account(self._users[uid])
            self._update_user_row(uid, changes)
        return replace(account, **changes)

    def set_role(self, user_id: int, role: str) -> UserAccount:
        """Foydalanuvchi rolini ``admin`` yoki ``user`` qiladi."""
        new_role = str(role or "").strip().lower()
        if new_role not in {"admin", "user"}:
            raise EconomyError("Rol faqat admin yoki user bölişi mumkin")
        account = self.find_user(user_id)
        if account is None:
            raise EconomyError("Foydalanuvçi topilmadi")
        uid = account.user_id
        with self._lock:
            if not self.enabled:
                self._users[uid]["role"] = new_role
                return _row_to_account(self._users[uid])
            self._update_user_row(uid, {"role": new_role})
        return replace(account, role=new_role)

    def set_language(self, user_id: int, language: str) -> UserAccount:
        """Foydalanuvchi tilini ``users.language_code`` ga saqlaydi."""
        from core.i18n import normalize_language

        normalized = normalize_language(language)
        account = self.find_user(user_id)
        if account is None:
            account = self.ensure_user(user_id)
        uid = account.user_id
        with self._lock:
            if not self.enabled:
                self._users[uid]["language_code"] = normalized
                return _row_to_account(self._users[uid])
            self._update_user_row(uid, {"language_code": normalized})
        return replace(account, language_code=normalized)

    def find_user(self, user_id: int) -> UserAccount | None:
        """Foydalanuvchini yaratmasdan qaytaradi; yo'q bo'lsa ``None``.

        Natija qisqa muddatli keshga yoziladi, shuning uchun /start va menyu
        tugmalari takror bosilganda Supabase'ga qayta so'rov ketmaydi.
        """
        uid = int(user_id)
        with self._lock:
            if not self.enabled:
                row = self._users.get(uid)
                return _row_to_account(row) if row is not None else None
            cached = self._cached_account(uid)
            if cached is not None:
                return cached
            row = self._select_one(USERS_TABLE, **{USERS_ID_COLUMN: uid})
            if row is None:
                return None
            account = _row_to_account(row)
            self._store_cached(account)
            return account

    def account_for(
        self,
        user_id: int,
        username: str = "",
        full_name: str = "",
    ) -> UserAccount:
        """Hisobni keshdan yoki bazadan qaytaradi; yo'q bo'lsa yaratadi.

        Menyu tugmalari (Profil, Do'kon) shu yo'l bilan o'qiydi: kesh yangi
        bo'lsa Supabase'ga umuman so'rov ketmaydi.
        """
        account = self.find_user(user_id)
        if account is not None:
            return account
        return self.ensure_user(user_id, username, full_name)

    def count_users(self) -> int:
        """Bazadagi jami foydalanuvchilar soni (30 sekundlik kesh bilan).

        Bu butun jadvalni o'qiydigan og'ir so'rov; admin bildirishnomasi har
        yangi o'yinchida uni takrorlamasligi uchun natija keshlanadi.
        """
        with self._lock:
            if not self.enabled:
                return len(self._users)
            if self._count_cache is not None:
                stamp, value = self._count_cache
                if time.monotonic() - stamp <= USER_COUNT_TTL:
                    return value
            rows = (
                self.client.table(USERS_TABLE)
                .select(USERS_ID_COLUMN)
                .execute()
                .data
                or []
            )
            total = len({int(row[USERS_ID_COLUMN]) for row in rows})
            self._count_cache = (time.monotonic(), total)
            return total

    def recent_users(self, limit: int = 10, offset: int = 0) -> list[UserAccount]:
        """Eng oxirgi qo'shilgan foydalanuvchilarni qaytaradi."""
        limit = min(max(1, int(limit)), 100)
        offset = max(0, int(offset))
        with self._lock:
            if not self.enabled:
                rows = sorted(
                    self._users.values(),
                    key=lambda row: str(row.get("created_at") or ""),
                    reverse=True,
                )[offset : offset + limit]
                return [_row_to_account(row) for row in rows]
            query = self.client.table(USERS_TABLE).select("*")
            try:
                response = (
                    query.order("created_at", desc=True)
                    .range(offset, offset + limit - 1)
                    .execute()
                )
                rows = response.data or []
            except Exception:
                # Eski/test mijozi ``order`` yoki ``range``ni qo'llamasligi mumkin.
                logger.info("users jadvalini sahifalab o'qib bo'lmadi, zaxira usul")
                rows = query.execute().data or []
                rows.sort(
                    key=lambda row: str(row.get("created_at") or ""),
                    reverse=True,
                )
                rows = rows[offset : offset + limit]
        return [_row_to_account(row) for row in rows]

    def top_users(self, limit: int = 10) -> list[UserAccount]:
        """Eng ko'p g'alaba qozongan o'yinchilarni qaytaradi.

        Test botlar qat'iy filtrlanadi: ``id < 9000000000``,
        ``is_bot`` aniq ``False`` bo'lishi va username ``%bot%`` emas.
        Faqat haqiqiy Telegram foydalanuvchilari reytingga kiritiladi.
        """
        limit = max(1, int(limit))
        with self._lock:
            if not self.enabled:
                rows = list(self._users.values())
            else:
                query = self.client.table(USERS_TABLE).select("*")
                # Eskirgan test mijozlari ``lt`` ni qo'llamasligi mumkin.
                if hasattr(query, "lt"):
                    query = query.lt(USERS_ID_COLUMN, TEST_BOT_ID_THRESHOLD)
                rows = query.execute().data or []
        accounts = [
            account
            for account in (_row_to_account(row) for row in rows)
            if not is_rating_bot(account)
        ]
        accounts.sort(
            key=lambda acc: (player_rating(acc), acc.coins),
            reverse=True,
        )
        return accounts[:limit]

    # ------------------------------------------------------------------
    # Referallar
    # ------------------------------------------------------------------
    def register_referral(
        self,
        inviter_id: int,
        invited_id: int,
        bonus: int = REFERRAL_BONUS,
    ) -> ReferralResult | None:
        """Yangi taklifni yozib, taklif qiluvchiga tanga beradi.

        O'zini taklif qilish, mavjud bo'lmagan taklif qiluvchi va takroriy
        takliflar ``None`` qaytaradi (tanga qo'shilmaydi).
        """
        inviter = int(inviter_id)
        invited = int(invited_id)
        bonus = int(bonus)
        if inviter <= 0 or invited <= 0 or inviter == invited or bonus <= 0:
            return None
        try:
            return self._register_referral(inviter, invited, bonus)
        except Exception:
            # Baza xatosi /start oqimini hech qachon to'xtatmasligi kerak.
            logger.exception("Taklif yozilmadi: %s -> %s", inviter, invited)
            return None

    def _register_referral(
        self, inviter: int, invited: int, bonus: int
    ) -> ReferralResult | None:
        """``register_referral`` ning xato bermaydigan ichki qismi."""
        with self._lock:
            if self.enabled:
                inviter_row = self._select_one(
                    USERS_TABLE, **{USERS_ID_COLUMN: inviter}
                )
                if inviter_row is None:
                    return None
                if not self._insert_referral(inviter, invited, bonus):
                    return None
                inviter_account = _row_to_account(inviter_row)
            else:
                if inviter not in self._users:
                    return None
                if invited in self._referrals:
                    return None
                self._referrals[invited] = inviter
                inviter_account = _row_to_account(self._users[inviter])

            new_coins = inviter_account.coins + bonus
            new_count = inviter_account.referral_count + 1
            if self.enabled:
                # Bitta so'rovda balans va taklif soni yangilanadi.
                self._update_user_row(
                    inviter,
                    {"coins": new_coins, "referral_count": new_count},
                )
                self._store_cached(
                    replace(
                        inviter_account,
                        coins=new_coins,
                        referral_count=new_count,
                    )
                )
            else:
                row = self._users[inviter]
                row["coins"] = new_coins
                row["referral_count"] = new_count
        return ReferralResult(inviter_id=inviter, invited_id=invited, bonus=bonus)

    def _insert_referral(self, inviter: int, invited: int, bonus: int) -> bool:
        """``referrals`` jadvaliga yozadi; xatoni yutib ``bool`` qaytaradi.

        Takroriy taklif (``invited_id`` unikal) ``False`` qaytaradi. Jadval
        yoki sxema bilan bog'liq xatolar taklifni bekor qilmaydi: taklif
        qiluvchi baribir mukofot oladi (``/start`` faqat yangi foydalanuvchi
        uchun bir marta ishlaydi, shuning uchun ikki marta berilmaydi).
        """
        row = {
            "inviter_id": inviter,
            "invited_id": invited,
            "bonus": bonus,
            "created_at": _now(),
        }
        try:
            safe_insert(self.client, REFERRALS_TABLE, row)
            return True
        except Exception:
            logger.warning(
                "Taklif yozuvi saqlanmadi (%s -> %s), holat tekshiriladi",
                inviter,
                invited,
                exc_info=True,
            )
        try:
            existing = self._select_one(
                REFERRALS_TABLE, invited_id=invited
            )
        except Exception:
            logger.warning(
                "referrals jadvalini o'qib bo'lmadi — taklif bir marta "
                "hisoblanadi",
                exc_info=True,
            )
            return True
        if existing is not None:
            logger.info("Taklif allaqachon yozilgan: %s", invited)
            return False
        return True

    def referral_count(self, user_id: int) -> int:
        """Foydalanuvchi taklif qilgan do'stlar soni."""
        return self.ensure_user(user_id).referral_count

    def add_coins(
        self,
        user_id: int,
        amount: int,
        *,
        purchased: bool = False,
    ) -> UserAccount:
        """Balansga tanga qo'shadi (admin sovg'asi yoki to'lov)."""
        if int(amount) <= 0:
            raise EconomyError("Qo'shiladigan tanga miqdori musbat bo'lishi kerak")
        uid = int(user_id)
        with self._lock:
            account = self.ensure_user(uid)
            new_coins = account.coins + int(amount)
            new_purchased = account.total_purchased + (int(amount) if purchased else 0)
            if not self.enabled:
                row = self._users[uid]
                row["coins"] = new_coins
                row["total_purchased"] = new_purchased
                return _row_to_account(row)
            self._update_user_row(
                uid,
                {"coins": new_coins, "total_purchased": new_purchased},
            )
            return replace(
                account, coins=new_coins, total_purchased=new_purchased
            )

    def spend_coins(self, user_id: int, amount: int) -> UserAccount:
        """Balansdan tanga yechadi; yetmasa :class:`InsufficientCoinsError`."""
        if int(amount) <= 0:
            raise EconomyError("Yechiladigan tanga miqdori musbat bo'lishi kerak")
        uid = int(user_id)
        with self._lock:
            account = self.ensure_user(uid)
            if account.coins < int(amount):
                raise InsufficientCoinsError(
                    f"Balansda yetarli tanga yo'q: {account.coins} ta bor, "
                    f"{int(amount)} ta kerak"
                )
            new_coins = account.coins - int(amount)
            if not self.enabled:
                row = self._users[uid]
                row["coins"] = new_coins
                return _row_to_account(row)
            self._update_user_row(uid, {"coins": new_coins})
            return replace(account, coins=new_coins)

    # ------------------------------------------------------------------
    # To'lov cheklari
    # ------------------------------------------------------------------
    def create_payment(
        self,
        user_id: int,
        username: str,
        full_name: str,
        package_coins: int,
        receipt_file_id: str,
    ) -> PaymentRequest:
        """Yangi PENDING chek yaratadi."""
        coins = int(package_coins)
        price = package_price(coins)
        if not (receipt_file_id or "").strip():
            raise EconomyError("Chek fayli identifikatori bo'sh")
        account = self.ensure_user(user_id, username, full_name)
        request_id = uuid.uuid4().hex[:12]
        row = {
            "id": request_id,
            "user_id": account.user_id,
            "username": account.username or username,
            "full_name": account.full_name or full_name,
            "package_coins": coins,
            "price_uzs": price,
            "receipt_file_id": receipt_file_id.strip(),
            "status": PENDING,
            "created_at": _now(),
        }
        with self._lock:
            # Xotirada har doim saqlanadi: Supabase xatosi (masalan PGRST204)
            # chekni adminga yuborishga to'sqinlik qilmasligi kerak.
            self._payments[request_id] = row
            if self.enabled:
                try:
                    safe_insert(self.client, PAYMENTS_TABLE, row)
                except Exception:
                    logger.exception(
                        "Chekni Supabase'ga saqlab bo'lmadi, xotirada saqlandi: %s",
                        request_id,
                    )
        return _row_to_payment(row)

    def get_payment(self, request_id: str) -> PaymentRequest | None:
        """Chekni id bo'yicha qaytaradi (avval xotiradan, keyin Supabase'dan)."""
        key = str(request_id)
        with self._lock:
            row = self._payments.get(key)
            if row is not None:
                return _row_to_payment(row)
            if not self.enabled:
                return None
            row = self._select_one(PAYMENTS_TABLE, id=key)
            if row is None:
                return None
            self._payments[key] = dict(row)
            return _row_to_payment(row)

    def list_pending_payments(self) -> list[PaymentRequest]:
        """Tasdiqlanmagan (PENDING) cheklarni eski tartibda qaytaradi."""
        with self._lock:
            if not self.enabled:
                rows = [
                    row
                    for row in self._payments.values()
                    if str(row.get("status")) == PENDING
                ]
            else:
                rows = (
                    self.client.table(PAYMENTS_TABLE)
                    .select("*")
                    .eq("status", PENDING)
                    .execute()
                    .data
                    or []
                )
            by_id: dict[str, dict[str, Any]] = {
                str(row.get("id")): dict(row) for row in rows
            }
            for key, row in self._payments.items():
                if str(row.get("status")) == PENDING and key not in by_id:
                    by_id[key] = row
            rows = list(by_id.values())
        payments = [_row_to_payment(row) for row in rows]
        payments.sort(key=lambda payment: payment.created_at)
        return payments

    def _set_payment_status(self, request_id: str, status: str, admin_id: int) -> None:
        key = str(request_id)
        changes = {
            "status": status,
            "reviewed_by": int(admin_id),
            "reviewed_at": _now(),
        }
        row = self._payments.get(key)
        if row is not None:
            row.update(changes)
        if not self.enabled:
            return
        try:
            safe_update(
                self.client,
                PAYMENTS_TABLE,
                dict(changes),
                {"id": key},
            )
        except Exception:
            # Baza xatosi admin amalini to'xtatmasin: xotiradagi nusxa yangilandi.
            logger.exception(
                "Chek holatini Supabase'da yangilab bo'lmadi: %s", key
            )

    def approve_payment(self, request_id: str, admin_id: int) -> PaymentRequest:
        """PENDING chekni tasdiqlaydi va tangalarni bir marta qo'shadi."""
        with self._lock:
            payment = self.get_payment(request_id)
            if payment is None:
                raise EconomyError("Chek topilmadi")
            if payment.status != PENDING:
                raise EconomyError(f"Chek allaqachon ko'rib chiqilgan: {payment.status}")
            self._set_payment_status(payment.id, APPROVED, admin_id)
            try:
                self.add_coins(payment.user_id, payment.package_coins, purchased=True)
            except Exception:
                # Tanga qo'shilmasa, chekni qayta ko'rib chiqish uchun PENDING'ga qaytaramiz.
                self._set_payment_status(payment.id, PENDING, admin_id)
                raise
            updated = self.get_payment(payment.id)
            if updated is None:
                raise EconomyError("Tasdiqlangan chekni qayta o'qib bo'lmadi")
            return updated

    def reject_payment(self, request_id: str, admin_id: int) -> PaymentRequest:
        """PENDING chekni rad etadi."""
        with self._lock:
            payment = self.get_payment(request_id)
            if payment is None:
                raise EconomyError("Chek topilmadi")
            if payment.status != PENDING:
                raise EconomyError(f"Chek allaqachon ko'rib chiqilgan: {payment.status}")
            self._set_payment_status(payment.id, REJECTED, admin_id)
            updated = self.get_payment(payment.id)
            if updated is None:
                raise EconomyError("Rad etilgan chekni qayta o'qib bo'lmadi")
            return updated

    # ------------------------------------------------------------------
    # Boosterlar
    # ------------------------------------------------------------------
    def has_booster(self, room_code: str, user_id: int, booster: str) -> bool:
        """O'yinchi shu xonada boosterni ishlatganmi."""
        key = (str(room_code).strip().upper(), int(user_id), str(booster))
        with self._lock:
            if not self.enabled:
                return key in self._boosters
            row = self._select_one(
                BOOSTERS_TABLE,
                room_code=key[0],
                user_id=key[1],
                booster=key[2],
            )
            return row is not None

    def record_booster(self, room_code: str, user_id: int, booster: str) -> bool:
        """Booster ishlatilganini yozadi. Avval ishlatilgan bo'lsa ``False``."""
        key = (str(room_code).strip().upper(), int(user_id), str(booster))
        with self._lock:
            if self.has_booster(*key):
                return False
            if not self.enabled:
                self._boosters.add(key)
                return True
            safe_insert(
                self.client,
                BOOSTERS_TABLE,
                {
                    "room_code": key[0],
                    "user_id": key[1],
                    "booster": key[2],
                    "used_at": _now(),
                },
            )
            return True

    # ------------------------------------------------------------------
    # Kunlik bonus
    # ------------------------------------------------------------------
    def daily_bonus_status(
        self, user_id: int, now: datetime | None = None
    ) -> DailyBonusStatus:
        """Kunlik bonus holati: mavjudmi, qancha va qancha vaqt qoldi."""
        uid = int(user_id)
        moment = now or _now_moment()
        with self._lock:
            account = self.ensure_user(uid)
        available, amount, streak, seconds_left = _daily_bonus_plan(account, moment)
        return DailyBonusStatus(
            available=available,
            amount=amount,
            streak=streak,
            seconds_left=seconds_left,
            next_amount=next_daily_bonus_amount(streak),
            streak_days=streak,
            last_daily_claim=account.last_bonus_at,
        )

    def claim_daily_bonus(
        self, user_id: int, now: datetime | None = None
    ) -> DailyBonusClaim:
        """Kunlik bonusni beradi; 24 soat o'tmagan bo'lsa xato ko'taradi."""
        uid = int(user_id)
        moment = now or _now_moment()
        with self._lock:
            account = self.ensure_user(uid)
            available, amount, streak, seconds_left = _daily_bonus_plan(
                account, moment
            )
            if not available:
                raise EconomyError(
                    "Kunlik bonus allaqachon olingan. "
                    f"Keyingi bonus {_format_wait(seconds_left)}."
                )
            claimed_at = moment.isoformat()
            if not self.enabled:
                row = self._users[uid]
                row["last_bonus_at"] = claimed_at
                row["last_daily_claim"] = claimed_at
                row["bonus_streak"] = streak
                row["streak_days"] = streak
            else:
                # Ikki nom ham yoziladi: eski baza (`bonus_streak`) ham,
                # yangi baza (`streak_days`) ham shu yerda yangilanadi.
                self._update_user_row(
                    uid,
                    {
                        "last_bonus_at": claimed_at,
                        "last_daily_claim": claimed_at,
                        "bonus_streak": streak,
                        "streak_days": streak,
                    },
                )
            updated = self.add_coins(uid, amount)
        return DailyBonusClaim(
            amount=amount,
            streak=streak,
            account=updated,
            next_amount=next_daily_bonus_amount(streak),
            streak_days=streak,
            last_daily_claim=claimed_at,
        )

    # ------------------------------------------------------------------
    # Promo kodlar
    # ------------------------------------------------------------------
    def create_promo_code(
        self,
        code: str,
        coins: int,
        max_uses: int = 1,
        created_by: int | None = None,
    ) -> PromoCode:
        """Yangi promo kod yaratadi (faqat admin panel ishlatadi)."""
        normalized = normalize_promo_code(code)
        amount = int(coins)
        uses = int(max_uses)
        if amount <= 0:
            raise EconomyError("Promo kod mukofoti musbat bo'lishi kerak")
        if uses < 1:
            raise EconomyError("Promo kod kamida bir marta ishlatilishi kerak")
        # Supabase jadvallarida ustun nomlari farq qilishi mumkin
        # (coins/reward_coins, max_uses/uses, used_count/current_uses).
        # Ikkala nom ham yuboriladi — mavjud bo'lmagani avtomatik olib tashlanadi.
        row: dict[str, Any] = {
            "code": normalized,
            "coins": amount,
            "reward_coins": amount,
            "max_uses": uses,
            "uses": uses,
            "used_count": 0,
            "current_uses": 0,
            "created_by": int(created_by) if created_by else None,
            "created_at": _now(),
        }
        with self._lock:
            # Kod avval xotirada saqlanadi — Supabase xatosi promokodni
            # yo'qotmasligi kerak.
            if normalized in self._promo_codes:
                raise EconomyError("Bu promo kod allaqachon mavjud")
            self._promo_codes[normalized] = row
            if self.enabled:
                try:
                    if (
                        self._select_one(PROMO_CODES_TABLE, code=normalized)
                        is not None
                    ):
                        self._promo_codes.pop(normalized, None)
                        raise EconomyError("Bu promo kod allaqachon mavjud")
                    safe_insert(self.client, PROMO_CODES_TABLE, row)
                except EconomyError:
                    raise
                except Exception:
                    logger.exception(
                        "Promo kodni Supabase'ga saqlab bo'lmadi, xotirada qoldi: %s",
                        normalized,
                    )
        return _row_to_promo(row)

    def get_promo_code(self, code: str) -> PromoCode | None:
        """Kod bo'yicha promo kodni qaytaradi (avval xotiradan)."""
        normalized = normalize_promo_code(code)
        with self._lock:
            row = self._promo_codes.get(normalized)
            if row is not None:
                return _row_to_promo(row)
            if not self.enabled:
                return None
            try:
                row = self._select_one(PROMO_CODES_TABLE, code=normalized)
            except Exception:
                logger.exception("Promo kodni Supabase'dan o'qib bo'lmadi")
                return None
            if row is not None:
                self._promo_codes[normalized] = dict(row)
                return _row_to_promo(row)
        return None

    def list_promo_codes(self, limit: int = 10) -> list[PromoCode]:
        """Oxirgi yaratilgan promo kodlar (admin panel uchun)."""
        with self._lock:
            rows = list(self._promo_codes.values())
            if self.enabled:
                try:
                    remote = (
                        self.client.table(PROMO_CODES_TABLE)
                        .select("*")
                        .execute()
                        .data
                        or []
                    )
                except Exception:
                    logger.exception("Promo kodlarni Supabase'dan o'qib bo'lmadi")
                    remote = []
                known = {str(row.get("code")) for row in rows}
                rows.extend(
                    row for row in remote if str(row.get("code")) not in known
                )
        codes = [_row_to_promo(row) for row in rows]
        codes.sort(key=lambda promo: promo.created_at, reverse=True)
        return codes[: max(1, int(limit))]

    def has_redeemed_promo(self, user_id: int, code: str) -> bool:
        """Foydalanuvchi bu kodni allaqachon ishlatganmi."""
        normalized = normalize_promo_code(code)
        uid = int(user_id)
        with self._lock:
            if (normalized, uid) in self._promo_redemptions:
                return True
            if not self.enabled:
                return False
            try:
                row = self._select_one(
                    PROMO_REDEMPTIONS_TABLE, code=normalized, user_id=uid
                )
            except Exception:
                logger.exception(
                    "Promo kod ishlatilganini tekshirib bo'lmadi: %s / %s",
                    normalized,
                    uid,
                )
                return False
            return row is not None

    def redeem_promo_code(self, user_id: int, code: str) -> PromoRedemption:
        """Promo kodni ishlatib, tangalarni qo'shadi."""
        normalized = normalize_promo_code(code)
        uid = int(user_id)
        with self._lock:
            promo = self.get_promo_code(normalized)
            if promo is None:
                raise EconomyError("Bunday promo kod topilmadi")
            if promo.used_count >= promo.max_uses:
                raise EconomyError("Promo kod ishlatish limiti tugagan")
            if self.has_redeemed_promo(uid, normalized):
                raise EconomyError("Bu promo kodni allaqachon ishlatgansiz")

            # Xotira har doim yangilanadi: Supabase xatosi kodni ishlatishga
            # to'sqinlik qilmasligi kerak.
            self._promo_redemptions.add((normalized, uid))
            memory_row = self._promo_codes.setdefault(
                normalized,
                {
                    "code": normalized,
                    "coins": promo.coins,
                    "max_uses": promo.max_uses,
                    "used_count": promo.used_count,
                    "created_at": promo.created_at,
                },
            )
            memory_row["used_count"] = promo.used_count + 1
            if self.enabled:
                try:
                    safe_insert(
                        self.client,
                        PROMO_REDEMPTIONS_TABLE,
                        {
                            "code": normalized,
                            "user_id": uid,
                            "coins": promo.coins,
                            "reward_coins": promo.coins,
                            "redeemed_at": _now(),
                        },
                    )
                except Exception:
                    logger.exception(
                        "Promo kod ishlatilishini Supabase'ga yozib bo'lmadi: %s / %s",
                        normalized,
                        uid,
                    )
                try:
                    safe_update(
                        self.client,
                        PROMO_CODES_TABLE,
                        {
                            "used_count": promo.used_count + 1,
                            "current_uses": promo.used_count + 1,
                        },
                        {"code": normalized},
                    )
                except Exception:
                    logger.exception(
                        "Promo kod hisoblagichini yangilab bo'lmadi: %s",
                        normalized,
                    )
            updated = self.add_coins(uid, promo.coins)
        return PromoRedemption(code=normalized, coins=promo.coins, account=updated)

    # ------------------------------------------------------------------
    # Missiya mukofotlari
    # ------------------------------------------------------------------
    def claimed_missions(self, user_id: int) -> set[str]:
        """Foydalanuvchi mukofotini olgan missiyalar kalitlari."""
        uid = int(user_id)
        with self._lock:
            claimed = set(self._mission_claims.get(uid, set()))
            if not self.enabled:
                return claimed
            try:
                rows = (
                    self.client.table(MISSIONS_TABLE)
                    .select("mission")
                    .eq("user_id", uid)
                    .execute()
                    .data
                    or []
                )
            except Exception:
                logger.exception(
                    "Missiya mukofotlarini Supabase'dan o'qib bo'lmadi: %s", uid
                )
                return claimed
        return claimed | {
            str(row["mission"]) for row in rows if row.get("mission")
        }

    def claim_mission_reward(
        self, user_id: int, mission: str, reward: int
    ) -> UserAccount:
        """Missiya mukofotini bir marta beradi."""
        key = str(mission or "").strip()
        amount = int(reward)
        uid = int(user_id)
        if not key:
            raise EconomyError("Missiya kaliti bo'sh")
        if amount <= 0:
            raise EconomyError("Missiya mukofoti musbat bo'lishi kerak")
        with self._lock:
            if key in self.claimed_missions(uid):
                raise EconomyError("Bu missiya mukofoti allaqachon olingan")
            # Mukofot avval xotirada belgilanadi — Supabase xatosi uni
            # ikkinchi marta olishga yo'l qo'ymasligi kerak.
            self._mission_claims.setdefault(uid, set()).add(key)
            if self.enabled:
                try:
                    safe_insert(
                        self.client,
                        MISSIONS_TABLE,
                        {"user_id": uid, "mission": key, "claimed_at": _now()},
                    )
                except Exception:
                    logger.exception(
                        "Missiya mukofotini Supabase'ga yozib bo'lmadi, xotirada qoldi: %s / %s",
                        key,
                        uid,
                    )
            return self.add_coins(uid, amount)

    # ------------------------------------------------------------------
    # Statistika
    # ------------------------------------------------------------------
    def stats(self, *, active_rooms: int = 0, total_rooms: int = 0) -> dict[str, int]:
        """Admin panel uchun umumiy ko'rsatkichlar."""
        with self._lock:
            if not self.enabled:
                rows = list(self._users.values())
            else:
                rows = self.client.table(USERS_TABLE).select(
                    f"{USERS_ID_COLUMN}, coins, total_purchased"
                ).execute().data or []
            return {
                "users": len(rows),
                "coins_in_balance": sum(int(row.get("coins") or 0) for row in rows),
                "coins_purchased": sum(
                    int(row.get("total_purchased") or 0) for row in rows
                ),
                "active_rooms": int(active_rooms),
                "total_rooms": int(total_rooms),
            }

    def list_user_ids(self) -> list[int]:
        """Broadcast uchun barcha foydalanuvchi idlari."""
        with self._lock:
            if not self.enabled:
                return sorted(self._users)
            rows = (
                self.client.table(USERS_TABLE)
                .select(USERS_ID_COLUMN)
                .execute()
                .data
                or []
            )
            return sorted({int(row[USERS_ID_COLUMN]) for row in rows})

    # ------------------------------------------------------------------
    # O'yin natijalari va tarix
    # ------------------------------------------------------------------
    def record_game_history(
        self,
        game_type: str,
        room_code: str,
        user_ids: Iterable[int],
        winner_ids: Iterable[int],
        coins_by_user: dict[int, int] | None = None,
        details: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Har bir o'yinchi uchun tarix yozuvini saqlaydi."""
        code = str(room_code).strip().upper()
        players = sorted({int(uid) for uid in user_ids})
        winners = set(int(uid) for uid in winner_ids) & set(players)
        coins = {int(uid): max(0, int(value)) for uid, value in (coins_by_user or {}).items()}
        common = dict(details or {})
        common.setdefault("players_count", len(players))
        common.setdefault("winner_ids", sorted(winners))
        created_at = _now()
        rows = [
            {
                "room_code": code,
                "user_id": uid,
                "game_type": str(game_type or "bunker").strip().lower(),
                "won": uid in winners,
                "coins_awarded": coins.get(uid, 0),
                "players_count": int(common["players_count"]),
                "details": common,
                "created_at": created_at,
            }
            for uid in players
        ]
        if not rows:
            return []
        with self._lock:
            self._history.extend(rows)
            if self.enabled:
                try:
                    safe_insert(self.client, HISTORY_TABLE, rows)
                except Exception:
                    logger.exception(
                        "O'yin tarixini Supabase'ga yozib bo'lmadi: %s", code
                    )
        metrics.game_finished(sum(coins.values()))
        return rows

    @staticmethod
    def _history_payload(row: dict[str, Any]) -> dict[str, Any]:
        """Tarix yozuvini API uchun ixcham ko'rinishga keltiradi."""
        return {
            "room_code": str(row.get("room_code") or ""),
            "game_type": str(row.get("game_type") or "bunker"),
            "won": bool(row.get("won")),
            "coins": int(row.get("coins_awarded") or row.get("coins") or 0),
            "players_count": int(row.get("players_count") or 0),
            "created_at": str(row.get("created_at") or ""),
        }

    def history_for_user(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        """Foydalanuvchining oxirgi o'yinlari."""
        uid = int(user_id)
        limit = max(1, min(int(limit), 50))
        with self._lock:
            if self.enabled:
                try:
                    rows = (
                        self.client.table(HISTORY_TABLE)
                        .select("*")
                        .eq("user_id", uid)
                        .order("created_at", desc=True)
                        .limit(limit)
                        .execute()
                        .data
                        or []
                    )
                except Exception:
                    logger.exception("O'yin tarixini o'qib bo'lmadi: %s", uid)
                    rows = [row for row in self._history if int(row.get("user_id") or 0) == uid]
            else:
                rows = [row for row in self._history if int(row.get("user_id") or 0) == uid]
            rows = [dict(row) for row in rows if int(row.get("user_id") or 0) == uid]
            rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
            return [self._history_payload(row) for row in rows[:limit]]

    def weekly_league(
        self,
        limit: int = 10,
        *,
        viewer_id: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Joriy hafta ligasi: o'yin va g'alaba ballari bo'yicha reyting."""
        limit = max(1, min(int(limit), 50))
        moment = now or _now_moment()
        week_start = (moment - timedelta(days=moment.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        week_end = week_start + timedelta(days=7)
        with self._lock:
            if self.enabled:
                try:
                    rows = (
                        self.client.table(HISTORY_TABLE)
                        .select("*")
                        .gte("created_at", week_start.isoformat())
                        .lt("created_at", week_end.isoformat())
                        .execute()
                        .data
                        or []
                    )
                except Exception:
                    logger.exception("Haftalik ligani o'qib bo'lmadi")
                    rows = self._history
            else:
                rows = self._history

        totals: dict[int, dict[str, int]] = {}
        for row in rows:
            created = str(row.get("created_at") or "")
            if created and not (week_start.isoformat() <= created < week_end.isoformat()):
                continue
            uid = int(row.get("user_id") or 0)
            if uid <= 0 or is_test_bot_id(uid):
                continue
            item = totals.setdefault(uid, {"points": 0, "wins": 0, "games": 0})
            won = bool(row.get("won"))
            item["games"] += 1
            item["wins"] += 1 if won else 0
            item["points"] += WEEKLY_WIN_POINTS if won else WEEKLY_PLAY_POINTS

        ranked: list[dict[str, Any]] = []
        for uid, item in totals.items():
            if is_test_bot_id(uid):
                continue
            account = self.ensure_user(uid)
            if is_rating_bot(account):
                continue
            points = int(item["points"])
            ranked.append(
                {
                    "user_id": uid,
                    "name": account.full_name or account.username or f"ID {uid}",
                    "points": points,
                    "wins": int(item["wins"]),
                    "games": int(item["games"]),
                    "tier": (
                        "oltin" if points >= 30 else "kumush" if points >= 15 else "bronza"
                    ),
                }
            )
        ranked.sort(key=lambda item: (item["points"], item["wins"], item["games"]), reverse=True)
        for index, item in enumerate(ranked, start=1):
            item["rank"] = index
        me = None
        if viewer_id is not None:
            me = next((item for item in ranked if item["user_id"] == int(viewer_id)), None)
            if me is None:
                account = self.ensure_user(int(viewer_id))
                me = {
                    "user_id": int(viewer_id),
                    "name": account.full_name or account.username or f"ID {viewer_id}",
                    "points": 0,
                    "wins": 0,
                    "games": 0,
                    "tier": "bronza",
                    "rank": len(ranked) + 1,
                }
        return {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "top": ranked[:limit],
            "me": me,
            "total": len(ranked),
        }

    def record_finished_game(
        self,
        room_code: str,
        user_ids: Iterable[int],
        winner_ids: Iterable[int],
        game: str = "bunker",
        reward: int = 0,
        coins_by_user: dict[int, int] | None = None,
    ) -> bool:
        """Tugagan o'yinni bir marta hisobga oladi (o'yinlar va g'alabalar).

        ``game`` qaysi g'alaba ustuni oshishini belgilaydi: bunker, mafia,
        spyfall, alias yoki bomb. ``reward`` berilsa, g'oliblarga shu qadar
        tanga qo'shiladi.
        """
        code = str(room_code).strip().upper()
        game_type = str(game or "bunker").strip().lower()
        win_column = game_win_column(game_type)
        reward = max(0, int(reward))
        players = sorted({int(uid) for uid in user_ids})
        winners = sorted({int(uid) for uid in winner_ids} & set(players))
        with self._lock:
            if not self.enabled:
                if code in self._finished_rooms:
                    return False
                self._finished_rooms.add(code)
            else:
                if self._select_one(RESULTS_TABLE, room_code=code) is not None:
                    return False
                safe_insert(
                    self.client,
                    RESULTS_TABLE,
                    {
                        "room_code": code,
                        "winner_ids": winners,
                        "finished_at": _now(),
                    },
                )

            for uid in players:
                account = self.ensure_user(uid)
                won = uid in winners
                games = account.games_played + 1
                wins = account.wins + (1 if won else 0)
                game_wins = getattr(account, win_column) + (1 if won else 0)
                coins = account.coins + (reward if won else 0)
                if not self.enabled:
                    row = self._users[uid]
                    row["games_played"] = games
                    row["wins"] = wins
                    row[win_column] = game_wins
                    if reward:
                        row["coins"] = coins
                else:
                    changes: dict[str, Any] = {
                        "games_played": games,
                        "wins": wins,
                        win_column: game_wins,
                    }
                    if reward:
                        changes["coins"] = coins
                    self._update_user_row(uid, changes)
            history_coins = coins_by_user
            if history_coins is None and reward:
                history_coins = {uid: reward for uid in winners}
            self.record_game_history(
                game_type,
                code,
                players,
                winners,
                history_coins,
            )
            return True

    def record_mafia_game(
        self,
        room_code: str,
        user_ids: Iterable[int],
        winner_ids: Iterable[int],
        reward: int = MAFIA_WIN_REWARD,
    ) -> bool:
        """Tugagan Mafiya o'yinini bir marta hisobga oladi.

        Barcha o'yinchilarga o'yin, g'oliblarga g'alaba va ``mafia_wins``
        qo'shiladi; har bir g'olibga ``reward`` tanga beriladi.
        """
        code = str(room_code).strip().upper()
        players = sorted({int(uid) for uid in user_ids})
        winners = sorted({int(uid) for uid in winner_ids} & set(players))
        reward = max(0, int(reward))
        with self._lock:
            if not self.enabled:
                if code in self._finished_rooms:
                    return False
                self._finished_rooms.add(code)
            else:
                if self._select_one(RESULTS_TABLE, room_code=code) is not None:
                    return False
                safe_insert(
                    self.client,
                    RESULTS_TABLE,
                    {
                        "room_code": code,
                        "winner_ids": winners,
                        "finished_at": _now(),
                    },
                )

            for uid in players:
                account = self.ensure_user(uid)
                won = uid in winners
                games = account.games_played + 1
                wins = account.wins + (1 if won else 0)
                mafia_wins = account.mafia_wins + (1 if won else 0)
                coins = account.coins + (reward if won else 0)
                if not self.enabled:
                    row = self._users[uid]
                    row["games_played"] = games
                    row["wins"] = wins
                    row["mafia_wins"] = mafia_wins
                    row["coins"] = coins
                else:
                    self._update_user_row(
                        uid,
                        {
                            "games_played": games,
                            "wins": wins,
                            "mafia_wins": mafia_wins,
                            "coins": coins,
                        },
                    )
            self.record_game_history(
                "mafia",
                code,
                players,
                winners,
                {uid: reward for uid in winners},
            )
            return True


_economy: EconomyStore | None = None
_economy_lock = threading.Lock()


def get_economy() -> EconomyStore:
    """Jarayon bo'ylab umumiy iqtisod store'ini qaytaradi."""
    global _economy
    if _economy is None:
        with _economy_lock:
            if _economy is None:
                _economy = EconomyStore()
    return _economy
