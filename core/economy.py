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
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)

USERS_TABLE = "users"
# Supabase'dagi `users` jadvalida asosiy ustun `telegram_id` deb nomlangan.
USERS_ID_COLUMN = "telegram_id"
PAYMENTS_TABLE = "payment_requests"
BOOSTERS_TABLE = "player_boosters"
RESULTS_TABLE = "game_results"
REFERRALS_TABLE = "referrals"

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
REFERRAL_BONUS = 50

# Kunlik bonus: asosiy mukofot, har bir ketma-ket kun uchun qo'shimcha va
# seriyaning eng yuqori chegarasi.
DAILY_BONUS_BASE = 50
DAILY_BONUS_STREAK_STEP = 10
DAILY_BONUS_MAX_STREAK = 5
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
    referral_count: int = 0
    last_bonus_at: str = ""
    bonus_streak: int = 0


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


@dataclass(frozen=True)
class DailyBonusClaim:
    """Muvaffaqiyatli kunlik bonus natijasi."""

    amount: int
    streak: int
    account: UserAccount


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
    amount = DAILY_BONUS_BASE + (streak - 1) * DAILY_BONUS_STREAK_STEP
    return available, amount, streak, max(0, seconds_left)


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
        referral_count=int(row.get("referral_count") or 0),
        last_bonus_at=str(row.get("last_bonus_at") or ""),
        bonus_streak=int(row.get("bonus_streak") or 0),
    )


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
    return PromoCode(
        code=str(row["code"]),
        coins=int(row.get("coins") or 0),
        max_uses=int(row.get("max_uses") or 1),
        used_count=int(row.get("used_count") or 0),
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
        self.key = (key if key is not None else os.getenv("SUPABASE_KEY") or "").strip()
        self._client = client
        self._lock = threading.RLock()
        self._users: dict[int, dict[str, Any]] = {}
        self._payments: dict[str, dict[str, Any]] = {}
        self._boosters: set[tuple[str, int, str]] = set()
        self._finished_rooms: set[str] = set()
        # taklif qilingan id -> taklif qilgan id
        self._referrals: dict[int, int] = {}
        self._promo_codes: dict[str, dict[str, Any]] = {}
        self._promo_redemptions: set[tuple[str, int]] = set()
        self._mission_claims: dict[int, set[str]] = {}

    @property
    def enabled(self) -> bool:
        return self._client is not None or bool(self.url and self.key)

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
        changes = {**changes, "updated_at": _now()}
        self.client.table(USERS_TABLE).update(changes).eq(
            USERS_ID_COLUMN, int(user_id)
        ).execute()

    # ------------------------------------------------------------------
    # Foydalanuvchilar
    # ------------------------------------------------------------------
    def ensure_user(
        self,
        user_id: int,
        username: str = "",
        full_name: str = "",
    ) -> UserAccount:
        """Foydalanuvchini yaratadi yoki ismini yangilab, hisobni qaytaradi."""
        uid = int(user_id)
        if uid <= 0:
            raise EconomyError("Foydalanuvchi id musbat bo'lishi kerak")
        username = (username or "").strip()
        full_name = (full_name or "").strip()

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
                        "referral_count": 0,
                        "role": "user",
                        "created_at": _now(),
                    }
                    self._users[uid] = row
                else:
                    if username:
                        row["username"] = username
                    if full_name:
                        row["full_name"] = full_name
                return _row_to_account(row)

            row = self._select_one(USERS_TABLE, **{USERS_ID_COLUMN: uid})
            if row is None:
                row = {
                    USERS_ID_COLUMN: uid,
                    "username": username,
                    "full_name": full_name,
                    "coins": START_COINS,
                    "total_purchased": 0,
                    "games_played": 0,
                    "wins": 0,
                    "referral_count": 0,
                    "role": "user",
                    "created_at": _now(),
                    "updated_at": _now(),
                }
                try:
                    self.client.table(USERS_TABLE).insert(row).execute()
                except Exception:
                    # Parallel yaratilgan bo'lsa, mavjud yozuvni qayta o'qiymiz.
                    row = self._select_one(USERS_TABLE, **{USERS_ID_COLUMN: uid})
                    if row is None:
                        raise
            else:
                changes: dict[str, Any] = {}
                if username and username != row.get("username"):
                    changes["username"] = username
                if full_name and full_name != row.get("full_name"):
                    changes["full_name"] = full_name
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
            return self._select_one(USERS_TABLE, **{USERS_ID_COLUMN: uid}) is not None

    def get_role(self, user_id: int) -> str:
        """Foydalanuvchi rolini qaytaradi (``admin`` yoki ``user``)."""
        uid = int(user_id)
        with self._lock:
            if not self.enabled:
                row = self._users.get(uid)
            else:
                row = self._select_one(USERS_TABLE, **{USERS_ID_COLUMN: uid})
        return str((row or {}).get("role") or "user").strip().lower()

    def is_admin_user(self, user_id: int) -> bool:
        """`users` jadvalida shu telegram id uchun rol ``admin`` mi?"""
        return self.get_role(user_id) == "admin"

    def top_users(self, limit: int = 10) -> list[UserAccount]:
        """Eng ko'p g'alaba qozongan o'yinchilarni qaytaradi."""
        limit = max(1, int(limit))
        with self._lock:
            if not self.enabled:
                rows = list(self._users.values())
            else:
                rows = self.client.table(USERS_TABLE).select("*").execute().data or []
        accounts = [_row_to_account(row) for row in rows]
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

        with self._lock:
            if self.enabled:
                if self._select_one(
                    USERS_TABLE, **{USERS_ID_COLUMN: inviter}
                ) is None:
                    return None
                row = {
                    "inviter_id": inviter,
                    "invited_id": invited,
                    "bonus": bonus,
                    "created_at": _now(),
                }
                try:
                    self.client.table(REFERRALS_TABLE).insert(row).execute()
                except Exception:
                    # `invited_id` unikal — takroriy taklif hisobga olinmaydi.
                    logger.info("Taklif allaqachon yozilgan: %s", invited)
                    return None
            else:
                if inviter not in self._users:
                    return None
                if invited in self._referrals:
                    return None
                self._referrals[invited] = inviter

            self.add_coins(inviter, bonus)
            account = self.ensure_user(inviter)
            new_count = account.referral_count + 1
            if self.enabled:
                self._update_user_row(inviter, {"referral_count": new_count})
            else:
                self._users[inviter]["referral_count"] = new_count
        return ReferralResult(inviter_id=inviter, invited_id=invited, bonus=bonus)

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
            if not self.enabled:
                self._payments[request_id] = row
            else:
                self.client.table(PAYMENTS_TABLE).insert(row).execute()
        return _row_to_payment(row)

    def get_payment(self, request_id: str) -> PaymentRequest | None:
        """Chekni id bo'yicha qaytaradi."""
        with self._lock:
            if not self.enabled:
                row = self._payments.get(str(request_id))
                return _row_to_payment(row) if row else None
            row = self._select_one(PAYMENTS_TABLE, id=str(request_id))
            return _row_to_payment(row) if row else None

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
        payments = [_row_to_payment(row) for row in rows]
        payments.sort(key=lambda payment: payment.created_at)
        return payments

    def _set_payment_status(self, request_id: str, status: str, admin_id: int) -> None:
        if not self.enabled:
            row = self._payments[str(request_id)]
            row["status"] = status
            row["reviewed_by"] = int(admin_id)
            row["reviewed_at"] = _now()
            return
        self.client.table(PAYMENTS_TABLE).update(
            {
                "status": status,
                "reviewed_by": int(admin_id),
                "reviewed_at": _now(),
            }
        ).eq("id", str(request_id)).eq("status", PENDING).execute()

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
            self.client.table(BOOSTERS_TABLE).insert(
                {
                    "room_code": key[0],
                    "user_id": key[1],
                    "booster": key[2],
                    "used_at": _now(),
                }
            ).execute()
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
                row["bonus_streak"] = streak
            else:
                self._update_user_row(
                    uid, {"last_bonus_at": claimed_at, "bonus_streak": streak}
                )
            updated = self.add_coins(uid, amount)
        return DailyBonusClaim(amount=amount, streak=streak, account=updated)

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
        row: dict[str, Any] = {
            "code": normalized,
            "coins": amount,
            "max_uses": uses,
            "used_count": 0,
            "created_by": int(created_by) if created_by else None,
            "created_at": _now(),
        }
        with self._lock:
            if not self.enabled:
                if normalized in self._promo_codes:
                    raise EconomyError("Bu promo kod allaqachon mavjud")
                self._promo_codes[normalized] = row
            else:
                if self._select_one(PROMO_CODES_TABLE, code=normalized) is not None:
                    raise EconomyError("Bu promo kod allaqachon mavjud")
                self.client.table(PROMO_CODES_TABLE).insert(row).execute()
        return _row_to_promo(row)

    def get_promo_code(self, code: str) -> PromoCode | None:
        """Kod bo'yicha promo kodni qaytaradi."""
        normalized = normalize_promo_code(code)
        with self._lock:
            if not self.enabled:
                row = self._promo_codes.get(normalized)
            else:
                row = self._select_one(PROMO_CODES_TABLE, code=normalized)
        return _row_to_promo(row) if row else None

    def list_promo_codes(self, limit: int = 10) -> list[PromoCode]:
        """Oxirgi yaratilgan promo kodlar (admin panel uchun)."""
        with self._lock:
            if not self.enabled:
                rows = list(self._promo_codes.values())
            else:
                rows = (
                    self.client.table(PROMO_CODES_TABLE)
                    .select("*")
                    .execute()
                    .data
                    or []
                )
        codes = [_row_to_promo(row) for row in rows]
        codes.sort(key=lambda promo: promo.created_at, reverse=True)
        return codes[: max(1, int(limit))]

    def has_redeemed_promo(self, user_id: int, code: str) -> bool:
        """Foydalanuvchi bu kodni allaqachon ishlatganmi."""
        normalized = normalize_promo_code(code)
        uid = int(user_id)
        with self._lock:
            if not self.enabled:
                return (normalized, uid) in self._promo_redemptions
            row = self._select_one(
                PROMO_REDEMPTIONS_TABLE, code=normalized, user_id=uid
            )
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
            if not self.enabled:
                self._promo_redemptions.add((normalized, uid))
                self._promo_codes[normalized]["used_count"] = promo.used_count + 1
            else:
                try:
                    self.client.table(PROMO_REDEMPTIONS_TABLE).insert(
                        {
                            "code": normalized,
                            "user_id": uid,
                            "coins": promo.coins,
                            "redeemed_at": _now(),
                        }
                    ).execute()
                except Exception as exc:
                    logger.info(
                        "Promo kod allaqachon ishlatilgan: %s / %s",
                        normalized,
                        uid,
                    )
                    raise EconomyError(
                        "Bu promo kodni allaqachon ishlatgansiz"
                    ) from exc
                self.client.table(PROMO_CODES_TABLE).update(
                    {"used_count": promo.used_count + 1}
                ).eq("code", normalized).execute()
            updated = self.add_coins(uid, promo.coins)
        return PromoRedemption(code=normalized, coins=promo.coins, account=updated)

    # ------------------------------------------------------------------
    # Missiya mukofotlari
    # ------------------------------------------------------------------
    def claimed_missions(self, user_id: int) -> set[str]:
        """Foydalanuvchi mukofotini olgan missiyalar kalitlari."""
        uid = int(user_id)
        with self._lock:
            if not self.enabled:
                return set(self._mission_claims.get(uid, set()))
            rows = (
                self.client.table(MISSIONS_TABLE)
                .select("mission")
                .eq("user_id", uid)
                .execute()
                .data
                or []
            )
        return {str(row["mission"]) for row in rows if row.get("mission")}

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
            if not self.enabled:
                self._mission_claims.setdefault(uid, set()).add(key)
            else:
                try:
                    self.client.table(MISSIONS_TABLE).insert(
                        {"user_id": uid, "mission": key, "claimed_at": _now()}
                    ).execute()
                except Exception as exc:
                    logger.info(
                        "Missiya mukofoti allaqachon olingan: %s / %s", key, uid
                    )
                    raise EconomyError(
                        "Bu missiya mukofoti allaqachon olingan"
                    ) from exc
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
    # O'yin natijalari
    # ------------------------------------------------------------------
    def record_finished_game(
        self,
        room_code: str,
        user_ids: Iterable[int],
        winner_ids: Iterable[int],
    ) -> bool:
        """Tugagan o'yinni bir marta hisobga oladi (o'yinlar va g'alabalar)."""
        code = str(room_code).strip().upper()
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
                self.client.table(RESULTS_TABLE).insert(
                    {
                        "room_code": code,
                        "winner_ids": winners,
                        "finished_at": _now(),
                    }
                ).execute()

            for uid in players:
                account = self.ensure_user(uid)
                if not self.enabled:
                    row = self._users[uid]
                    row["games_played"] = account.games_played + 1
                    row["wins"] = account.wins + (1 if uid in winners else 0)
                else:
                    self._update_user_row(
                        uid,
                        {
                            "games_played": account.games_played + 1,
                            "wins": account.wins + (1 if uid in winners else 0),
                        },
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
