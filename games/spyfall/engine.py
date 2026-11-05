"""«Josus» (Spyfall) o'yin dvigateli.

Dvigatel faqat qoidalar bilan shug'ullanadi: xona holati, rollarni
tarqatish, joyni taxmin qilish va ovoz berish. Tangalar, Telegram va
saqlash qatlamlari manager/API tomonida hal qilinadi.

Odatiy oqim::

    room = SpyfallRoom("SPY482", host_id=1)
    room.add_player(1, "Ali", is_host=True)
    room.add_player(2, "Vali")
    room.add_player(3, "Zilola")
    room.start()
    view = room.player_view(1)      # rol va lokatsiya
    room.guess(2, "toyxona")        # noto'g'ri taxmin -> tinch aholi yutadi
    room.tally()                    # ovozlarni sanash
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from games.spyfall.locations import (
    LOCATIONS,
    Location,
    get_location,
    random_location,
)

MIN_PLAYERS = 3
MAX_PLAYERS = 12
# 7 kishidan boshlab ikki josus bo'lishi mumkin.
DOUBLE_SPY_MIN_PLAYERS = 7
DEFAULT_ROUND_SECONDS = 300
HINT_PRICE = 20
HINT_ELIMINATIONS = 3
PLAYER_WIN_REWARD = 25
SPY_WIN_REWARD = 35

SPY_WARNING = (
    "🕵️ SIZ JOSUSSIZ! Vazifangiz: savol-javoblar orqali qayerda "
    "ekanligingizni topish va o'zingizni sezdirmaslik!"
)


class SpyfallError(Exception):
    """O'yin qoidasi yoki holati bilan bog'liq xatolik."""


class Phase(str, Enum):
    """Xona bosqichlari."""

    LOBBY = "LOBBY"
    PLAYING = "PLAYING"
    VOTING = "VOTING"
    FINISHED = "FINISHED"
    EXPIRED = "EXPIRED"


class Winner(str, Enum):
    """O'yin g'olibi."""

    PLAYERS = "players"
    SPIES = "spies"


WIN_REASONS: dict[Winner, str] = {
    Winner.PLAYERS: "Josus topildi — tinch aholi g'alaba qozondi!",
    Winner.SPIES: "Josus sezilmay qoldi — u g'alaba qozondi!",
}


@dataclass
class SpyfallPlayer:
    """Bitta ishtirokchi."""

    user_id: int
    name: str = ""
    is_host: bool = False
    role: str = ""
    is_spy: bool = False
    has_voted: bool = False
    hint_exclusions: list[str] = field(default_factory=list)

    def display_name(self) -> str:
        return self.name.strip() or f"ID {self.user_id}"

    def reset_for_round(self) -> None:
        self.role = ""
        self.is_spy = False
        self.has_voted = False
        self.hint_exclusions = []


@dataclass(frozen=True)
class GuessOutcome:
    """Josusning joyni taxmin qilishi natijasi."""

    spy_id: int
    guessed_key: str
    guessed_name: str
    correct: bool
    winner: Winner
    location_key: str
    location_name: str

    @property
    def reason(self) -> str:
        if self.correct:
            return (
                f"🕵️ Josus joyni topdi: «{self.location_name}»! "
                "Josus g'alaba qozondi."
            )
        return (
            f"❌ Josus xato taxmin qildi: «{self.guessed_name}». "
            f"Asl joy — «{self.location_name}». Tinch aholi g'alaba qozondi!"
        )


@dataclass(frozen=True)
class VoteOutcome:
    """Ovoz berish yakuni."""

    winner: Winner
    accused_id: int | None
    accused_name: str
    spies: tuple[int, ...]
    counts: dict[int, int]
    tie: bool
    reason: str


class SpyfallRoom:
    """Bitta Josus partiyasining to'liq holati."""

    def __init__(
        self,
        code: str,
        host_id: int,
        *,
        chat_id: int = 0,
        round_seconds: int = DEFAULT_ROUND_SECONDS,
    ) -> None:
        normalized = (code or "").strip().upper()
        if not normalized:
            raise SpyfallError("Xona kodi bo'sh bo'lishi mumkin emas")
        self.code = normalized
        self.host_id = int(host_id)
        self.chat_id = int(chat_id or 0)
        self.phase = Phase.LOBBY
        self.players: dict[int, SpyfallPlayer] = {}
        self.location: Location | None = None
        self.spy_ids: set[int] = set()
        self.votes: dict[int, int] = {}
        self.winner: Winner | None = None
        self.finish_reason = ""
        self.round_seconds = max(30, int(round_seconds))
        self.deadline: float | None = None
        self.rewards_granted = False

    # ------------------------------------------------------------------ holat
    def get_player(self, user_id: int) -> SpyfallPlayer:
        player = self.players.get(int(user_id))
        if player is None:
            raise SpyfallError(f"O'yinchi {user_id} xonada topilmadi")
        return player

    @property
    def player_count(self) -> int:
        return len(self.players)

    @property
    def is_full(self) -> bool:
        return len(self.players) >= MAX_PLAYERS

    def add_player(
        self, user_id: int, name: str = "", *, is_host: bool = False
    ) -> SpyfallPlayer:
        """Lobby bosqichida o'yinchi qo'shadi."""
        if self.phase is not Phase.LOBBY:
            raise SpyfallError("O'yin boshlanganidan keyin qo'shilish mumkin emas")
        uid = int(user_id)
        if uid in self.players:
            raise SpyfallError("Siz allaqachon xonadasiz")
        if self.is_full:
            raise SpyfallError(
                f"Xona to'lgan: eng ko'pi bilan {MAX_PLAYERS} o'yinchi"
            )
        player = SpyfallPlayer(
            user_id=uid,
            name=(name or "").strip()[:64],
            is_host=bool(is_host) or uid == self.host_id,
        )
        self.players[uid] = player
        return player

    # ------------------------------------------------------------------ start
    def start(
        self,
        *,
        now: float | None = None,
        rng: random.Random | None = None,
    ) -> None:
        """Rollarni tarqatib, o'yinni boshlaydi."""
        if self.phase is not Phase.LOBBY:
            raise SpyfallError("O'yin allaqachon boshlangan")
        if len(self.players) < MIN_PLAYERS:
            raise SpyfallError(
                f"Boshlash uchun kamida {MIN_PLAYERS} o'yinchi kerak, "
                f"{len(self.players)} ta bor"
            )

        chooser = rng or random
        ids = list(self.players)
        spy_count = 2 if len(ids) >= DOUBLE_SPY_MIN_PLAYERS else 1
        spies = set(chooser.sample(ids, spy_count))
        location = random_location(chooser)

        self.location = location
        self.spy_ids = spies
        self.votes.clear()
        self.winner = None
        self.finish_reason = ""
        self.deadline = (now if now is not None else time.time()) + self.round_seconds
        self.phase = Phase.PLAYING
        for uid, player in self.players.items():
            player.reset_for_round()
            player.is_spy = uid in spies
            player.role = "" if player.is_spy else chooser.choice(list(location.roles))

    # ------------------------------------------------------------------ vaqt
    def ensure_phase(self, now: float | None = None) -> Phase:
        """Muddat tugagan bo'lsa PLAYING'dan VOTING'ga o'tadi."""
        if (
            self.phase is Phase.PLAYING
            and self.deadline is not None
            and (now if now is not None else time.time()) >= self.deadline
        ):
            self.phase = Phase.VOTING
        return self.phase

    def seconds_left(self, now: float | None = None) -> int:
        if self.deadline is None:
            return 0
        current = now if now is not None else time.time()
        return max(0, int(round(self.deadline - current)))

    # ------------------------------------------------------------------ taxmin
    def guess(
        self, user_id: int, location_key: str, *, now: float | None = None
    ) -> GuessOutcome:
        """Josus joyni taxmin qiladi: to'g'ri — josus, xato — tinch aholi."""
        self.ensure_phase(now)
        if self.phase not in (Phase.PLAYING, Phase.VOTING):
            raise SpyfallError("Joyni faqat o'yin davomida taxmin qilish mumkin")
        player = self.get_player(user_id)
        if not player.is_spy:
            raise SpyfallError("Joyni faqat josus taxmin qilishi mumkin")
        assert self.location is not None
        try:
            guessed = get_location(location_key)
        except KeyError as exc:
            raise SpyfallError(f"Noma'lum lokatsiya: {location_key!r}") from exc

        correct = guessed.key == self.location.key
        winner = Winner.SPIES if correct else Winner.PLAYERS
        outcome = GuessOutcome(
            spy_id=player.user_id,
            guessed_key=guessed.key,
            guessed_name=guessed.name,
            correct=correct,
            winner=winner,
            location_key=self.location.key,
            location_name=self.location.name,
        )
        self.finish(winner, outcome.reason)
        return outcome

    # ------------------------------------------------------------------ ovoz
    def cast_vote(self, user_id: int, target_id: int, *, now: float | None = None) -> None:
        """Ovoz beradi (har bir o'yinchi bir marta)."""
        self.ensure_phase(now)
        if self.phase not in (Phase.PLAYING, Phase.VOTING):
            raise SpyfallError("Ovoz berish vaqti emas")
        voter = self.get_player(user_id)
        target = self.get_player(target_id)
        if voter.user_id == target.user_id:
            raise SpyfallError("O'zingizga ovoz bera olmaysiz")
        if voter.has_voted:
            raise SpyfallError("Siz allaqachon ovoz bergansiz")
        self.votes[voter.user_id] = target.user_id
        voter.has_voted = True

    @property
    def all_voted(self) -> bool:
        return bool(self.players) and len(self.votes) >= len(self.players)

    @property
    def vote_counts(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for target in self.votes.values():
            counts[target] = counts.get(target, 0) + 1
        return counts

    def tally(self) -> VoteOutcome:
        """Ovozlarni sanaydi va g'olibni e'lon qiladi."""
        if self.phase not in (Phase.PLAYING, Phase.VOTING):
            raise SpyfallError("Ovozlarni faqat o'yin davomida sanash mumkin")
        if not self.votes:
            raise SpyfallError("Hali hech kim ovoz bermagan")
        self.ensure_phase()

        counts = self.vote_counts
        highest = max(counts.values())
        leaders = sorted(uid for uid, count in counts.items() if count == highest)
        spies = tuple(sorted(self.spy_ids))

        if len(leaders) > 1:
            reason = (
                "Ovozlar teng bo'ldi — hech kim haydalmadi va Josus sezilmay qoldi. "
                "Josus g'alaba qozondi."
            )
            self.finish(Winner.SPIES, reason)
            return VoteOutcome(
                winner=Winner.SPIES,
                accused_id=None,
                accused_name="",
                spies=spies,
                counts=counts,
                tie=True,
                reason=reason,
            )

        accused = self.get_player(leaders[0])
        if accused.is_spy:
            reason = (
                f"🗳 «{accused.display_name()}» Josus edi! "
                "Tinch aholi g'alaba qozondi."
            )
            self.finish(Winner.PLAYERS, reason)
        else:
            reason = (
                f"😢 «{accused.display_name()}» begunoh edi — Josus omon qoldi va "
                "g'alaba qozondi."
            )
            self.finish(Winner.SPIES, reason)
        return VoteOutcome(
            winner=self.winner or Winner.SPIES,
            accused_id=accused.user_id,
            accused_name=accused.display_name(),
            spies=spies,
            counts=counts,
            tie=False,
            reason=reason,
        )

    # ------------------------------------------------------------------ hint
    def add_hint(
        self, user_id: int, *, rng: random.Random | None = None
    ) -> tuple[str, ...]:
        """Josusga 3 ta noto'g'ri lokatsiyani ko'rsatadi (booster)."""
        self.ensure_phase()
        if self.phase not in (Phase.PLAYING, Phase.VOTING):
            raise SpyfallError("Maslahat faqat o'yin davomida ishlaydi")
        player = self.get_player(user_id)
        if not player.is_spy:
            raise SpyfallError("Radar faqat Josus uchun")
        if player.hint_exclusions:
            return tuple(player.hint_exclusions)
        assert self.location is not None
        wrong = [item.key for item in LOCATIONS if item.key != self.location.key]
        chooser = rng or random
        chosen = tuple(chooser.sample(wrong, HINT_ELIMINATIONS))
        player.hint_exclusions = list(chosen)
        return chosen

    # ------------------------------------------------------------------ finish
    def finish(self, winner: Winner, reason: str = "") -> None:
        """O'yinni g'olib bilan yakunlaydi."""
        self.phase = Phase.FINISHED
        self.winner = winner
        self.finish_reason = reason or WIN_REASONS.get(winner, "")
        self.deadline = None

    @property
    def winner_ids(self) -> list[int]:
        """G'olib o'yinchilar id'lari (mukofot uchun)."""
        if self.winner is None:
            return []
        return sorted(
            uid for uid, player in self.players.items() if player.is_spy == (self.winner is Winner.SPIES)
        )

    @property
    def reward_per_winner(self) -> int:
        return SPY_WIN_REWARD if self.winner is Winner.SPIES else PLAYER_WIN_REWARD

    # ------------------------------------------------------------------ view
    def player_view(self, user_id: int, *, now: float | None = None) -> dict[str, Any]:
        """Bitta o'yinchi ko'radigan ma'lumot (josusga joy ko'rsatilmaydi)."""
        self.ensure_phase(now)
        player = self.get_player(user_id)
        location = self.location
        is_spy = player.is_spy
        finished = self.phase is Phase.FINISHED
        reveal = finished or not is_spy
        teammates = (
            [
                {"user_id": uid, "name": self.players[uid].display_name()}
                for uid in sorted(self.spy_ids)
                if uid != player.user_id
            ]
            if is_spy and not finished
            else []
        )
        return {
            "user_id": player.user_id,
            "name": player.display_name(),
            "is_host": player.user_id == self.host_id,
            "is_spy": is_spy,
            "role": "spy" if is_spy else "player",
            "role_name": "" if is_spy else player.role,
            "location": location.key if (location and reveal) else None,
            "location_name": location.name if (location and reveal) else None,
            "location_emoji": location.emoji if (location and reveal) else None,
            "spy_warning": SPY_WARNING if is_spy and not finished else "",
            "teammates": teammates,
            "has_voted": player.has_voted,
            "hint_exclusions": list(player.hint_exclusions),
            "hint_price": HINT_PRICE,
            "reward": self.reward_per_winner if finished else 0,
        }

    def public_state(self, viewer_id: int = 0, *, now: float | None = None) -> dict[str, Any]:
        """Hamma ko'radigan xona holati."""
        self.ensure_phase(now)
        finished = self.phase is Phase.FINISHED
        counts = self.vote_counts
        return {
            "code": self.code,
            "status": self.phase.value,
            "host_id": self.host_id,
            "chat_id": self.chat_id,
            "players_count": len(self.players),
            "max_players": MAX_PLAYERS,
            "min_players": MIN_PLAYERS,
            "players": [
                {
                    "user_id": player.user_id,
                    "name": player.display_name(),
                    "is_host": player.user_id == self.host_id,
                    "is_me": player.user_id == int(viewer_id or 0),
                    "has_voted": player.has_voted,
                    "votes": counts.get(player.user_id, 0),
                    "is_spy": player.is_spy if finished else None,
                }
                for player in self.players.values()
            ],
            "votes_count": len(self.votes),
            "all_voted": self.all_voted,
            "winner": self.winner.value if self.winner else None,
            "finish_reason": self.finish_reason,
            "spy_ids": sorted(self.spy_ids) if finished else [],
            "location": (
                {
                    "key": self.location.key,
                    "name": self.location.name,
                    "emoji": self.location.emoji,
                    "roles": list(self.location.roles),
                }
                if finished and self.location
                else None
            ),
            "deadline": self.deadline,
            "seconds_left": self.seconds_left(now),
            "round_seconds": self.round_seconds,
        }

    # ------------------------------------------------------------------ save
    def to_state(self) -> dict[str, Any]:
        """Saqlash uchun JSON holat."""
        return {
            "code": self.code,
            "host_id": self.host_id,
            "chat_id": self.chat_id,
            "phase": self.phase.value,
            "location": self.location.key if self.location else "",
            "spy_ids": sorted(self.spy_ids),
            "votes": {str(voter): int(target) for voter, target in self.votes.items()},
            "winner": self.winner.value if self.winner else None,
            "finish_reason": self.finish_reason,
            "round_seconds": self.round_seconds,
            "deadline": self.deadline,
            "rewards_granted": self.rewards_granted,
            "players": {
                str(uid): {
                    "user_id": player.user_id,
                    "name": player.name,
                    "is_host": player.is_host,
                    "role": player.role,
                    "is_spy": player.is_spy,
                    "has_voted": player.has_voted,
                    "hint_exclusions": list(player.hint_exclusions),
                }
                for uid, player in self.players.items()
            },
        }

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "SpyfallRoom":
        """``to_state`` natijasidan xonani tiklaydi."""
        room = cls(
            code=str(state["code"]),
            host_id=int(state["host_id"]),
            chat_id=int(state.get("chat_id") or 0),
            round_seconds=int(state.get("round_seconds") or DEFAULT_ROUND_SECONDS),
        )
        try:
            room.phase = Phase(str(state.get("phase") or "LOBBY").upper())
        except ValueError as exc:
            raise SpyfallError("Saqlangan holatda noto'g'ri bosqich") from exc

        location_key = str(state.get("location") or "").strip()
        room.location = get_location(location_key) if location_key else None
        room.spy_ids = {int(uid) for uid in state.get("spy_ids") or []}
        room.votes = {
            int(voter): int(target)
            for voter, target in (state.get("votes") or {}).items()
        }
        winner = state.get("winner")
        room.winner = Winner(str(winner)) if winner else None
        room.finish_reason = str(state.get("finish_reason") or "")
        deadline = state.get("deadline")
        room.deadline = float(deadline) if deadline is not None else None
        room.rewards_granted = bool(state.get("rewards_granted"))

        for raw_uid, raw_player in (state.get("players") or {}).items():
            player = SpyfallPlayer(
                user_id=int(raw_uid),
                name=str(raw_player.get("name") or "")[:64],
                is_host=bool(raw_player.get("is_host")),
                role=str(raw_player.get("role") or "")[:64],
                is_spy=bool(raw_player.get("is_spy")),
                has_voted=bool(raw_player.get("has_voted")),
                hint_exclusions=[
                    str(item) for item in raw_player.get("hint_exclusions") or []
                ],
            )
            room.players[player.user_id] = player
        return room
