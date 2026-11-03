"""Tangalar, to'lov so'rovlari va boosterlar uchun iqtisod qatlami.

Supabase sozlangan bo'lsa ma'lumotlar ``users``, ``payment_requests``,
``player_boosters`` va ``game_results`` jadvallarida saqlanadi. Supabase
bo'lmasa (lokal test yoki preview) hammasi jarayon xotirasida ishlaydi.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import dataclass
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            return UserAccount(
                user_id=account.user_id,
                username=account.username,
                full_name=account.full_name,
                coins=new_coins,
                total_purchased=new_purchased,
                games_played=account.games_played,
                wins=account.wins,
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
            return UserAccount(
                user_id=account.user_id,
                username=account.username,
                full_name=account.full_name,
                coins=new_coins,
                total_purchased=account.total_purchased,
                games_played=account.games_played,
                wins=account.wins,
            )

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
