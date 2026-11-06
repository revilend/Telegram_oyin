"""Revilend Haftalik Turnirlar: ro'yxatga olish, qatnashish va bracket.

Turnir iqtisodi :class:`core.shop.ShopStore` bilan bog'langan: qatnashish
uchun 50 tanga yechiladi yoki inventardagi ``tournament_ticket`` çiptasi
sarflanadi.  Ma'lumotlar Supabase sozlangan bo'lsa ``tournaments`` va
``tournament_participants`` jadvallarida, aks holda jarayon xotirasida
saqlanadi — testlar va lokal ish uchun qulay.

Har hafta avtomatik «Haftalik Çempionat» yaratiladi: şanba kuni 18:00
(Toshkent vaqti).  Admin ``create`` orqali öyin bo'yicha alohida turnir
oçishi mumkin.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from core.db import safe_insert, safe_update
from core.economy import (
    EconomyStore,
    InsufficientCoinsError,
    UserAccount,
    get_economy,
)
from core.shop import InventoryEntry, get_shop_store

logger = logging.getLogger(__name__)

TOURNAMENTS_TABLE = "tournaments"
PARTICIPANTS_TABLE = "tournament_participants"

# Qatnashish narxi (tanga) va çipta slug'i.
ENTRY_FEE = 50
TICKET_SLUG = "tournament_ticket"
# Boshlanişdan şuncha daqiqa öldin eslatma yuboriladi.
REMINDER_MINUTES = 30
MAX_PARTICIPANTS = 64
# Turnir boshlanganidan keyin şuncha daqiqa içida hali qöşiliş mumkin.
JOIN_GRACE_MINUTES = 5

OPEN = "OPEN"
FINISHED = "FINISHED"

TASHKENT = timezone(timedelta(hours=5))

GAME_TITLES: dict[str, str] = {
    "bunker": "Bunker",
    "mafia": "Mafiya",
    "spyfall": "Josus",
    "alias": "Alias",
    "mixed": "Haftalik Çempionat",
}


class TournamentError(Exception):
    """Turnir amali bajarilmadi."""


class TournamentNotFoundError(TournamentError):
    """Bunday turnir yo'q."""


class TournamentClosedError(TournamentError):
    """Turnir allaqachon boşlangan yoki yopilgan."""


class AlreadyJoinedError(TournamentError):
    """Foydalanuvchi allaqachon yozilgan."""


class TournamentFullError(TournamentError):
    """Turnirda bo'sh o'rin qolmagan."""


class EntryFeeError(TournamentError):
    """Qatnashish uchun tanga ham, çipta ham yetarli emas."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_moment(value: Any) -> datetime | None:
    """ISO satr yoki datetime'ni UTC momentga aylantiradi."""
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


def format_local(value: Any) -> str:
    """Turnir vaqtini Toshkent vaqtida ``DD.MM.YYYY HH:MM`` ko'rinishida beradi."""
    moment = _parse_moment(value)
    if moment is None:
        return ""
    return moment.astimezone(TASHKENT).strftime("%d.%m.%Y %H:%M")


def seconds_left(value: Any, now: datetime | None = None) -> int:
    """Boshlanişga qolgan soniyalar (ö'tib ketgan bo'lsa 0)."""
    moment = _parse_moment(value)
    if moment is None:
        return 0
    delta = moment - (now or _now())
    return max(0, int(delta.total_seconds()))


def countdown_text(value: Any, now: datetime | None = None) -> str:
    """``2 kun 4 soat`` ko'rinishidagi qisqa countdown."""
    total = seconds_left(value, now)
    if total <= 0:
        return "boşlandi"
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days} kun {hours} soat"
    if hours:
        return f"{hours} soat {minutes} daqiqa"
    return f"{minutes} daqiqa"


def _next_saturday(now: datetime) -> datetime:
    """Keyingi şanba 18:00 (Toshkent) momentini UTC'da qaytaradi."""
    local = now.astimezone(TASHKENT)
    days = (5 - local.weekday()) % 7  # dushanba=0, şanba=5
    target = (local + timedelta(days=days)).replace(
        hour=18, minute=0, second=0, microsecond=0
    )
    if target - local < timedelta(hours=6):
        target += timedelta(days=7)
    return target.astimezone(timezone.utc)


@dataclass(frozen=True)
class Tournament:
    """Bitta turnir yozuvi."""

    id: str
    game: str
    title: str
    entry_fee: int
    prize_pool: int
    starts_at: str
    status: str = OPEN
    max_players: int = MAX_PARTICIPANTS
    created_by: int = 0
    reminded_at: str = ""

    @property
    def starts_moment(self) -> datetime:
        return _parse_moment(self.starts_at) or _now()

    @property
    def game_title(self) -> str:
        return GAME_TITLES.get(self.game, self.game)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game": self.game,
            "game_title": self.game_title,
            "title": self.title,
            "entry_fee": self.entry_fee,
            "prize_pool": self.prize_pool,
            "starts_at": self.starts_at,
            "starts_at_local": format_local(self.starts_at),
            "countdown": countdown_text(self.starts_at),
            "status": self.status,
            "max_players": self.max_players,
            "created_by": self.created_by,
            "reminded_at": self.reminded_at,
        }


@dataclass(frozen=True)
class Participant:
    """Turnirga yozilgan öyinçi."""

    user_id: int
    username: str = ""
    full_name: str = ""
    joined_at: str = ""

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.full_name or str(self.user_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "full_name": self.full_name,
            "display_name": self.display_name,
            "joined_at": self.joined_at,
        }


@dataclass(frozen=True)
class JoinResult:
    """Qatnashish natijasi."""

    tournament: Tournament
    account: UserAccount
    ticket_used: bool
    expense: int
    participants_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "tournament": self.tournament.as_dict(),
            "coins": self.account.coins,
            "ticket_used": self.ticket_used,
            "expense": self.expense,
            "participants_count": self.participants_count,
        }


def _tournament_from_row(row: dict[str, Any]) -> Tournament:
    return Tournament(
        id=str(row.get("id") or ""),
        game=str(row.get("game") or "mixed"),
        title=str(row.get("title") or ""),
        entry_fee=int(row.get("entry_fee") or ENTRY_FEE),
        prize_pool=int(row.get("prize_pool") or 0),
        starts_at=str(row.get("starts_at") or ""),
        status=str(row.get("status") or OPEN),
        max_players=int(row.get("max_players") or MAX_PARTICIPANTS),
        created_by=int(row.get("created_by") or 0),
        reminded_at=str(row.get("reminded_at") or ""),
    )


def _participant_from_row(row: dict[str, Any]) -> Participant:
    return Participant(
        user_id=int(row.get("user_id") or 0),
        username=str(row.get("username") or ""),
        full_name=str(row.get("full_name") or ""),
        joined_at=str(row.get("joined_at") or ""),
    )


class TournamentStore:
    """Turnirlar ro'yxati, qatnashchilar va bracketni boshqaradi."""

    def __init__(
        self,
        economy: EconomyStore | None = None,
        shop: Any | None = None,
        client: Any | None = None,
    ) -> None:
        self.economy = economy if economy is not None else get_economy()
        self.shop = shop if shop is not None else get_shop_store()
        self._client = client
        self._lock = threading.RLock()
        self._tournaments: dict[str, dict[str, Any]] = {}
        self._participants: dict[str, list[dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Saqlash qatlami
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._client is not None or self.economy.enabled

    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        return self.economy.client

    def _rows(self) -> list[dict[str, Any]]:
        """Turnirlar qatorlari (baza yoki xotira)."""
        if not self.enabled:
            return list(self._tournaments.values())
        try:
            return (
                self.client.table(TOURNAMENTS_TABLE)
                .select("*")
                .order("starts_at")
                .execute()
                .data
                or []
            )
        except Exception:
            logger.exception("Turnirlar ro'yxatini öqib bölmadi")
            return list(self._tournaments.values())

    def _participant_rows(self, tournament_id: str) -> list[dict[str, Any]]:
        tid = str(tournament_id)
        if not self.enabled:
            return list(self._participants.get(tid, []))
        try:
            return (
                self.client.table(PARTICIPANTS_TABLE)
                .select("*")
                .eq("tournament_id", tid)
                .order("joined_at")
                .execute()
                .data
                or []
            )
        except Exception:
            logger.exception("Turnir qatnaşçilarini öqib bölmadi: %s", tid)
            return list(self._participants.get(tid, []))

    def _save_tournament(self, tournament: Tournament) -> None:
        row = {
            "id": tournament.id,
            "game": tournament.game,
            "title": tournament.title,
            "entry_fee": tournament.entry_fee,
            "prize_pool": tournament.prize_pool,
            "starts_at": tournament.starts_at,
            "status": tournament.status,
            "max_players": tournament.max_players,
            "created_by": tournament.created_by,
        }
        with self._lock:
            self._tournaments[tournament.id] = {**row, "reminded_at": tournament.reminded_at}
        if not self.enabled:
            return
        try:
            safe_insert(self.client, TOURNAMENTS_TABLE, row)
        except Exception:
            logger.exception("Turnirni saqlab bölmadi: %s", tournament.id)

    def _save_participant(self, tournament_id: str, participant: Participant) -> None:
        row = {
            "tournament_id": str(tournament_id),
            "user_id": participant.user_id,
            "username": participant.username,
            "full_name": participant.full_name,
            "joined_at": participant.joined_at,
        }
        with self._lock:
            bucket = self._participants.setdefault(str(tournament_id), [])
            if all(int(item.get("user_id") or 0) != participant.user_id for item in bucket):
                bucket.append(row)
        if not self.enabled:
            return
        try:
            safe_insert(self.client, PARTICIPANTS_TABLE, row)
        except Exception:
            logger.exception(
                "Turnir qatnaşçisini saqlab bölmadi: %s %s",
                tournament_id,
                participant.user_id,
            )

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------
    def get(self, tournament_id: str) -> Tournament | None:
        key = str(tournament_id or "").strip()
        if not key:
            return None
        with self._lock:
            cached = self._tournaments.get(key)
        if cached is not None:
            return _tournament_from_row(cached)
        for row in self._rows():
            if str(row.get("id") or "") == key:
                with self._lock:
                    self._tournaments[key] = dict(row)
                return _tournament_from_row(row)
        return None

    def all(self) -> list[Tournament]:
        tournaments = [_tournament_from_row(row) for row in self._rows()]
        tournaments.sort(key=lambda item: item.starts_moment)
        return tournaments

    def active(self, now: datetime | None = None) -> list[Tournament]:
        """Ro'yxatga olish ochiq turnirlar (boshlanişga 5 daqiqa qolguncha)."""
        moment = now or _now()
        self.ensure_weekly(moment)
        result = []
        for tournament in self.all():
            if tournament.status != OPEN:
                continue
            if tournament.starts_moment + timedelta(minutes=JOIN_GRACE_MINUTES) <= moment:
                continue
            result.append(tournament)
        return result

    def participants(self, tournament_id: str) -> list[Participant]:
        rows = self._participant_rows(tournament_id)
        rows = sorted(rows, key=lambda row: str(row.get("joined_at") or ""))
        return [_participant_from_row(row) for row in rows]

    def participant_count(self, tournament_id: str) -> int:
        return len(self._participant_rows(tournament_id))

    def joined(self, tournament_id: str, user_id: int) -> bool:
        return any(
            int(row.get("user_id") or 0) == int(user_id)
            for row in self._participant_rows(tournament_id)
        )

    def bracket(self, tournament_id: str) -> list[dict[str, Any]]:
        """Ko'rgazma bracket: juftliklar, keyingi raundlar va bo'sh o'rinlar."""
        participants = self.participants(tournament_id)
        if not participants:
            return []
        rounds: list[dict[str, Any]] = []
        current: list[Participant | None] = list(participants)
        round_number = 1
        while len(current) > 1:
            matches: list[dict[str, Any]] = []
            next_round: list[Participant | None] = []
            for index in range(0, len(current), 2):
                left = current[index]
                right = current[index + 1] if index + 1 < len(current) else None
                matches.append(
                    {
                        "a": left.as_dict() if left else None,
                        "b": right.as_dict() if right else None,
                        "winner": None,
                    }
                )
                # Birinchi juftlik vakili keyingi raundga chiqadi (ko'rgazma).
                next_round.append(left)
            rounds.append({"round": round_number, "matches": matches})
            current = next_round
            round_number += 1
            if round_number > 8:  # cheksiz sikl himoyasi
                break
        return rounds

    def payload(self, user_id: int | None = None) -> dict[str, Any]:
        """Mini App va bot uchun to'liq turnir ma'lumoti."""
        tournaments = []
        for tournament in self.active():
            participants = self.participants(tournament.id)
            data = tournament.as_dict()
            data["participants_count"] = len(participants)
            data["participants"] = [item.as_dict() for item in participants]
            data["bracket"] = self.bracket(tournament.id)
            data["joined"] = any(
                item.user_id == int(user_id) for item in participants
            ) if user_id is not None else False
            tournaments.append(data)
        payload: dict[str, Any] = {
            "tournaments": tournaments,
            "entry_fee": ENTRY_FEE,
            "ticket_slug": TICKET_SLUG,
        }
        if user_id is not None:
            uid = int(user_id)
            account = self.economy.ensure_user(uid)
            payload["coins"] = account.coins
            payload["tickets"] = self.shop.entry(uid, TICKET_SLUG).quantity
        return payload

    # ------------------------------------------------------------------
    # Yozish
    # ------------------------------------------------------------------
    def create(
        self,
        game: str,
        starts_at: Any,
        *,
        entry_fee: int = ENTRY_FEE,
        prize_pool: int = 2_000,
        title: str = "",
        created_by: int = 0,
        max_players: int = MAX_PARTICIPANTS,
    ) -> Tournament:
        """Yangi turnir ochadi (admin panel va bot buyrug'i uchun)."""
        key = str(game or "mixed").strip().lower()
        if key not in GAME_TITLES:
            raise TournamentError(
                "Öyin nomi notöğri. Mumkin: bunker, mafiya, josus, alias, mixed."
            )
        moment = _parse_moment(starts_at)
        if moment is None:
            raise TournamentError("Boşlaniş vaqti notöğri (ISO format kerak).")
        if moment <= _now():
            raise TournamentError("Boşlaniş vaqti kelajakda bölishi kerak.")
        if entry_fee < 0 or prize_pool < 0:
            raise TournamentError("Narx va sovrin manfiy bölmaydi.")
        tournament = Tournament(
            id=uuid.uuid4().hex[:10],
            game=key,
            title=(title or "").strip() or f"{GAME_TITLES[key]} Haftalik Turniri",
            entry_fee=int(entry_fee),
            prize_pool=int(prize_pool),
            starts_at=moment.isoformat(),
            max_players=max(2, int(max_players)),
            created_by=int(created_by or 0),
        )
        self._save_tournament(tournament)
        logger.info(
            "Yangi turnir: %s (%s) — %s, sovrin %s",
            tournament.id,
            tournament.title,
            tournament.starts_at,
            tournament.prize_pool,
        )
        return tournament

    def ensure_weekly(self, now: datetime | None = None) -> Tournament | None:
        """Haftalik çempionat mavjud bölmasa, keyingi şanbaga yaratadi."""
        moment = now or _now()
        for tournament in self.all():
            if tournament.status == OPEN and tournament.starts_moment > moment:
                return tournament
        try:
            return self.create(
                "mixed",
                _next_saturday(moment),
                entry_fee=ENTRY_FEE,
                prize_pool=2_000,
                title="Revilend Haftalik Çempionati",
            )
        except TournamentError:
            logger.exception("Haftalik turnirni yaratib bölmadi")
            return None

    def join(
        self,
        user_id: int,
        tournament_id: str,
        username: str = "",
        full_name: str = "",
    ) -> JoinResult:
        """Turnirga yoziladi: çipta yoki 50 tanga sarflanadi."""
        uid = int(user_id)
        tournament = self.get(tournament_id)
        if tournament is None:
            raise TournamentNotFoundError("Turnir topilmadi.")
        now = _now()
        if tournament.status != OPEN:
            raise TournamentClosedError("Turnir allaqachon yakunlangan.")
        if tournament.starts_moment + timedelta(minutes=JOIN_GRACE_MINUTES) <= now:
            raise TournamentClosedError("Turnir boşlanib ketgan — ro'yxat yopilgan.")
        if self.joined(tournament.id, uid):
            raise AlreadyJoinedError("Siz allaqachon bu turnirga yozilgansiz.")
        if self.participant_count(tournament.id) >= tournament.max_players:
            raise TournamentFullError("Turnirda bo'sh örin qolmagan.")

        expense = 0
        ticket_used = False
        entry = self.shop.entry(uid, TICKET_SLUG)
        if entry.quantity > 0:
            ticket_used = True
            self.shop._save_entry(
                uid,
                InventoryEntry(
                    item_slug=TICKET_SLUG,
                    quantity=entry.quantity - 1,
                    is_equipped=False,
                ),
            )
        else:
            try:
                self.economy.spend_coins(uid, tournament.entry_fee)
            except InsufficientCoinsError as exc:
                raise EntryFeeError(
                    f"Qatnaşiş uçun {tournament.entry_fee} tanga yoki turnir "
                    "çiptasi kerak."
                ) from exc
            expense = tournament.entry_fee

        account = self.economy.ensure_user(uid, username, full_name)
        participant = Participant(
            user_id=uid,
            username=(username or "").strip().lstrip("@"),
            full_name=(full_name or "").strip(),
            joined_at=now.isoformat(),
        )
        self._save_participant(tournament.id, participant)
        return JoinResult(
            tournament=tournament,
            account=account,
            ticket_used=ticket_used,
            expense=expense,
            participants_count=self.participant_count(tournament.id),
        )

    def due_reminders(self, now: datetime | None = None) -> list[Tournament]:
        """Boshlanişga 30 daqiqa qolgan va eslatilmagan turnirlar."""
        moment = now or _now()
        result = []
        for tournament in self.active(moment):
            if tournament.reminded_at:
                continue
            left = tournament.starts_moment - moment
            if timedelta(0) <= left <= timedelta(minutes=REMINDER_MINUTES):
                result.append(tournament)
        return result

    def mark_reminded(self, tournament_id: str) -> None:
        """Eslatma yuborilganini belgilaydi."""
        tournament = self.get(tournament_id)
        if tournament is None:
            return
        moment = _now().isoformat()
        with self._lock:
            row = self._tournaments.get(tournament.id)
            if row is not None:
                row["reminded_at"] = moment
        if not self.enabled:
            return
        try:
            safe_update(
                self.client,
                TOURNAMENTS_TABLE,
                {"reminded_at": moment},
                "id",
                tournament.id,
            )
        except Exception:
            logger.exception("Eslatma belgisini saqlab bölmadi: %s", tournament.id)


_store: TournamentStore | None = None
_store_lock = threading.Lock()


def get_tournament_store() -> TournamentStore:
    """Global turnir omborini qaytaradi."""
    global _store
    with _store_lock:
        if _store is None:
            _store = TournamentStore()
        return _store


def set_tournament_store(store: TournamentStore | None) -> None:
    """Global omborni almashtiradi (testlar uchun)."""
    global _store
    with _store_lock:
        _store = store
