"""Revilend Haftalik Turnirlar: ro'yxatga olish, qatnashish va bracket.

Turnir iqtisodi :class:`core.shop.ShopStore` bilan bog'langan: qatnashish
uchun 50 tanga yechiladi yoki inventardagi ``tournament_ticket`` çiptasi
sarflanadi.  Ma'lumotlar Supabase sozlangan bo'lsa ``tournaments`` va
``tournament_participants`` jadvallarida saqlanadi.  Xotiradagi nusxa faqat
Supabase sozlanmagan lokal/test muhitida ishlatiladi.

Asosiy ustunlar:
``tournaments`` — ``game_type``, ``start_time``, ``max_participants``,
``bracket_data``; eski o'rnatishlar uchun ``game``, ``starts_at`` va
``max_players`` ham yoziladi.
``tournament_participants`` — ``score``, ``status``, ``registered_at``;
eski o'rnatishlar uchun ``joined_at`` ham yoziladi.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from dataclasses import dataclass, field
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
MIN_PARTICIPANTS = 2
# Turnir boshlanganidan keyin şuncha daqiqa içida hali qöşiliş mumkin.
JOIN_GRACE_MINUTES = 5

OPEN = "OPEN"
ACTIVE = "ACTIVE"
FINISHED = "FINISHED"

# Admin panel va tashqi panellar turli nomlarda yozadi: ``registration``,
# ``active``, ``OPEN`` va h.k.  Hammasi bitta ichki holatga keltiriladi.
STATUS_ALIASES: dict[str, str] = {
    "OPEN": OPEN,
    "REGISTRATION": OPEN,
    "REGISTRATION_OPEN": OPEN,
    "REGISTERING": OPEN,
    "REGISTER": OPEN,
    "SIGNUP": OPEN,
    "UPCOMING": OPEN,
    "PENDING": OPEN,
    "ROYXAT": OPEN,
    "RO_YXAT": OPEN,
    "ACTIVE": ACTIVE,
    "ONGOING": ACTIVE,
    "STARTED": ACTIVE,
    "LIVE": ACTIVE,
    "IN_PROGRESS": ACTIVE,
    "INPROGRESS": ACTIVE,
    "FINISHED": FINISHED,
    "COMPLETED": FINISHED,
    "CLOSED": FINISHED,
    "ENDED": FINISHED,
    "CANCELLED": FINISHED,
    "CANCELED": FINISHED,
}

STATUS_LABELS: dict[str, str] = {
    OPEN: "Röyxatga oliş oçiq",
    ACTIVE: "Turnir boşlangan",
    FINISHED: "Yakunlangan",
}

TASHKENT = timezone(timedelta(hours=5))


def normalize_status(value: Any) -> str:
    """Turnir holatini yagona ko'rinishga keltiradi.

    Supabase'dagi eski qatorlarda ``registration`` yoki ``active`` kabi
    kichik harfli qiymatlar bo'lishi mumkin.  Ular mos ravishda ``OPEN`` va
    ``ACTIVE`` ga aylanadi — aks holda foydalanuvchi menyusi turnirni
    ko'rmay qoladi.
    """
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if not text:
        return OPEN
    return STATUS_ALIASES.get(text, text)


def status_label(value: Any) -> str:
    """Foydalanuvchiga ko'rinadigan holat matni."""
    status = normalize_status(value)
    return STATUS_LABELS.get(status, status)

GAME_TITLES: dict[str, str] = {
    "bunker": "Bunker",
    "mafia": "Mafiya",
    "spyfall": "Josus",
    "alias": "Alias",
    "bomb": "Portlovchi Bomba",
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


def parse_admin_time(value: Any, now: datetime | None = None) -> datetime:
    """Admin kiritadigan vaqtni Toshkent vaqti bo'yicha UTC ga aylantiradi.

    Qabul qilinadigan formatlar:
    ``2026-11-12 20:00``, ``12.11.2026 20:00``, ``ertaga 21:00``,
    ``+3 kun``, ``+3 kun 21:00`` va ISO sana.
    """
    text = str(value or "").strip()
    if not text:
        raise TournamentError("Vaqt kiritilmadi.")
    current = (now or _now()).astimezone(TASHKENT)
    lowered = text.lower()

    def with_local_time(day: datetime, time_text: str) -> datetime:
        raw = time_text.replace(".", ":").strip()
        try:
            hour_text, minute_text = raw.split(":", 1)
            hour, minute = int(hour_text), int(minute_text)
        except (TypeError, ValueError):
            raise TournamentError("Vaqt formati noto'g'ri. Masalan: 20:00") from None
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise TournamentError("Soat yoki daqiqa noto'g'ri.")
        return day.replace(hour=hour, minute=minute, second=0, microsecond=0)

    relative = re.fullmatch(r"\+?\s*(\d+)\s*(?:kun|days?)(?:\s+(\d{1,2}[:.]\d{2}))?", lowered)
    if relative:
        days = int(relative.group(1))
        target = current + timedelta(days=days)
        if relative.group(2):
            target = with_local_time(target, relative.group(2))
        return target.astimezone(timezone.utc)

    tomorrow = re.fullmatch(r"(?:ertaga|tomorrow)(?:\s+(\d{1,2}[:.]\d{2}))?", lowered)
    if tomorrow:
        target = current + timedelta(days=1)
        if tomorrow.group(1):
            target = with_local_time(target, tomorrow.group(1))
        else:
            target = target.replace(hour=18, minute=0, second=0, microsecond=0)
        return target.astimezone(timezone.utc)

    today = re.fullmatch(r"(?:bugun|today)(?:\s+(\d{1,2}[:.]\d{2}))?", lowered)
    if today:
        target = current
        if today.group(1):
            target = with_local_time(target, today.group(1))
        else:
            target = target.replace(hour=18, minute=0, second=0, microsecond=0)
        return target.astimezone(timezone.utc)

    raw = text[:-1] + "+00:00" if text.endswith("Z") else text
    for pattern in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M"):
        try:
            parsed = datetime.strptime(raw, pattern)
            return parsed.replace(tzinfo=TASHKENT).astimezone(timezone.utc)
        except ValueError:
            pass
    moment = _parse_moment(raw)
    if moment is None:
        raise TournamentError(
            "Vaqt formati noto'g'ri. Masalan: 2026-11-12 20:00, "
            "ertaga 21:00 yoki +3 kun."
        )
    return moment


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


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return default


def _load_bracket(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if isinstance(value, dict):
        value = value.get("rounds") or value.get("bracket") or []
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, dict)]


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
    room_link: str = ""
    room_sent_at: str = ""
    bracket_data: list[dict[str, Any]] = field(default_factory=list)

    @property
    def starts_moment(self) -> datetime:
        return _parse_moment(self.starts_at) or _now()

    @property
    def game_title(self) -> str:
        return GAME_TITLES.get(self.game, self.game)

    @property
    def game_type(self) -> str:
        return self.game

    @property
    def start_time(self) -> str:
        return self.starts_at

    @property
    def max_participants(self) -> int:
        return self.max_players

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game": self.game,
            "game_type": self.game,
            "game_title": self.game_title,
            "title": self.title,
            "entry_fee": self.entry_fee,
            "prize_pool": self.prize_pool,
            "starts_at": self.starts_at,
            "start_time": self.starts_at,
            "starts_at_local": format_local(self.starts_at),
            "countdown": countdown_text(self.starts_at),
            "seconds_left": seconds_left(self.starts_at),
            "status": self.status,
            "max_players": self.max_players,
            "max_participants": self.max_players,
            "created_by": self.created_by,
            "reminded_at": self.reminded_at,
            "room_link": self.room_link,
            "room_sent_at": self.room_sent_at,
            "bracket_data": list(self.bracket_data),
        }


@dataclass(frozen=True)
class Participant:
    """Turnirga yozilgan öyinçi."""

    user_id: int
    username: str = ""
    full_name: str = ""
    score: int = 0
    status: str = "REGISTERED"
    registered_at: str = ""

    @property
    def joined_at(self) -> str:
        return self.registered_at

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
            "score": self.score,
            "status": self.status,
            "registered_at": self.registered_at,
            "joined_at": self.registered_at,
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
        game=str(_first(row.get("game_type"), row.get("game"), default="mixed")),
        title=str(row.get("title") or ""),
        entry_fee=int(_first(row.get("entry_fee"), default=ENTRY_FEE) or ENTRY_FEE),
        prize_pool=int(row.get("prize_pool") or 0),
        starts_at=str(_first(row.get("start_time"), row.get("starts_at"), default="")),
        status=normalize_status(row.get("status")),
        max_players=int(
            _first(
                row.get("max_participants"),
                row.get("max_players"),
                default=MAX_PARTICIPANTS,
            )
            or MAX_PARTICIPANTS
        ),
        created_by=int(row.get("created_by") or 0),
        reminded_at=str(row.get("reminded_at") or ""),
        room_link=str(_first(row.get("room_link"), row.get("room_url"), default="")),
        room_sent_at=str(row.get("room_sent_at") or ""),
        bracket_data=_load_bracket(
            _first(row.get("bracket_data"), row.get("bracket"), default=[])
        ),
    )


def _participant_from_row(row: dict[str, Any]) -> Participant:
    return Participant(
        user_id=int(row.get("user_id") or 0),
        username=str(row.get("username") or ""),
        full_name=str(row.get("full_name") or ""),
        score=int(row.get("score") or 0),
        status=str(row.get("status") or "REGISTERED"),
        registered_at=str(
            _first(row.get("registered_at"), row.get("joined_at"), default="")
        ),
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
        self._read_failed = False

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
        """Turnirlar qatorlari; Supabase yoqilganda faqat bazadan o'qiladi."""
        if not self.enabled:
            return list(self._tournaments.values())
        try:
            rows = self.client.table(TOURNAMENTS_TABLE).select("*").execute().data or []
            self._read_failed = False
            return [dict(row) for row in rows]
        except Exception:
            self._read_failed = True
            logger.exception("Turnirlar ro'yxatini öqib bölmadi")
            return []

    def _participant_rows(self, tournament_id: str) -> list[dict[str, Any]]:
        tid = str(tournament_id)
        if not self.enabled:
            return list(self._participants.get(tid, []))
        try:
            rows = (
                self.client.table(PARTICIPANTS_TABLE)
                .select("*")
                .eq("tournament_id", tid)
                .execute()
                .data
                or []
            )
            return [dict(row) for row in rows]
        except Exception:
            logger.exception("Turnir qatnaşçilarini öqib bölmadi: %s", tid)
            return []

    def _tournament_row(self, tournament: Tournament) -> dict[str, Any]:
        return {
            "id": tournament.id,
            "title": tournament.title,
            "game_type": tournament.game,
            "game": tournament.game,
            "prize_pool": tournament.prize_pool,
            "max_participants": tournament.max_players,
            "max_players": tournament.max_players,
            "status": tournament.status,
            "start_time": tournament.starts_at,
            "starts_at": tournament.starts_at,
            "bracket_data": list(tournament.bracket_data),
            "entry_fee": tournament.entry_fee,
            "created_by": tournament.created_by,
        }
        # Eski jadvalda ustun bölmasa ham yangi turnir yaratilaveradi.
        if tournament.room_link:
            row["room_link"] = tournament.room_link

    def _save_tournament(self, tournament: Tournament) -> None:
        row = self._tournament_row(tournament)
        if not self.enabled:
            with self._lock:
                self._tournaments[tournament.id] = {
                    **row,
                    "reminded_at": tournament.reminded_at,
                }
            return
        try:
            safe_insert(self.client, TOURNAMENTS_TABLE, row)
        except Exception as exc:
            logger.exception("Turnirni saqlab bölmadi: %s", tournament.id)
            raise TournamentError(
                "Turnirni Supabase'ga saqlab bo'lmadi. Qayta urinib ko'ring."
            ) from exc

    def _update_tournament(
        self, tournament_id: str, changes: dict[str, Any]
    ) -> None:
        """Turnir maydonlarini eski va yangi ustun nomlarida yangilaydi."""
        row = dict(changes)
        if "game" in row:
            row["game_type"] = row["game"]
            row["game"] = row["game"]
        if "starts_at" in row:
            row["start_time"] = row["starts_at"]
            row["starts_at"] = row["starts_at"]
        if "max_players" in row:
            row["max_participants"] = row["max_players"]
            row["max_players"] = row["max_players"]
        with self._lock:
            cached = self._tournaments.get(str(tournament_id))
            if cached is not None:
                cached.update(row)
        if not self.enabled:
            return
        try:
            safe_update(
                self.client,
                TOURNAMENTS_TABLE,
                row,
                {"id": str(tournament_id)},
            )
        except Exception as exc:
            logger.exception("Turnirni yangilab bölmadi: %s", tournament_id)
            raise TournamentError(
                "Turnir sozlamasini Supabase'ga saqlab bo'lmadi."
            ) from exc

    def _save_participant(
        self, tournament_id: str, participant: Participant
    ) -> None:
        row = {
            "tournament_id": str(tournament_id),
            "user_id": participant.user_id,
            "username": participant.username,
            "full_name": participant.full_name,
            "score": participant.score,
            "status": participant.status,
            "registered_at": participant.registered_at,
            "joined_at": participant.registered_at,
        }
        if not self.enabled:
            with self._lock:
                bucket = self._participants.setdefault(str(tournament_id), [])
                if all(
                    int(item.get("user_id") or 0) != participant.user_id
                    for item in bucket
                ):
                    bucket.append(row)
            return
        try:
            safe_insert(self.client, PARTICIPANTS_TABLE, row)
        except Exception as exc:
            logger.exception(
                "Turnir qatnaşçisini saqlab bölmadi: %s %s",
                tournament_id,
                participant.user_id,
            )
            raise TournamentError(
                "Qatnashchini Supabase'ga saqlab bo'lmadi. Qayta urinib ko'ring."
            ) from exc

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------
    def get(self, tournament_id: str) -> Tournament | None:
        key = str(tournament_id or "").strip()
        if not key:
            return None
        if not self.enabled:
            with self._lock:
                cached = self._tournaments.get(key)
            return _tournament_from_row(cached) if cached is not None else None
        for row in self._rows():
            if str(row.get("id") or "") == key:
                return _tournament_from_row(row)
        return None

    def all(self) -> list[Tournament]:
        tournaments = [_tournament_from_row(row) for row in self._rows()]
        tournaments.sort(key=lambda item: item.starts_moment)
        return tournaments

    def active(self, now: datetime | None = None) -> list[Tournament]:
        """Ro'yxatga olish uchun ochiq turnirlar.

        ``registration`` va ``OPEN`` bir xil qabul qilinadi; ``active``
        turnirlar ro'yxatga olish uchun emas, faqat ko'rish uchun xizmat
        qiladi.
        """
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

    def visible(self, now: datetime | None = None) -> list[Tournament]:
        """Mini App uchun ochiq va boshlangan (faol) turnirlar."""
        moment = now or _now()
        self.ensure_weekly(moment)
        result = []
        for tournament in self.all():
            if tournament.status == ACTIVE:
                result.append(tournament)
            elif tournament.status == OPEN and (
                tournament.starts_moment + timedelta(minutes=JOIN_GRACE_MINUTES) > moment
            ):
                result.append(tournament)
        return result

    def current(self, now: datetime | None = None) -> Tournament | None:
        """Admin panelida tahrirlanadigan joriy turnir."""
        moment = now or _now()
        self.ensure_weekly(moment)
        rows = self.all()
        for tournament in rows:
            if tournament.status == ACTIVE:
                return tournament
        for tournament in rows:
            if tournament.status == OPEN and tournament.starts_moment > moment:
                return tournament
        return rows[0] if rows else None

    def participants(self, tournament_id: str) -> list[Participant]:
        rows = self._participant_rows(tournament_id)
        rows = sorted(
            rows,
            key=lambda row: str(
                _first(row.get("registered_at"), row.get("joined_at"), default="")
            ),
        )
        return [_participant_from_row(row) for row in rows]

    def participant_count(self, tournament_id: str) -> int:
        return len(self._participant_rows(tournament_id))

    def joined(self, tournament_id: str, user_id: int) -> bool:
        return any(
            int(row.get("user_id") or 0) == int(user_id)
            and str(row.get("status") or "REGISTERED").upper() != "CANCELLED"
            for row in self._participant_rows(tournament_id)
        )

    def _build_bracket(self, participants: list[Participant]) -> list[dict[str, Any]]:
        """Qatnashchilardan ko'rgazma bracket yasaydi."""
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
                next_round.append(left)
            rounds.append({"round": round_number, "matches": matches})
            current = next_round
            round_number += 1
            if round_number > 10:  # cheksiz sikl himoyasi
                break
        return rounds

    def bracket(self, tournament_id: str) -> list[dict[str, Any]]:
        """Saqlangan yoki qatnashchilardan yasalgan bracket."""
        tournament = self.get(tournament_id)
        if tournament is not None and tournament.bracket_data:
            return list(tournament.bracket_data)
        return self._build_bracket(self.participants(tournament_id))

    def payload(self, user_id: int | None = None) -> dict[str, Any]:
        """Mini App va bot uchun to'liq turnir ma'lumoti."""
        tournaments = []
        for tournament in self.visible():
            participants = self.participants(tournament.id)
            bracket = (
                list(tournament.bracket_data)
                if tournament.bracket_data
                else self._build_bracket(participants)
            )
            data = tournament.as_dict()
            data["participants_count"] = len(participants)
            data["participants"] = [item.as_dict() for item in participants]
            data["bracket"] = bracket
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
                "Öyin nomi notöğri. Mumkin: bunker, mafiya, josus, alias, "
                "bomba, mixed."
            )
        moment = _parse_moment(starts_at)
        if moment is None:
            raise TournamentError("Boşlaniş vaqti notöğri (ISO format kerak).")
        if moment <= _now():
            raise TournamentError("Boşlaniş vaqti kelajakda bölishi kerak.")
        if entry_fee < 0 or prize_pool < 0:
            raise TournamentError("Narx va sovrin manfiy bölmaydi.")
        max_count = int(max_players)
        if max_count < MIN_PARTICIPANTS:
            raise TournamentError(
                f"Qatnashchilar soni kamida {MIN_PARTICIPANTS} bölishi kerak."
            )
        tournament = Tournament(
            id=uuid.uuid4().hex[:10],
            game=key,
            title=(title or "").strip() or f"{GAME_TITLES[key]} Haftalik Turniri",
            entry_fee=int(entry_fee),
            prize_pool=int(prize_pool),
            starts_at=moment.isoformat(),
            max_players=max_count,
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
        rows = self.all()
        if self._read_failed:
            return None
        for tournament in rows:
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
            raise TournamentFullError("Joylar to'ldi ⛔")

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
            score=0,
            status="REGISTERED",
            registered_at=now.isoformat(),
        )
        try:
            self._save_participant(tournament.id, participant)
        except TournamentError:
            # To'lov o'tib, qatnashchi saqlanmasa — pulni/çiptani qaytaramiz.
            if ticket_used:
                current = self.shop.entry(uid, TICKET_SLUG)
                self.shop._save_entry(
                    uid,
                    InventoryEntry(
                        item_slug=TICKET_SLUG,
                        quantity=current.quantity + 1,
                        is_equipped=False,
                    ),
                )
            elif expense:
                self.economy.add_coins(uid, expense)
            raise
        return JoinResult(
            tournament=tournament,
            account=account,
            ticket_used=ticket_used,
            expense=expense,
            participants_count=self.participant_count(tournament.id),
        )

    def leave(self, user_id: int, tournament_id: str) -> Tournament:
        """Turnirdan ro'yxatdan chiqadi (qatnashchi yozuvi o'chiriladi)."""
        uid = int(user_id)
        tournament = self.get(tournament_id)
        if tournament is None:
            raise TournamentNotFoundError("Turnir topilmadi.")
        now = _now()
        if tournament.status != OPEN:
            raise TournamentClosedError("Turnir allaqachon boshlangan.")
        if tournament.starts_moment + timedelta(minutes=JOIN_GRACE_MINUTES) <= now:
            raise TournamentClosedError("Turnir boshlanib ketgan — ro'yxat yopilgan.")
        if not self.joined(tournament.id, uid):
            raise TournamentError("Siz bu turnirga yozilmagansiz.")
        tid = str(tournament.id)
        if not self.enabled:
            with self._lock:
                bucket = self._participants.get(tid, [])
                self._participants[tid] = [
                    row for row in bucket if int(row.get("user_id") or 0) != uid
                ]
            return tournament
        try:
            (
                self.client.table(PARTICIPANTS_TABLE)
                .delete()
                .eq("tournament_id", tid)
                .eq("user_id", uid)
                .execute()
            )
        except Exception as exc:
            logger.exception(
                "Turnir qatnaşçisini o'çirib bölmadi: %s %s", tid, uid
            )
            raise TournamentError(
                "Ro'yxatdan chiqishni Supabase'ga saqlab bo'lmadi."
            ) from exc
        return tournament

    def set_max_participants(
        self, tournament_id: str, value: int
    ) -> Tournament:
        """Admin panelidan qatnashchilar limitini yangilaydi."""
        tournament = self.get(tournament_id)
        if tournament is None:
            raise TournamentNotFoundError("Turnir topilmadi.")
        try:
            count = int(value)
        except (TypeError, ValueError):
            raise TournamentError("Qatnashchilar soni butun son bo'lishi kerak.") from None
        if count < MIN_PARTICIPANTS:
            raise TournamentError(
                f"Qatnashchilar soni kamida {MIN_PARTICIPANTS} bo'lishi kerak."
            )
        if count < self.participant_count(tournament.id):
            raise TournamentError(
                "Yangi limit hozirgi qatnashchilar sonidan kam bo'lmaydi."
            )
        self._update_tournament(tournament.id, {"max_players": count})
        return self.get(tournament.id) or tournament

    def set_start_time(self, tournament_id: str, value: Any) -> Tournament:
        """Admin panelidan boshlanish vaqtini yangilaydi."""
        tournament = self.get(tournament_id)
        if tournament is None:
            raise TournamentNotFoundError("Turnir topilmadi.")
        moment = parse_admin_time(value)
        if moment <= _now():
            raise TournamentError("Boshlanish vaqti kelajakda bo'lishi kerak.")
        self._update_tournament(tournament.id, {"starts_at": moment.isoformat()})
        return self.get(tournament.id) or tournament

    def set_prize_pool(self, tournament_id: str, value: int) -> Tournament:
        """Admin panelidan sovrin miqdorini yangilaydi."""
        tournament = self.get(tournament_id)
        if tournament is None:
            raise TournamentNotFoundError("Turnir topilmadi.")
        try:
            prize = int(value)
        except (TypeError, ValueError):
            raise TournamentError("Sovrin miqdori butun son bo'lishi kerak.") from None
        if prize < 0:
            raise TournamentError("Sovrin miqdori manfiy bo'lmaydi.")
        self._update_tournament(tournament.id, {"prize_pool": prize})
        return self.get(tournament.id) or tournament

    def set_game(self, tournament_id: str, value: str) -> Tournament:
        """Admin panelidan o'yin turini yangilaydi."""
        tournament = self.get(tournament_id)
        if tournament is None:
            raise TournamentNotFoundError("Turnir topilmadi.")
        game = str(value or "").strip().lower()
        if game not in GAME_TITLES:
            raise TournamentError("O'yin turi noto'g'ri.")
        self._update_tournament(tournament.id, {"game": game})
        return self.get(tournament.id) or tournament

    def set_room_link(self, tournament_id: str, value: Any) -> Tournament:
        """Admin panelidan turnir xonasi havolasini yangilaydi."""
        tournament = self.get(tournament_id)
        if tournament is None:
            raise TournamentNotFoundError("Turnir topilmadi.")
        link = str(value or "").strip()
        if link in {"", "-", "—", "yoq", "yo'q"}:
            link = ""
        elif link.startswith("t.me/"):
            link = f"https://{link}"
        if link:
            if any(char.isspace() for char in link):
                raise TournamentError("Xona havolasida bo'sh joy bo'lmaydi.")
            if not link.startswith(("https://", "http://")):
                raise TournamentError(
                    "Xona havolasi https:// yoki http:// bilan boshlanishi kerak."
                )
            if len(link) > 500:
                raise TournamentError("Xona havolasi juda uzun.")
        self._update_tournament(
            tournament.id,
            {"room_link": link, "room_sent_at": None},
        )
        return self.get(tournament.id) or tournament

    def start(self, tournament_id: str) -> Tournament:
        """Ro'yxatdan o'tganlardan bracket yasab, turnirni ACTIVE qiladi."""
        tournament = self.get(tournament_id)
        if tournament is None:
            raise TournamentNotFoundError("Turnir topilmadi.")
        if tournament.status == ACTIVE:
            raise TournamentClosedError("Turnir allaqachon boshlangan.")
        if tournament.status != OPEN:
            raise TournamentClosedError("Turnirni boshlab bo'lmaydi.")
        participants = self.participants(tournament.id)
        if len(participants) < MIN_PARTICIPANTS:
            raise TournamentError(
                f"Boshlash uchun kamida {MIN_PARTICIPANTS} nafar qatnashchi kerak."
            )
        bracket = self._build_bracket(participants)
        self._update_tournament(
            tournament.id,
            {"status": ACTIVE, "bracket_data": bracket},
        )
        updated = self.get(tournament.id) or tournament
        logger.info(
            "Turnir boshlandi: %s, %s qatnashchi, %s raund",
            tournament.id,
            len(participants),
            len(bracket),
        )
        return updated

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
        self._update_tournament(
            tournament.id,
            {"reminded_at": moment},
        )

    def due_room_links(self, now: datetime | None = None) -> list[Tournament]:
        """Xona havolasi yuborilishi kerak bo'lgan boshlangan turnirlar.

        Faqat yaqinda boshlangan (24 soat ichida) va havolasi hali
        yuborilmagan faol turnirlar qaytariladi. Bu bot qayta ishga
        tushganda eski turnirlar uchun havola yuborilishining oldini oladi.
        """
        moment = now or _now()
        result = []
        for tournament in self.all():
            if tournament.status != ACTIVE:
                continue
            if not tournament.room_link or tournament.room_sent_at:
                continue
            if tournament.starts_moment > moment + timedelta(minutes=1):
                continue
            if moment - tournament.starts_moment > timedelta(hours=24):
                continue
            result.append(tournament)
        return result

    def mark_room_sent(self, tournament_id: str) -> None:
        """Xona havolasi qatnashchilarga yuborilganini belgilaydi."""
        tournament = self.get(tournament_id)
        if tournament is None:
            return
        self._update_tournament(
            tournament.id,
            {"room_sent_at": _now().isoformat()},
        )


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
